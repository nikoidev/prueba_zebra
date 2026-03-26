"""
ReviewerAgent: Revisa criticamente la arquitectura propuesta.

Responsabilidad:
  Evaluar la solucion del Architect contra el request original y los analisis
  de dominio. Detectar contradicciones, lagunas o incoherencias. Asignar
  un score de confianza y decidir si aprobar o solicitar revision.

Input:
  context.architecture (Architecture)
  context.domain_analyses (dict[str, DomainAnalysis])
  context.original_request (str)
  context.revision_count (int)

Output:
  context.review (ReviewResult)
  [La decision de revision/aprobacion la toma el orchestrator basandose en review.approved]

Condiciones de error:
  - LLM falla: se registra error, se genera revision con approved=False y confidence baja
  - El orchestrator limita el numero de revisiones (max_revisions)
"""

from __future__ import annotations

import time

from pydantic import BaseModel, Field

from src.agents.base import BaseAgent
from src.llm import LLMError, call_llm
from src.models import ReviewResult, SharedContext, TokenUsage


class _ReviewOutput(BaseModel):
    approved: bool
    confidence: float = Field(ge=0.0, le=1.0)
    strengths: list[str]
    weaknesses: list[str]
    suggestions: list[str]
    reasoning: str


_SYSTEM_PROMPT = """Eres un revisor critico senior con experiencia en evaluacion de soluciones tecnicas y de negocio.

Tu tarea es evaluar la solucion propuesta de forma rigurosa e imparcial.

Criterios de evaluacion:
1. COMPLETITUD: La solucion cubre todos los aspectos del request original?
2. COHERENCIA: Los componentes son consistentes entre si? Hay contradicciones?
3. VIABILIDAD: La solucion es realista y ejecutable?
4. CALIDAD: Las decisiones tecnicas estan justificadas? Los trade-offs son razonables?
5. RIESGOS: Se han identificado los principales riesgos?

Instrucciones:
- approved: true si la solucion es aceptable (confidence >= umbral del sistema)
- confidence: tu nivel de confianza en que la solucion es correcta (0.0-1.0)
- strengths: aspectos positivos de la solucion (minimo 2)
- weaknesses: problemas, lagunas o incoherencias detectadas
- suggestions: mejoras concretas y accionables (vacio si approved=true)
- reasoning: explicacion de tu evaluacion (2-3 parrafos)

SE CRITICO. Una solucion mediocre con confidence=0.9 es un fallo del revisor.
Una solucion buena con confidence=0.8 es aprobar correctamente."""


def _build_user_prompt(context: SharedContext) -> str:
    arch = context.architecture
    lines = [
        f"Request original:\n{context.original_request}\n",
        f"## Solucion propuesta (revision #{context.revision_count + 1})\n",
        f"**Resumen:** {arch.summary}\n",
        f"**Componentes ({len(arch.components)}):**",
    ]
    for c in arch.components:
        lines.append(f"  - {c.name} ({c.technology}): {c.description}")

    lines.append(f"\n**Integracion:** {arch.integration_notes}")

    if arch.tech_decisions:
        lines.append("\n**Decisiones tecnicas:**")
        for td in arch.tech_decisions:
            lines.append(f"  - {td}")

    if arch.revision_notes:
        lines.append(f"\n**Notas de revision:** {arch.revision_notes}")

    lines.append(f"\n**Confianza del Architect:** {arch.confidence:.0%}")
    lines.append(f"\n## Analisis de dominio disponibles\n")

    for subtask in context.subtasks:
        analysis = context.domain_analyses.get(subtask.id)
        if analysis and not analysis.degraded:
            lines.append(
                f"- **{subtask.domain}**: {analysis.findings[:300]}... "
                f"(confianza: {analysis.confidence:.0%})"
            )
        elif analysis and analysis.degraded:
            lines.append(f"- **{subtask.domain}**: [ANALISIS DEGRADADO - no disponible]")

    return "\n".join(lines)


class ReviewerAgent(BaseAgent):
    name = "reviewer"
    description = (
        "Revisa criticamente la arquitectura propuesta y asigna un score de confianza. "
        "NO propone nuevas soluciones, solo evalua y sugiere mejoras especificas."
    )

    async def execute(self, context: SharedContext, **kwargs) -> SharedContext:
        start = time.monotonic()
        db_session = kwargs.get("db_session")

        if context.architecture is None:
            return context

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(context)},
        ]

        revision_number = context.revision_count + 1

        try:
            result, usage = await call_llm(
                messages=messages,
                response_model=_ReviewOutput,
                db_session=db_session,
                use_cache=False,  # Las revisiones nunca se cachean
            )
        except LLMError as e:
            self._record_error(context, e)
            # Revision degradada: no aprobamos para no arriesgar mala calidad
            context.review = ReviewResult(
                revision_number=revision_number,
                approved=False,
                confidence=0.0,
                strengths=[],
                weaknesses=[f"Error en la revision: {str(e)[:200]}"],
                suggestions=["Reintentar la revision"],
                reasoning="La revision fallo debido a un error del LLM.",
            )
            self._record_trace(
                context, start,
                input_summary="revision fallida",
                output_summary="ERROR - revision degradada",
                token_usage=TokenUsage(),
            )
            return context

        context.review = ReviewResult(
            revision_number=revision_number,
            approved=result.approved,
            confidence=result.confidence,
            strengths=result.strengths,
            weaknesses=result.weaknesses,
            suggestions=result.suggestions,
            reasoning=result.reasoning,
        )

        # Persistir revision en DB si hay sesion
        if db_session is not None:
            try:
                from src.db.repository import save_review
                await save_review(db_session, context.request_id, context.review)
            except Exception:
                pass  # No critico

        self._record_trace(
            context,
            start,
            input_summary=f"arquitectura con {len(context.architecture.components)} componentes",
            output_summary=(
                f"{'APROBADO' if result.approved else 'RECHAZADO'}, "
                f"confianza={result.confidence:.0%}, "
                f"{len(result.weaknesses)} debilidades"
            ),
            token_usage=usage,
            model_used=kwargs.get("model", ""),
        )

        return context
