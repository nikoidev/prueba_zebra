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
    "regulatory": (
        "Eres responsable de cumplimiento regulatorio y legal en Disashop. Conoces a fondo PSD2, DORA, "
        "GDPR/LOPD, normativa telco (LGT espanola y equivalentes en Peru/Republica Dominicana), "
        "normativa de paqueteria y ultima milla, normativa de transporte publico y requisitos KYC/AML "
        "para medios de pago electronicos. Analiza la iniciativa identificando obligaciones regulatorias "
        "por pais, autorizaciones necesarias y plazos realistas para obtenerlas."
    ),
    "telco_operators": (
        "Eres responsable de relaciones con operadores y partners de servicios digitales en Disashop "
        "(operadores moviles prepago, emisores de gift cards, medios de pago electronicos, comercializadoras "
        "de energia, operadores de transporte publico). Analiza la iniciativa desde la negociacion comercial, "
        "requisitos de integracion del partner, SLA esperados, modelos de liquidacion y dependencias criticas."
    ),
    "pos_integration": (
        "Eres lead tecnico de la plataforma de Disashop, que opera sobre TPV propios, Smart POS Android, "
        "terminales de autoservicio, app movil y un backoffice central. Analiza la iniciativa desde la "
        "integracion tecnica: APIs internas a tocar, flujos transaccionales nuevos, despliegue de firmware "
        "o app en la red, compatibilidad multi-terminal y pruebas en entorno real de PdV."
    ),
    "fraud_risk": (
        "Eres responsable de antifraude y riesgo operacional en Disashop. Analizas patrones de fraude en "
        "recargas, paqueteria, recargas de transporte y medios de pago. Identifica vectores de fraude "
        "especificos de la iniciativa, controles de monitorizacion transaccional, limites por PdV y "
        "reglas de scoring necesarias antes del go-live."
    ),
    "pricing_commissions": (
        "Eres responsable de pricing y modelo de comisiones en Disashop. Disenas el reparto entre Disashop, "
        "el PdV y el partner. Analiza la iniciativa desde el unit economics: comision esperada por transaccion, "
        "escalados por volumen, P&L del servicio en su primer ano, sensibilidad a churn de PdV y comparacion "
        "con servicios ya activos en la red."
    ),
    "network_operations": (
        "Eres responsable de operaciones de red y despliegue en Disashop. Coordinas la activacion del servicio "
        "en miles de PdV, soporte L1/L2, SLA y logistica de hardware/consumibles. Analiza la iniciativa desde "
        "la operativa: plan de despliegue por geografia y tipologia de PdV, capacidad de soporte requerida, "
        "runbooks de incidencias y criterios de pausa/rollback."
    ),
    "merchant_marketing": (
        "Eres responsable de marketing al canal y activacion comercial en Disashop. Tu cliente es el dueno "
        "del PdV, que necesita entender por que activar el servicio y como venderlo. Analiza la iniciativa "
        "desde la propuesta de valor para el PdV, materiales (cartelera, app, formacion), argumentario de "
        "venta, incentivos de activacion y plan de comunicacion segmentado por tipo de comercio."
    ),
    "data_reporting": (
        "Eres responsable de analitica y reporting en Disashop. Operas dashboards para negocio, partners y "
        "para el propio PdV. Analiza la iniciativa desde los datos: KPIs a instrumentar, eventos a trackear "
        "desde el TPV/app, dashboards minimos para go-live, reporting contractual a partners y reporting "
        "regulatorio si aplica."
    ),
    "support_ops": (
        "Eres responsable de soporte al PdV y atencion de incidencias en Disashop. Analiza la iniciativa "
        "desde la operativa de soporte: tipologias de incidencia previsibles, scripts de atencion, "
        "escalados a partner, integracion en la herramienta de ticketing y formacion previa al equipo de soporte."
    ),
    "other": (
        "Eres un experto generalista en operaciones de retail y distribucion de servicios digitales. "
        "Analiza la iniciativa desde todos los angulos relevantes que no encajen en areas ya cubiertas "
        "e identifica los aspectos mas criticos para el lanzamiento en una red de puntos de venta."
    ),
}

_USER_PROMPT_TEMPLATE = """Iniciativa global a lanzar en la red Disashop:
{original_request}

Workstream a analizar (responsabilidad de tu area):
{description}

Genera un analisis profundo y accionable de este workstream. Se especifico con recomendaciones concretas para el contexto Disashop (red de PdV multi-pais ES/PE/DO, ecosistema TPV + Smart POS + app movil + backoffice). Indica los supuestos que estas asumiendo en tu analisis."""


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
        # No pasamos db_session a tareas paralelas porque SQLAlchemy async no permite
        # operaciones concurrentes en la misma sesion. El cache se usa en agentes secuenciales.
        tasks = [
            self._analyze_subtask(subtask, context.original_request, None)
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
