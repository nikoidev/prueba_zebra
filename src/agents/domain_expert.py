"""
DomainExpertAgent: Analiza cada subtarea desde la perspectiva de su dominio.

Responsabilidad:
  Procesar TODAS las subtareas en paralelo (asyncio.gather) y generar un analisis
  de dominio para cada una. Esta es la principal coordinacion real del sistema:
  fan-out paralelo, no secuencial.

Input:
  context.subtasks (list[SubTask])
  context.original_request (str)

Output:
  context.domain_analyses (dict[subtask_id -> DomainAnalysis])

Condiciones de error:
  - Si una subtarea falla: se registra el error y se genera un analisis degradado
    (confidence=0.0, degraded=True). El pipeline continua con las demas subtareas.
  - Si TODAS las subtareas fallan: el orchestrator detecta analyses vacios y puede
    transicionar a FAILED.
"""

from __future__ import annotations

import asyncio
import time

from pydantic import BaseModel, Field

from src.agents.base import BaseAgent
from src.llm import LLMError, call_llm
from src.models import DomainAnalysis, SharedContext, SubTask, TokenUsage


class _DomainOutput(BaseModel):
    findings: str
    recommendations: list[str]
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


_SYSTEM_PROMPTS = {
    "technical": (
        "Eres un experto tecnico senior. Analiza el problema desde la perspectiva de "
        "arquitectura de software, tecnologias, viabilidad tecnica y mejores practicas."
    ),
    "legal": (
        "Eres un especialista en derecho tecnologico y regulacion. Analiza implicaciones "
        "legales, normativas aplicables (GDPR, LOPD, etc.) y requisitos de cumplimiento."
    ),
    "market": (
        "Eres un analista de mercado y negocio. Analiza el contexto de mercado, competencia, "
        "usuarios objetivo, propuesta de valor y viabilidad comercial."
    ),
    "product": (
        "Eres un product manager senior. Analiza requisitos del producto, funcionalidades "
        "clave, MVP, experiencia de usuario y roadmap de producto."
    ),
    "planning": (
        "Eres un experto en gestion de proyectos. Analiza el plan de ejecucion, recursos "
        "necesarios, dependencias, riesgos de proyecto y cronograma."
    ),
    "financial": (
        "Eres un analista financiero. Analiza costes, modelo de ingresos, proyecciones "
        "financieras y metricas de negocio relevantes."
    ),
    "ux": (
        "Eres un especialista en UX/UI. Analiza la experiencia de usuario, flujos de "
        "navegacion, accesibilidad y mejores practicas de diseno."
    ),
    "security": (
        "Eres un especialista en ciberseguridad. Analiza vectores de ataque, requisitos "
        "de seguridad, autenticacion, autorizacion y proteccion de datos."
    ),
    "data": (
        "Eres un ingeniero de datos. Analiza modelos de datos, almacenamiento, pipelines "
        "de datos, integraciones y estrategia de datos."
    ),
    "other": (
        "Eres un experto generalista. Analiza el problema en profundidad desde todos los "
        "angulos relevantes e identifica los aspectos mas criticos."
    ),
}

_USER_PROMPT_TEMPLATE = """Contexto global del proyecto:
{original_request}

Subtarea a analizar:
{description}

Genera un analisis profundo y accionable de esta subtarea. Se especifico con recomendaciones concretas.
Indica los supuestos que estas asumiendo en tu analisis."""


class DomainExpertAgent(BaseAgent):
    name = "domain_expert"
    description = (
        "Analiza cada subtarea en paralelo desde la perspectiva de su dominio. "
        "NO sintetiza resultados ni propone arquitectura global."
    )

    async def execute(self, context: SharedContext, **kwargs) -> SharedContext:
        start = time.monotonic()
        db_session = kwargs.get("db_session")

        if not context.subtasks:
            return context

        # Fan-out paralelo: todas las subtareas se procesan simultaneamente
        tasks = [
            self._analyze_subtask(subtask, context.original_request, db_session)
            for subtask in context.subtasks
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        total_usage = TokenUsage()
        successful = 0

        for subtask, result in zip(context.subtasks, results):
            if isinstance(result, Exception):
                self._record_error(context, result)
                # Analisis degradado para no bloquear el pipeline
                context.domain_analyses[subtask.id] = DomainAnalysis(
                    subtask_id=subtask.id,
                    findings=f"Analisis no disponible debido a un error: {str(result)[:200]}",
                    recommendations=[],
                    assumptions=[],
                    confidence=0.0,
                    degraded=True,
                )
            else:
                analysis, usage = result
                context.domain_analyses[subtask.id] = analysis
                total_usage.prompt_tokens += usage.prompt_tokens
                total_usage.completion_tokens += usage.completion_tokens
                total_usage.total_tokens += usage.total_tokens
                successful += 1

        self._record_trace(
            context,
            start,
            input_summary=f"{len(context.subtasks)} subtareas en paralelo",
            output_summary=(
                f"{successful}/{len(context.subtasks)} analisis exitosos. "
                f"Dominios: {', '.join(s.domain for s in context.subtasks)}"
            ),
            token_usage=total_usage,
            model_used=kwargs.get("model", ""),
        )

        return context

    async def _analyze_subtask(
        self,
        subtask: SubTask,
        original_request: str,
        db_session,
    ) -> tuple[DomainAnalysis, TokenUsage]:
        """Analiza una subtarea individual."""
        system_prompt = _SYSTEM_PROMPTS.get(subtask.domain, _SYSTEM_PROMPTS["other"])

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": _USER_PROMPT_TEMPLATE.format(
                    original_request=original_request,
                    description=subtask.description,
                ),
            },
        ]

        output, usage = await call_llm(
            messages=messages,
            response_model=_DomainOutput,
            db_session=db_session,
        )

        analysis = DomainAnalysis(
            subtask_id=subtask.id,
            findings=output.findings,
            recommendations=output.recommendations,
            assumptions=output.assumptions,
            confidence=output.confidence,
        )
        return analysis, usage
