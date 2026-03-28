"""
Cache de respuestas LLM en PostgreSQL.

Usa SHA-256 del contenido de los mensajes + modelo como key.
Incrementa un contador de hits por cada cache hit para monitoreo.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

import structlog
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import LLMCache

logger = structlog.get_logger(__name__)


def _compute_hash(messages: list[dict], model: str) -> str:
    """Genera un hash SHA-256 deterministico para (messages, model)."""
    payload = json.dumps({"messages": messages, "model": model}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


async def get_cached_response(
    session: AsyncSession,
    messages: list[dict],
    model: str,
) -> dict | None:
    """
    Busca una respuesta cacheada.

    Returns:
        Dict con {"response": ..., "token_usage": ...} o None si no hay cache.
    """
    prompt_hash = _compute_hash(messages, model)

    result = await session.execute(
        select(LLMCache).where(
            LLMCache.prompt_hash == prompt_hash,
            LLMCache.model == model,
        )
    )
    cached = result.scalar_one_or_none()

    if cached is None:
        return None

    # Incrementar contador de hits
    await session.execute(
        update(LLMCache)
        .where(LLMCache.id == cached.id)
        .values(hits=LLMCache.hits + 1)
    )

    logger.debug("cache_hit", hash=prompt_hash[:12], model=model, hits=cached.hits + 1)
    return {"response": cached.response, "token_usage": cached.token_usage}


async def save_to_cache(
    session: AsyncSession,
    messages: list[dict],
    model: str,
    response: dict,
    token_usage: dict,
) -> None:
    """
    Guarda una respuesta en cache.
    Si ya existe la clave (race condition), ignora el conflicto.
    """
    prompt_hash = _compute_hash(messages, model)

    stmt = (
        insert(LLMCache)
        .values(
            prompt_hash=prompt_hash,
            model=model,
            response=response,
            token_usage=token_usage,
            hits=0,
        )
        .on_conflict_do_nothing(constraint="uq_cache_hash_model")
    )
    await session.execute(stmt)
    logger.debug("cache_saved", hash=prompt_hash[:12], model=model)


async def cleanup_expired_cache(session: AsyncSession) -> int:
    """
    Elimina entradas vencidas del cache LLM.

    Reglas:
    - Entradas sin hits en los últimos 7 días → eliminar
    - Cualquier entrada con más de 30 días → eliminar
    - Si quedan más de 500 filas → eliminar las más antiguas hasta 500

    Returns:
        Número de filas eliminadas.
    """
    now = datetime.utcnow()
    deleted = 0

    # 1. Sin hits y más de 7 días (entradas "frías")
    cold_cutoff = now - timedelta(days=7)
    result = await session.execute(
        delete(LLMCache)
        .where(LLMCache.hits == 0, LLMCache.created_at < cold_cutoff)
        .returning(LLMCache.id)
    )
    deleted += len(result.all())

    # 2. Más de 30 días independientemente de los hits
    old_cutoff = now - timedelta(days=30)
    result = await session.execute(
        delete(LLMCache)
        .where(LLMCache.created_at < old_cutoff)
        .returning(LLMCache.id)
    )
    deleted += len(result.all())

    # 3. Límite de 500 filas: eliminar las más antiguas si se supera
    count_result = await session.execute(select(func.count()).select_from(LLMCache))
    total = count_result.scalar_one()
    max_rows = 500
    if total > max_rows:
        excess = total - max_rows
        subq = (
            select(LLMCache.id)
            .order_by(LLMCache.created_at.asc())
            .limit(excess)
            .scalar_subquery()
        )
        result = await session.execute(
            delete(LLMCache).where(LLMCache.id.in_(subq)).returning(LLMCache.id)
        )
        deleted += len(result.all())

    if deleted:
        logger.info("cache_cleanup", deleted=deleted, remaining=total - deleted)
    return deleted
