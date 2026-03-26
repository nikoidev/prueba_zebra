"""
Cache de respuestas LLM en PostgreSQL.

Usa SHA-256 del contenido de los mensajes + modelo como key.
Incrementa un contador de hits por cada cache hit para monitoreo.
"""

from __future__ import annotations

import hashlib
import json

import structlog
from sqlalchemy import select, update
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
            messages=messages,
            response=response,
            token_usage=token_usage,
            hits=0,
        )
        .on_conflict_do_nothing(constraint="uq_cache_hash_model")
    )
    await session.execute(stmt)
    logger.debug("cache_saved", hash=prompt_hash[:12], model=model)
