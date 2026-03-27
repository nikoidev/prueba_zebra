"""
Clase base para todos los agentes del sistema.

Cada agente tiene:
- name: identificador unico
- description: que hace y que NO hace
- execute(): metodo principal que recibe y devuelve SharedContext
- _record_trace(): registra la ejecucion en context.traces
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime

import structlog

from src.config import get_settings
from src.models import AgentTrace, ErrorRecord, SharedContext, TokenUsage

logger = structlog.get_logger(__name__)


class BaseAgent(ABC):
    """
    Clase abstracta de la que heredan todos los agentes.

    Contrato:
    - Recibe SharedContext con el estado actual del pipeline
    - Modifica exclusivamente su seccion del contexto
    - Devuelve el SharedContext actualizado
    - Registra su ejecucion en context.traces
    - En caso de error no critico: loguea, registra en context.errors y devuelve
      el contexto sin modificar su seccion (degradacion graceful)
    """

    name: str
    description: str

    @abstractmethod
    async def execute(self, context: SharedContext, **kwargs) -> SharedContext:
        """
        Ejecuta la logica del agente.

        Args:
            context: Estado compartido del pipeline
            **kwargs: Argumentos adicionales (e.g., db_session)

        Returns:
            SharedContext actualizado
        """
        ...

    def _record_trace(
        self,
        context: SharedContext,
        start_time: float,
        input_summary: str,
        output_summary: str,
        token_usage: TokenUsage,
        model_used: str = "",
    ) -> None:
        """
        Registra la ejecucion del agente en context.traces.
        Llamar al final de execute(), tanto en caso de exito como de error.
        """
        duration_ms = (time.monotonic() - start_time) * 1000
        effective_model = model_used or get_settings().active_model
        trace = AgentTrace(
            agent_name=self.name,
            state=context.current_state,
            input_summary=input_summary[:500],  # truncar para no inflar la DB
            output_summary=output_summary[:500],
            duration_ms=round(duration_ms, 1),
            model_used=effective_model,
            token_usage=token_usage,
            timestamp=datetime.utcnow(),
        )
        context.traces.append(trace)
        logger.info(
            "agent_trace",
            agent=self.name,
            state=context.current_state,
            duration_ms=round(duration_ms, 1),
            tokens=token_usage.total_tokens,
            cached=token_usage.cached,
        )

    def _record_error(
        self,
        context: SharedContext,
        error: Exception,
    ) -> None:
        """Registra un error en context.errors."""
        err = ErrorRecord(
            agent_name=self.name,
            error_type=type(error).__name__,
            message=str(error)[:1000],
        )
        context.errors.append(err)
        logger.error(
            "agent_error",
            agent=self.name,
            state=context.current_state,
            error_type=type(error).__name__,
            message=str(error)[:200],
        )
