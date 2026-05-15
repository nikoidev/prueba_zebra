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


_SYSTEM_PROMPT = """Eres el PMO (Program Management Office) del Disashop AI Lab, una compania tecnologica especializada en soluciones digitales para retail y punto de venta, con una red de mas de 30.000 establecimientos en Espana, Peru y Republica Dominicana.

Tu tarea es analizar una iniciativa de lanzamiento o evolucion de servicio y descomponerla en los workstreams (subtareas) que un comite de lanzamiento de Disashop tendria que coordinar para llevarla a produccion en la red de puntos de venta.

Para cada workstream debes identificar:
- description: descripcion clara y accionable del workstream (que hay que hacer y para que)
- domain: area responsable. Usa EXCLUSIVAMENTE una de estas categorias internas de Disashop:
    * "regulatory"          -> Cumplimiento regulatorio y legal multi-pais (PSD2, DORA, GDPR/LOPD, normativa telco LGT, normativa de paqueteria y transporte, KYC/AML)
    * "telco_operators"     -> Integracion y negociacion con operadores de telecomunicaciones, emisores de medios de pago y proveedores de servicio (recargas, PINs, gift cards)
    * "pos_integration"     -> Integracion tecnica con TPV, Smart POS, autoservicio, app movil y backoffice de Disashop
    * "fraud_risk"          -> Antifraude, riesgo operacional y monitorizacion transaccional
    * "pricing_commissions" -> Modelo de comisiones, pricing al PdV, P&L del servicio y unit economics
    * "network_operations"  -> Despliegue operativo en la red, logistica de activacion, soporte L1/L2 y SLA con PdV
    * "merchant_marketing"  -> Activacion comercial, formacion, materiales y argumentario para el dueno del PdV
    * "data_reporting"      -> Analitica, dashboards de seguimiento, reporting a negocio y a partners
    * "support_ops"         -> Soporte al cliente final del PdV y atencion de incidencias
    * "other"               -> Solo si ningun area encaja
- priority: 1 (mas alta, bloquea el go-live) a 5 (mas baja, post-launch)

Reglas:
- Genera entre 4 y 7 workstreams (no mas, no menos)
- Cada workstream debe ser atomico y tener un unico area responsable
- Cubre TODOS los aspectos criticos del lanzamiento: que ningun pais, integracion o riesgo regulatorio quede fuera
- Evita duplicados y solapamientos entre workstreams
- No inventes pasos genericos ("hacer un kickoff", "montar un plan"): cada workstream debe ser especifico de la iniciativa

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
                    f"Iniciativa a lanzar en la red Disashop:\n\n{context.original_request}\n\n"
                    "Descompon la iniciativa en los workstreams que el comite de lanzamiento debe coordinar."
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
