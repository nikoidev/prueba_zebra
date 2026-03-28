"""
Orchestrator: Maquina de estados que coordina el pipeline multi-agente.

Estados:
  RECEIVED    -> Solicitud recibida, contexto inicializado
  DECOMPOSING -> DecomposerAgent descompone en subtareas
  ANALYZING   -> DomainExpertAgent analiza subtareas en paralelo
  ARCHITECTING -> ArchitectAgent sintetiza la solucion
  REVIEWING   -> ReviewerAgent evalua la solucion
  REVISING    -> (loop) Si confianza < threshold, vuelve a ARCHITECTING
  FINALIZING  -> RiskAnalystAgent + ensamblado del output final
  DONE        -> Ejecucion completada correctamente
  FAILED      -> Error irrecuperable en agente critico

Transicion dinamica post-REVIEWING:
  Si review.confidence < threshold AND revision_count < max_revisions:
    -> REVISING (que transiciona a ARCHITECTING)
  Si no:
    -> FINALIZING

El orchestrator es el unico punto de entrada y salida del sistema.
"""

from __future__ import annotations

import time
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

import structlog

from src.agents.architect import ArchitectAgent
from src.agents.decomposer import DecomposerAgent
from src.agents.domain_expert import DomainExpertAgent
from src.agents.reviewer import ReviewerAgent
from src.agents.risk_analyst import RiskAnalystAgent
from src.config import get_settings
from src.models import (
    FinalOutput,
    OutputMetadata,
    SharedContext,
)
from src.observability import compute_metrics

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class State(str, Enum):
    RECEIVED = "RECEIVED"
    DECOMPOSING = "DECOMPOSING"
    ANALYZING = "ANALYZING"
    ARCHITECTING = "ARCHITECTING"
    REVIEWING = "REVIEWING"
    REVISING = "REVISING"
    FINALIZING = "FINALIZING"
    DONE = "DONE"
    FAILED = "FAILED"


def _get_state_agents() -> dict[State, type]:
    """
    Devuelve el mapa estado->agente. Se construye en tiempo de ejecucion
    para que los patches en tests funcionen correctamente.
    """
    return {
        State.DECOMPOSING: DecomposerAgent,
        State.ANALYZING: DomainExpertAgent,
        State.ARCHITECTING: ArchitectAgent,
        State.REVIEWING: ReviewerAgent,
        State.REVISING: ArchitectAgent,   # REVISING usa el Architect con sugerencias del Reviewer
        State.FINALIZING: RiskAnalystAgent,
    }

# Transiciones lineales (las dinamicas se gestionan en _next_state)
_LINEAR_TRANSITIONS: dict[State, State] = {
    State.RECEIVED: State.DECOMPOSING,
    State.DECOMPOSING: State.ANALYZING,
    State.ANALYZING: State.ARCHITECTING,
    State.ARCHITECTING: State.REVIEWING,
    State.REVISING: State.REVIEWING,
    State.FINALIZING: State.DONE,
}


def _next_state(context: SharedContext) -> State:
    """
    Calcula el siguiente estado del pipeline.
    El unico punto de logica dinamica es post-REVIEWING.
    """
    current = State(context.current_state)
    settings = get_settings()

    if current == State.REVIEWING:
        review = context.review
        if review is None:
            return State.FAILED

        needs_revision = (
            not review.approved
            and review.confidence < settings.review_confidence_threshold
        )
        can_revise = context.revision_count < settings.max_revisions

        if needs_revision and can_revise:
            logger.info(
                "review_requesting_revision",
                confidence=review.confidence,
                threshold=settings.review_confidence_threshold,
                revision=context.revision_count + 1,
                max=settings.max_revisions,
            )
            return State.REVISING
        else:
            if needs_revision:
                logger.warning(
                    "review_max_revisions_reached",
                    confidence=review.confidence,
                    revisions=context.revision_count,
                )
            return State.FINALIZING

    return _LINEAR_TRANSITIONS.get(current, State.FAILED)


def _assemble_final_output(context: SharedContext, started_at: datetime) -> FinalOutput:
    """Ensambla el output final a partir del contexto completo."""
    metrics = compute_metrics(context.traces)
    now = datetime.utcnow()

    # Confianza global: ponderacion de architect (60%) + reviewer (40%)
    arch_conf = context.architecture.confidence if context.architecture else 0.0
    rev_conf = context.review.confidence if context.review else 0.0
    overall = round(arch_conf * 0.6 + rev_conf * 0.4, 2)

    metadata = OutputMetadata(
        request_id=context.request_id,
        started_at=started_at,
        finished_at=now,
        total_duration_ms=metrics["total_duration_ms"],
        total_tokens=metrics["total_tokens"],
        cached_calls=metrics.get("cached_calls", 0),
        agents_invoked=metrics["agents_invoked"],
        states_traversed=[t.state for t in context.traces],
        revisions_performed=context.revision_count,
        errors_encountered=len(context.errors),
    )

    return FinalOutput(
        request_id=context.request_id,
        original_request=context.original_request,
        solution=context.architecture,
        domain_analyses=context.domain_analyses,
        review=context.review,
        risk_assessment=context.risk_assessment,
        agent_traces=context.traces,
        errors=context.errors,
        metadata=metadata,
        overall_confidence=overall,
    )


async def run(
    request: str,
    db_session: "AsyncSession | None" = None,
    verbose: bool = False,
) -> FinalOutput:
    """
    Punto de entrada del sistema multi-agente.

    Args:
        request: Solicitud del usuario en lenguaje natural
        db_session: Sesion de DB para persistencia (opcional)
        verbose: Si True, loguea trazas en tiempo real

    Returns:
        FinalOutput con el resultado estructurado y metadatos de ejecucion

    Raises:
        Exception: Si un agente critico falla de forma irrecuperable
    """
    started_at = datetime.utcnow()
    context = SharedContext(original_request=request)

    logger.info(
        "pipeline_started",
        request_id=context.request_id,
        request_preview=request[:100],
    )

    # Guardar ejecucion inicial en DB
    if db_session is not None:
        try:
            from src.db.repository import save_execution
            await save_execution(db_session, context, started_at)
            await db_session.commit()
        except Exception as e:
            logger.warning("db_save_initial_failed", error=str(e))

    # --- Loop principal de la maquina de estados ---
    state_agents = _get_state_agents()
    errors_saved = 0  # Puntero para evitar guardar errores duplicados

    while State(context.current_state) not in (State.DONE, State.FAILED):
        current_state = State(context.current_state)
        agent_class = state_agents.get(current_state)

        if agent_class is None:
            # Estado sin agente (RECEIVED): solo avanzamos
            context.current_state = _next_state(context).value
            continue

        agent = agent_class()

        if verbose:
            logger.info("state_transition", state=current_state.value, agent=agent.name)

        # Incrementar contador de revisiones cuando entramos en REVISING
        if current_state == State.REVISING:
            context.revision_count += 1

        try:
            context = await agent.execute(context, db_session=db_session)
        except Exception as e:
            logger.error(
                "critical_agent_failed",
                agent=agent.name,
                state=current_state.value,
                error=str(e),
            )
            context.current_state = State.FAILED.value
            break

        # Persistir trazas en DB
        if db_session is not None and context.traces:
            try:
                from src.db.repository import save_agent_trace, save_error
                last_trace = context.traces[-1]
                await save_agent_trace(db_session, context.request_id, last_trace)
                new_errors = context.errors[errors_saved:]
                for error in new_errors:
                    await save_error(db_session, context.request_id, error)
                errors_saved = len(context.errors)
                await db_session.commit()
            except Exception as e:
                logger.warning("db_save_trace_failed", error=str(e))

        context.current_state = _next_state(context).value

    # --- Ensamblar output final ---
    if State(context.current_state) == State.DONE:
        context.final_output = _assemble_final_output(context, started_at)
        logger.info(
            "pipeline_completed",
            request_id=context.request_id,
            overall_confidence=context.final_output.overall_confidence,
            total_tokens=context.final_output.metadata.total_tokens,
            revisions=context.revision_count,
            duration_ms=context.final_output.metadata.total_duration_ms,
        )
    else:
        # Pipeline fallido: generar output parcial
        logger.error(
            "pipeline_failed",
            request_id=context.request_id,
            errors=[e.message for e in context.errors],
        )
        # Intentar construir output parcial si hay suficiente informacion
        if context.architecture is not None and context.review is not None:
            context.final_output = _assemble_final_output(context, started_at)
        else:
            raise RuntimeError(
                f"Pipeline fallido en estado {context.current_state}. "
                f"Errores: {[e.message for e in context.errors]}"
            )

    # Persistir ejecucion final en DB
    if db_session is not None:
        try:
            from src.db.repository import save_execution
            await save_execution(db_session, context, started_at)
            await db_session.commit()
        except Exception as e:
            logger.warning("db_save_final_failed", error=str(e))

    return context.final_output
