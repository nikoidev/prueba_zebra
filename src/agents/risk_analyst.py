"""
RiskAnalystAgent: Identifica riesgos legales, tecnicos y operacionales.

Responsabilidad:
  Analizar la solucion aprobada e identificar riesgos con su severidad y
  estrategias de mitigacion. Agente no critico: su fallo no detiene el pipeline.

Input:
  context.architecture (Architecture)
  context.original_request (str)

Output:
  context.risk_assessment (RiskAssessment)

Condiciones de error:
  - LLM falla: se loguea el error, risk_assessment queda en None
  - El sistema continua y genera el output final sin la evaluacion de riesgos
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

from src.agents.base import BaseAgent
from src.llm import LLMError, call_llm
from src.models import Risk, RiskAssessment, SharedContext, TokenUsage


class _RiskRaw(BaseModel):
    title: str
    description: str
    severity: Literal["low", "medium", "high", "critical"]
    category: Literal["legal", "technical", "operational", "financial", "compliance"]
    mitigation: str


class _RiskOutput(BaseModel):
    risks: list[_RiskRaw]
    overall_risk_level: Literal["low", "medium", "high", "critical"]
    regulatory_notes: str = ""
    recommendations: list[str] = Field(default_factory=list)


_SYSTEM_PROMPT = """Eres responsable de gestion de riesgos en Disashop, especializado en lanzamientos de servicios sobre redes amplias de puntos de venta (recargas telco, paqueteria de ultima milla, energia, transporte publico, medios de pago electronicos).

Tu tarea es analizar el plan de lanzamiento e identificar los riesgos mas relevantes para Disashop.

Para cada riesgo identifica:
- title: nombre corto del riesgo
- description: descripcion del riesgo y su impacto potencial sobre la red de PdV, sobre el partner o sobre Disashop
- severity: "low" | "medium" | "high" | "critical"
- category: "legal" | "technical" | "operational" | "financial" | "compliance"
- mitigation: estrategia concreta de mitigacion (no genericos tipo "hacer mas testing")

Ademas proporciona:
- overall_risk_level: nivel de riesgo global del lanzamiento
- regulatory_notes: normativas especificas aplicables (PSD2, DORA, GDPR/LOPD, LGT telco, normativa de paqueteria, normativa de transporte publico, KYC/AML) por pais relevante (ES/PE/DO).
- recommendations: recomendaciones generales para reducir el riesgo del lanzamiento.

Identifica entre 4 y 8 riesgos. Cubre obligatoriamente al menos: (a) riesgo regulatorio multi-pais, (b) riesgo de fraude transaccional, (c) riesgo de dependencia de partner u operador, (d) riesgo operacional sobre la red de PdV (SLA, soporte, churn)."""


class RiskAnalystAgent(BaseAgent):
    name = "risk_analyst"
    description = (
        "Identifica riesgos legales, tecnicos y operacionales de la solucion. "
        "Agente no critico: su fallo no detiene el pipeline. "
        "NO evalua la calidad tecnica de la solucion."
    )

    async def execute(self, context: SharedContext, **kwargs) -> SharedContext:
        start = time.monotonic()
        db_session = kwargs.get("db_session")

        if context.architecture is None:
            return context

        arch = context.architecture
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Iniciativa de lanzamiento Disashop:\n{context.original_request}\n\n"
                    f"Plan de lanzamiento propuesto:\n{arch.summary}\n\n"
                    f"Workstreams principales: "
                    f"{', '.join(f'{c.name} [{c.technology}]' for c in arch.components)}\n\n"
                    "Identifica los principales riesgos de este lanzamiento."
                ),
            },
        ]

        try:
            result, usage = await call_llm(
                messages=messages,
                response_model=_RiskOutput,
                db_session=db_session,
            )
        except LLMError as e:
            # Agente no critico: log y continuar sin risk_assessment
            self._record_error(context, e)
            self._record_trace(
                context, start,
                input_summary="analisis de riesgos fallido",
                output_summary=f"ERROR: {str(e)[:100]}",
                token_usage=TokenUsage(),
            )
            return context

        context.risk_assessment = RiskAssessment(
            risks=[
                Risk(
                    title=r.title,
                    description=r.description,
                    severity=r.severity,
                    category=r.category,
                    mitigation=r.mitigation,
                )
                for r in result.risks
            ],
            overall_risk_level=result.overall_risk_level,
            regulatory_notes=result.regulatory_notes,
            recommendations=result.recommendations,
        )

        self._record_trace(
            context,
            start,
            input_summary="arquitectura y request original",
            output_summary=(
                f"{len(context.risk_assessment.risks)} riesgos identificados, "
                f"nivel global: {context.risk_assessment.overall_risk_level}"
            ),
            token_usage=usage,
            model_used=kwargs.get("model", ""),
        )

        return context
