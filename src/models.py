"""
Contratos de datos del sistema multi-agente.

Todos los schemas Pydantic que definen la interfaz entre agentes se definen aqui.
Ningun agente importa directamente de otro: solo de este modulo.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Primitivos compartidos
# ---------------------------------------------------------------------------


class TokenUsage(BaseModel):
    """Consumo de tokens de una llamada al LLM."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached: bool = False  # True si la respuesta provino de cache


class ErrorRecord(BaseModel):
    """Registro de un error ocurrido durante la ejecucion."""

    agent_name: str
    error_type: str
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AgentTrace(BaseModel):
    """Traza de una invocacion de agente."""

    agent_name: str
    state: str
    input_summary: str
    output_summary: str
    duration_ms: float
    model_used: str
    token_usage: TokenUsage
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Schemas de subtareas
# ---------------------------------------------------------------------------


class SubTask(BaseModel):
    """Una subtarea derivada del request original."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str
    domain: str  # e.g. "product", "legal", "technical", "market", "planning"
    priority: int = Field(ge=1, le=5, description="1=mas alta, 5=mas baja")


# ---------------------------------------------------------------------------
# Outputs de agentes especializados
# ---------------------------------------------------------------------------


class DomainAnalysis(BaseModel):
    """Analisis de una subtarea por el Domain Expert."""

    subtask_id: str
    agent_name: str = "domain_expert"
    findings: str
    recommendations: list[str]
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    degraded: bool = False  # True si el analisis es resultado de un fallo


class Component(BaseModel):
    """Componente de la arquitectura propuesta."""

    name: str
    description: str
    technology: str
    responsibilities: list[str]


class Architecture(BaseModel):
    """Propuesta de arquitectura/solucion generada por el Architect."""

    agent_name: str = "architect"
    summary: str
    components: list[Component]
    integration_notes: str
    tech_decisions: list[str] = Field(
        default_factory=list, description="Decisiones tecnicas con sus trade-offs"
    )
    revision_notes: str = Field(
        default="", description="Notas sobre cambios respecto a revision anterior"
    )
    confidence: float = Field(ge=0.0, le=1.0)


class ReviewResult(BaseModel):
    """Resultado de la revision critica del Reviewer."""

    agent_name: str = "reviewer"
    revision_number: int = 1
    approved: bool
    confidence: float = Field(ge=0.0, le=1.0)
    strengths: list[str]
    weaknesses: list[str]
    suggestions: list[str]
    reasoning: str


class Risk(BaseModel):
    """Riesgo identificado por el Risk Analyst."""

    title: str
    description: str
    severity: Literal["low", "medium", "high", "critical"]
    category: Literal["legal", "technical", "operational", "financial", "compliance"]
    mitigation: str


class RiskAssessment(BaseModel):
    """Evaluacion de riesgos del Risk Analyst."""

    agent_name: str = "risk_analyst"
    risks: list[Risk]
    overall_risk_level: Literal["low", "medium", "high", "critical"]
    regulatory_notes: str = ""
    recommendations: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Estado compartido del sistema (pasa por todos los agentes)
# ---------------------------------------------------------------------------


class SharedContext(BaseModel):
    """
    Estado compartido del pipeline. El orchestrator lo crea y cada agente
    lo recibe, modifica su seccion y lo devuelve.

    Es la unica fuente de verdad del estado actual de la ejecucion.
    """

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    original_request: str

    # Estado de la maquina de estados
    current_state: str = "RECEIVED"

    # Resultados de cada agente (None = aun no ejecutado)
    subtasks: list[SubTask] = Field(default_factory=list)
    domain_analyses: dict[str, DomainAnalysis] = Field(default_factory=dict)
    architecture: Architecture | None = None
    review: ReviewResult | None = None
    risk_assessment: RiskAssessment | None = None

    # Control de flujo
    revision_count: int = 0

    # Observabilidad
    traces: list[AgentTrace] = Field(default_factory=list)
    errors: list[ErrorRecord] = Field(default_factory=list)

    # Resultado final (se popula en estado FINALIZING)
    final_output: FinalOutput | None = None


# ---------------------------------------------------------------------------
# Output final estructurado
# ---------------------------------------------------------------------------


class OutputMetadata(BaseModel):
    """Metadatos de la ejecucion completa."""

    request_id: str
    started_at: datetime
    finished_at: datetime
    total_duration_ms: float
    total_tokens: int
    cached_calls: int
    agents_invoked: list[str]
    states_traversed: list[str]
    revisions_performed: int
    errors_encountered: int


class FinalOutput(BaseModel):
    """
    Respuesta final estructurada del sistema.
    Incluye el resultado, trazas de ejecucion, confianza por seccion y metadatos.
    """

    request_id: str
    original_request: str

    # Resultado principal
    solution: Architecture
    domain_analyses: dict[str, DomainAnalysis]
    review: ReviewResult
    risk_assessment: RiskAssessment | None

    # Trazabilidad
    agent_traces: list[AgentTrace]
    errors: list[ErrorRecord]
    metadata: OutputMetadata

    # Nivel de confianza global (promedio ponderado)
    overall_confidence: float = Field(ge=0.0, le=1.0)

    def to_markdown(self) -> str:
        """Genera un resumen en Markdown del output final."""
        lines = [
            f"# Resultado del Analisis",
            f"\n**Request ID:** `{self.request_id}`",
            f"**Confianza global:** {self.overall_confidence:.0%}",
            f"**Duracion:** {self.metadata.total_duration_ms:.0f}ms",
            f"**Tokens utilizados:** {self.metadata.total_tokens}",
            f"**Revisiones realizadas:** {self.metadata.revisions_performed}",
            f"\n## Solucion\n",
            f"{self.solution.summary}",
            f"\n### Componentes\n",
        ]
        for c in self.solution.components:
            lines.append(f"- **{c.name}** ({c.technology}): {c.description}")
        if self.risk_assessment:
            lines.append(f"\n## Riesgos ({self.risk_assessment.overall_risk_level.upper()})\n")
            for r in self.risk_assessment.risks:
                lines.append(f"- [{r.severity.upper()}] **{r.title}**: {r.description}")
        lines.append(f"\n## Trazas de Ejecucion\n")
        for t in self.agent_traces:
            lines.append(
                f"- `{t.agent_name}` ({t.state}): {t.duration_ms:.0f}ms, "
                f"{t.token_usage.total_tokens} tokens"
                + (" [CACHE]" if t.token_usage.cached else "")
            )
        return "\n".join(lines)
