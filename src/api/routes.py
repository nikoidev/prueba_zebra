"""
Endpoints REST de la API web.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.schemas import (
    ExecutionDetail,
    ExecutionSummary,
    ModelsResponse,
    ProviderInfo,
)
from src.config import get_settings
from src.db.connection import get_session_factory
from src.db.models import AgentTrace, Execution, ExecutionError, ReviewHistory
from src.db.repository import get_execution_history

router = APIRouter(prefix="/api")


async def get_db():
    """Dependency: sesion de DB por request."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


@router.get("/providers", response_model=ProviderInfo)
async def get_providers():
    """Devuelve los providers disponibles segun las API keys configuradas."""
    settings = get_settings()
    providers = settings.available_providers
    if not providers:
        raise HTTPException(status_code=503, detail="No API keys configured")
    return ProviderInfo(
        providers=providers,
        default_provider=providers[0],
        default_model=settings.active_model,
    )


@router.get("/models/{provider}", response_model=ModelsResponse)
async def get_models(provider: str):
    """Devuelve los modelos disponibles para un provider consultando su API."""
    _STATIC_MODELS = {
        "anthropic": [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
        ],
    }
    if provider == "gemini":
        try:
            from src.llm import list_gemini_models
            models = await list_gemini_models()
            if models:
                return ModelsResponse(provider=provider, models=models)
        except Exception:
            pass
    elif provider == "openai":
        try:
            from src.llm import list_openai_models
            models = await list_openai_models()
            if models:
                return ModelsResponse(provider=provider, models=models)
        except Exception:
            pass

    fallback = _STATIC_MODELS.get(provider, ["gpt-4o", "gpt-4o-mini"])
    return ModelsResponse(provider=provider, models=fallback)


@router.get("/executions", response_model=list[ExecutionSummary])
async def list_executions(limit: int = 20, db: AsyncSession = Depends(get_db)):
    """Devuelve el historial de ejecuciones recientes."""
    executions = await get_execution_history(db, limit=limit)
    return [
        ExecutionSummary(
            id=ex.id,
            original_request=ex.original_request,
            final_state=ex.final_state,
            overall_confidence=ex.overall_confidence,
            total_tokens=ex.total_tokens,
            duration_ms=ex.duration_ms,
            revision_count=ex.revision_count,
            created_at=ex.created_at,
        )
        for ex in executions
    ]


@router.get("/executions/{execution_id}", response_model=ExecutionDetail)
async def get_execution(execution_id: str, db: AsyncSession = Depends(get_db)):
    """Devuelve el detalle completo de una ejecucion incluyendo traces y reviews."""
    result = await db.execute(
        select(Execution)
        .where(Execution.id == execution_id)
        .options(
            selectinload(Execution.traces),
            selectinload(Execution.reviews),
            selectinload(Execution.errors),
        )
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    return ExecutionDetail(
        id=execution.id,
        original_request=execution.original_request,
        final_state=execution.final_state,
        overall_confidence=execution.overall_confidence,
        total_tokens=execution.total_tokens,
        duration_ms=execution.duration_ms,
        revision_count=execution.revision_count,
        created_at=execution.created_at,
        finished_at=execution.finished_at,
        final_output=execution.final_output,
        traces=[
            {
                "agent_name": t.agent_name,
                "state": t.state,
                "duration_ms": t.duration_ms,
                "model_used": t.model_used,
                "tokens_in": t.tokens_in,
                "tokens_out": t.tokens_out,
                "from_cache": t.from_cache,
                "timestamp": t.timestamp.isoformat() if t.timestamp else None,
            }
            for t in execution.traces
        ],
        reviews=[
            {
                "revision_number": r.revision_number,
                "approved": r.approved,
                "confidence": r.confidence,
                "strengths": r.strengths,
                "weaknesses": r.weaknesses,
                "suggestions": r.suggestions,
                "reasoning": r.reasoning,
            }
            for r in execution.reviews
        ],
        errors=[
            {
                "agent_name": e.agent_name,
                "error_type": e.error_type,
                "message": e.message,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            }
            for e in execution.errors
        ],
    )
