"""
DecomposerAgent: Descompone el request del usuario en subtareas estructuradas.

Responsabilidad:
  Analizar el request y producir una lista de subtareas con dominio y prioridad.

Input:
  context.original_request (str)

Output:
  context.subtasks (list[SubTask])

Condiciones de error:
  - LLM no responde: reintento via llm.py
  - LLM devuelve 0 subtareas: fallback a una subtarea unica con el request completo
  - JSON invalido: LLMParseError propagada al orchestrator (agente critico)
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

from src.agents.base import BaseAgent
from src.llm import call_llm
from src.models import SharedContext, SubTask, TokenUsage


class _DecomposerOutput(BaseModel):
    """Schema interno esperado del LLM."""

    subtasks: list[_SubTaskRaw]
    reasoning: str

class _SubTaskRaw(BaseModel):
    description: str
    domain: str
    priority: int = Field(ge=1, le=5)


_SYSTEM_PROMPT = """Eres un especialista en descomposicion de problemas complejos.

Tu tarea es analizar la solicitud del usuario y dividirla en subtareas independientes y accionables.

Para cada subtarea debes identificar:
- description: descripcion clara y concisa de la subtarea
- domain: categoria del dominio ("product", "technical", "legal", "market", "planning", "financial", "ux", "security", "data", "other")
- priority: 1 (mas alta) a 5 (mas baja)

Reglas:
- Genera entre 3 y 7 subtareas (no mas, no menos)
- Cada subtarea debe ser atomica y tener un unico responsable logico
- Las subtareas deben cubrir todos los aspectos del request original
- Evita duplicados y solapamientos

Responde SIEMPRE con JSON valido siguiendo exactamente el schema indicado."""


class DecomposerAgent(BaseAgent):
    name = "decomposer"
    description = (
        "Descompone el request del usuario en subtareas estructuradas con dominio y prioridad. "
        "NO analiza el contenido de las subtareas, solo las define."
    )

    async def execute(self, context: SharedContext, **kwargs) -> SharedContext:
        start = time.monotonic()
        db_session = kwargs.get("db_session")

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Solicitud del usuario:\n\n{context.original_request}\n\n"
                    "Descompone esta solicitud en subtareas estructuradas."
                ),
            },
        ]

        try:
            result, usage = await call_llm(
                messages=messages,
                response_model=_DecomposerOutput,
                db_session=db_session,
            )
        except Exception as e:
            self._record_error(context, e)
            # Agente critico: propagamos el error al orchestrator
            raise

        # Validar que haya subtareas (fallback si el LLM devuelve lista vacia)
        if not result.subtasks:
            result.subtasks = [
                _SubTaskRaw(
                    description=context.original_request,
                    domain="other",
                    priority=1,
                )
            ]

        context.subtasks = [
            SubTask(
                description=st.description,
                domain=st.domain,
                priority=st.priority,
            )
            for st in result.subtasks
        ]

        self._record_trace(
            context,
            start,
            input_summary=context.original_request[:200],
            output_summary=f"{len(context.subtasks)} subtareas: {', '.join(s.domain for s in context.subtasks)}",
            token_usage=usage,
            model_used=kwargs.get("model", ""),
        )

        return context
