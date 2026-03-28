"""
Modelos SQLAlchemy para persistencia en PostgreSQL.

Tablas:
- executions: una fila por ejecucion completa del pipeline
- agent_traces: una fila por invocacion de agente
- llm_cache: cache de respuestas LLM indexadas por hash del prompt
- review_history: historial de revisiones del Reviewer
- errors: errores registrados durante ejecuciones
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Execution(Base):
    """Registro de una ejecucion completa del sistema multi-agente."""

    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    original_request: Mapped[str] = mapped_column(Text, nullable=False)
    final_state: Mapped[str] = mapped_column(String(50), nullable=False)
    final_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    revision_count: Mapped[int] = mapped_column(Integer, default=0)
    overall_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relaciones
    traces: Mapped[list["AgentTrace"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["ReviewHistory"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )
    errors: Mapped[list["ExecutionError"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )


class AgentTrace(Base):
    """Traza de una invocacion de agente dentro de una ejecucion."""

    __tablename__ = "agent_traces"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    execution_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    input_summary: Mapped[str] = mapped_column(Text, default="")
    output_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    model_used: Mapped[str] = mapped_column(String(100), default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    from_cache: Mapped[bool] = mapped_column(Boolean, default=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    execution: Mapped["Execution"] = relationship(back_populates="traces")


class LLMCache(Base):
    """Cache de respuestas LLM indexadas por hash SHA-256 del prompt."""

    __tablename__ = "llm_cache"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    messages: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    token_usage: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    hits: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("prompt_hash", "model", name="uq_cache_hash_model"),)


class ReviewHistory(Base):
    """Historial de cada iteracion de revision del Reviewer."""

    __tablename__ = "review_history"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    execution_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    strengths: Mapped[list] = mapped_column(JSONB, default=list)
    weaknesses: Mapped[list] = mapped_column(JSONB, default=list)
    suggestions: Mapped[list] = mapped_column(JSONB, default=list)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    execution: Mapped["Execution"] = relationship(back_populates="reviews")


class ExecutionError(Base):
    """Error registrado durante una ejecucion."""

    __tablename__ = "errors"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    execution_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    error_type: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    execution: Mapped["Execution"] = relationship(back_populates="errors")
