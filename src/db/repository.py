"""
Operaciones CRUD sobre la base de datos.

Cada funcion recibe una sesion de DB y realiza la operacion correspondiente.
No gestionan transacciones: el caller es responsable del commit/rollback.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import AgentTrace, Execution, ExecutionError, ReviewHistory
from src.models import FinalOutput, SharedContext

logger = structlog.get_logger(__name__)


async def save_execution(
    session: AsyncSession,
    context: SharedContext,
    started_at: datetime,
) -> Execution:
    """Crea o actualiza el registro de ejecucion en DB."""
    result = await session.execute(
        select(Execution).where(Execution.id == context.request_id)
    )
    execution = result.scalar_one_or_none()

    now = datetime.utcnow()
    duration_ms = (now - started_at).total_seconds() * 1000
    total_tokens = sum(t.token_usage.total_tokens for t in context.traces)
    confidence = (
        context.final_output.overall_confidence if context.final_output else None
    )

    if execution is None:
        execution = Execution(
            id=context.request_id,
            original_request=context.original_request,
            final_state=context.current_state,
            created_at=started_at,
            finished_at=now,
            duration_ms=duration_ms,
            total_tokens=total_tokens,
            revision_count=context.revision_count,
            overall_confidence=confidence,
            final_output=(
                context.final_output.model_dump(mode="json", exclude={"agent_traces", "errors"})
                if context.final_output else None
            ),
        )
        session.add(execution)
    else:
        execution.final_state = context.current_state
        execution.finished_at = now
        execution.duration_ms = duration_ms
        execution.total_tokens = total_tokens
        execution.revision_count = context.revision_count
        execution.overall_confidence = confidence
        execution.final_output = (
            context.final_output.model_dump(mode="json", exclude={"agent_traces", "errors"})
            if context.final_output else None
        )

    logger.info(
        "execution_saved",
        request_id=context.request_id,
        state=context.current_state,
        duration_ms=round(duration_ms, 1),
    )
    return execution


async def save_agent_trace(
    session: AsyncSession,
    execution_id: str,
    trace,  # src.models.AgentTrace
) -> AgentTrace:
    """Persiste la traza de un agente."""
    db_trace = AgentTrace(
        execution_id=execution_id,
        agent_name=trace.agent_name,
        state=trace.state,
        input_summary=trace.input_summary,
        output_summary={"summary": trace.output_summary},
        duration_ms=trace.duration_ms,
        model_used=trace.model_used,
        tokens_in=trace.token_usage.prompt_tokens,
        tokens_out=trace.token_usage.completion_tokens,
        from_cache=trace.token_usage.cached,
        timestamp=trace.timestamp,
    )
    session.add(db_trace)
    return db_trace


async def save_review(
    session: AsyncSession,
    execution_id: str,
    review,  # src.models.ReviewResult
) -> ReviewHistory:
    """Persiste el resultado de una revision del Reviewer."""
    db_review = ReviewHistory(
        execution_id=execution_id,
        revision_number=review.revision_number,
        approved=review.approved,
        confidence=review.confidence,
        strengths=review.strengths,
        weaknesses=review.weaknesses,
        suggestions=review.suggestions,
        reasoning=review.reasoning,
    )
    session.add(db_review)
    logger.info(
        "review_saved",
        execution_id=execution_id,
        revision=review.revision_number,
        approved=review.approved,
        confidence=review.confidence,
    )
    return db_review


async def save_error(
    session: AsyncSession,
    execution_id: str,
    error,  # src.models.ErrorRecord
) -> ExecutionError:
    """Persiste un error ocurrido durante la ejecucion."""
    db_error = ExecutionError(
        execution_id=execution_id,
        agent_name=error.agent_name,
        error_type=error.error_type,
        message=error.message,
        timestamp=error.timestamp,
    )
    session.add(db_error)
    return db_error


async def get_execution_history(
    session: AsyncSession,
    limit: int = 10,
) -> list[Execution]:
    """Obtiene las ultimas ejecuciones ordenadas por fecha."""
    result = await session.execute(
        select(Execution).order_by(Execution.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def cleanup_old_executions(session: AsyncSession) -> int:
    """
    Elimina ejecuciones obsoletas para mantener la DB compacta.

    Reglas:
    - RECEIVED con más de 1 hora → ejecuciones huérfanas que nunca terminaron
    - DONE/FAILED con más de 90 días → historial antiguo

    Returns:
        Número de ejecuciones eliminadas (cascada a traces, reviews, errors).
    """
    now = datetime.utcnow()
    deleted = 0

    # Ejecuciones atascadas en RECEIVED (nunca progresaron)
    orphan_cutoff = now - timedelta(hours=1)
    result = await session.execute(
        delete(Execution)
        .where(Execution.final_state == "RECEIVED", Execution.created_at < orphan_cutoff)
        .returning(Execution.id)
    )
    deleted += len(result.all())

    # Ejecuciones completadas con más de 90 días
    old_cutoff = now - timedelta(days=90)
    result = await session.execute(
        delete(Execution)
        .where(
            Execution.final_state.in_(["DONE", "FAILED"]),
            Execution.created_at < old_cutoff,
        )
        .returning(Execution.id)
    )
    deleted += len(result.all())

    if deleted:
        logger.info("executions_cleanup", deleted=deleted)
    return deleted
