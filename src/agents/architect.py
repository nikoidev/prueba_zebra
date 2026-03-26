"""
ArchitectAgent: Sintetiza todos los analisis de dominio en una solucion coherente.

Responsabilidad:
  Tomar los analisis del DomainExpert y producir una arquitectura/solucion
  integrada con componentes, decisiones tecnicas y notas de integracion.
  En revisiones, incorpora las sugerencias del Reviewer.

Input:
  context.domain_analyses (dict[str, DomainAnalysis])
  context.subtasks (list[SubTask])
  context.review (ReviewResult | None) - solo en revisiones
  context.original_request (str)

Output:
  context.architecture (Architecture)

Condiciones de error:
  - LLM falla tras reintentos: devuelve arquitectura degradada (confidence baja)
  - Agente critico: el orchestrator puede decidir transicionar a FAILED
"""

from __future__ import annotations

import time

from pydantic import BaseModel, Field

from src.agents.base import BaseAgent
from src.llm import LLMError, call_llm
from src.models import Architecture, Component, SharedContext, TokenUsage


class _ComponentRaw(BaseModel):
    name: str
    description: str
    technology: str
    responsibilities: list[str]


class _ArchitectOutput(BaseModel):
    summary: str
    components: list[_ComponentRaw]
    integration_notes: str
    tech_decisions: list[str] = Field(default_factory=list)
    revision_notes: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


_SYSTEM_PROMPT = """Eres un arquitecto de soluciones senior con amplia experiencia en proyectos complejos.

Tu tarea es sintetizar los analisis de dominio proporcionados en una solucion cohesionada y bien estructurada.

Debes producir:
- summary: vision general de la solucion (2-3 parrafos)
- components: lista de componentes/modulos principales con su tecnologia y responsabilidades
- integration_notes: como se integran los componentes entre si
- tech_decisions: lista de decisiones tecnicas importantes con sus trade-offs (formato: "Decision: [decision]. Trade-off: [pros y contras]")
- revision_notes: si recibes sugerencias de revision, explica como las has incorporado
- confidence: tu nivel de confianza en la solucion (0.0-1.0)

Principios:
- Prioriza la cohesion y coherencia sobre la exhaustividad
- Cada componente debe tener una responsabilidad clara
- Justifica las decisiones tecnicas con trade-offs explicitos
- Si hay conflictos entre analisis de dominio, resuelvelos explicitamente"""


def _build_user_prompt(context: SharedContext) -> str:
    """Construye el prompt del usuario con todos los analisis."""
    lines = [
        f"Solicitud original:\n{context.original_request}\n",
        "Analisis por dominio:\n",
    ]

    for subtask in context.subtasks:
        analysis = context.domain_analyses.get(subtask.id)
        if analysis is None:
            continue
        status = " [DEGRADADO]" if analysis.degraded else ""
        lines.append(f"### Subtarea: {subtask.description} (Dominio: {subtask.domain}){status}")
        lines.append(f"**Hallazgos:** {analysis.findings}")
        if analysis.recommendations:
            lines.append("**Recomendaciones:**")
            for rec in analysis.recommendations[:5]:  # limitar para no exceder contexto
                lines.append(f"  - {rec}")
        lines.append(f"**Confianza:** {analysis.confidence:.0%}\n")

    # Incorporar sugerencias del Reviewer si es una revision
    if context.review and not context.review.approved:
        lines.append(f"\n## REVISION #{context.revision_count} - Sugerencias del Reviewer:")
        lines.append(f"**Debilidades identificadas:**")
        for w in context.review.weaknesses:
            lines.append(f"  - {w}")
        lines.append(f"**Sugerencias de mejora:**")
        for s in context.review.suggestions:
            lines.append(f"  - {s}")
        lines.append(
            "\nIntegra estas sugerencias en tu propuesta de arquitectura. "
            "Explica en revision_notes como las has incorporado."
        )

    return "\n".join(lines)


class ArchitectAgent(BaseAgent):
    name = "architect"
    description = (
        "Sintetiza los analisis de dominio en una arquitectura/solucion coherente. "
        "NO analiza dominios individuales ni evalua la calidad de la solucion."
    )

    async def execute(self, context: SharedContext, **kwargs) -> SharedContext:
        start = time.monotonic()
        db_session = kwargs.get("db_session")

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(context)},
        ]

        try:
            result, usage = await call_llm(
                messages=messages,
                response_model=_ArchitectOutput,
                db_session=db_session,
                # Las revisiones no deben usar cache (el prompt cambia con sugerencias)
                use_cache=context.revision_count == 0,
            )
        except LLMError as e:
            self._record_error(context, e)
            # Arquitectura degradada para no bloquear el pipeline
            context.architecture = Architecture(
                summary=f"Arquitectura parcial (error en generacion): {str(e)[:200]}",
                components=[],
                integration_notes="No disponible",
                confidence=0.1,
            )
            self._record_trace(
                context, start,
                input_summary=f"{len(context.domain_analyses)} analisis",
                output_summary="ERROR - arquitectura degradada",
                token_usage=TokenUsage(),
            )
            return context

        context.architecture = Architecture(
            summary=result.summary,
            components=[
                Component(
                    name=c.name,
                    description=c.description,
                    technology=c.technology,
                    responsibilities=c.responsibilities,
                )
                for c in result.components
            ],
            integration_notes=result.integration_notes,
            tech_decisions=result.tech_decisions,
            revision_notes=result.revision_notes,
            confidence=result.confidence,
        )

        self._record_trace(
            context,
            start,
            input_summary=f"{len(context.domain_analyses)} analisis de dominio",
            output_summary=(
                f"{len(context.architecture.components)} componentes, "
                f"confianza={context.architecture.confidence:.0%}"
            ),
            token_usage=usage,
            model_used=kwargs.get("model", ""),
        )

        return context
