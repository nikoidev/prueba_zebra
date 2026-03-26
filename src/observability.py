"""
Observabilidad del sistema: logging estructurado y trazas de ejecucion.

Usa structlog para logs JSON. Cada agente registra su ejecucion con timing y tokens.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from functools import wraps
from typing import Any, Callable

import structlog
from structlog.types import FilteringBoundLogger

from src.config import get_settings


def configure_logging() -> None:
    """Configura structlog con output JSON estructurado."""
    settings = get_settings()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Procesadores de structlog
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.JSONRenderer(),
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configurar logging estandar para librerias externas
    logging.basicConfig(
        format="%(message)s",
        level=log_level,
    )


def get_logger(name: str) -> FilteringBoundLogger:
    return structlog.get_logger(name)


def compute_metrics(traces) -> dict[str, Any]:
    """
    Calcula metricas agregadas a partir de las trazas de agentes.

    Args:
        traces: Lista de AgentTrace

    Returns:
        Dict con metricas: total_tokens, total_duration_ms, cache_rate, por_agente
    """
    if not traces:
        return {
            "total_tokens": 0,
            "total_duration_ms": 0.0,
            "cache_rate": 0.0,
            "agents_invoked": [],
            "per_agent": {},
        }

    total_tokens = sum(t.token_usage.total_tokens for t in traces)
    total_duration = sum(t.duration_ms for t in traces)
    cached_calls = sum(1 for t in traces if t.token_usage.cached)
    cache_rate = cached_calls / len(traces) if traces else 0.0

    per_agent: dict[str, dict] = {}
    for t in traces:
        if t.agent_name not in per_agent:
            per_agent[t.agent_name] = {
                "calls": 0,
                "total_tokens": 0,
                "total_duration_ms": 0.0,
                "cached_calls": 0,
            }
        per_agent[t.agent_name]["calls"] += 1
        per_agent[t.agent_name]["total_tokens"] += t.token_usage.total_tokens
        per_agent[t.agent_name]["total_duration_ms"] += t.duration_ms
        per_agent[t.agent_name]["cached_calls"] += 1 if t.token_usage.cached else 0

    return {
        "total_tokens": total_tokens,
        "total_duration_ms": round(total_duration, 1),
        "cache_rate": round(cache_rate, 2),
        "cached_calls": cached_calls,
        "agents_invoked": list(per_agent.keys()),
        "per_agent": per_agent,
    }
