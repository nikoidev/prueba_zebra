"""
Schemas Pydantic especificos de la API web.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ProviderInfo(BaseModel):
    providers: list[str]
    default_provider: str
    default_model: str


class ModelsResponse(BaseModel):
    provider: str
    models: list[str]


class ExecutionSummary(BaseModel):
    id: str
    original_request: str
    final_state: str
    overall_confidence: float | None
    total_tokens: int
    duration_ms: float | None
    revision_count: int
    created_at: datetime


class ExecutionDetail(BaseModel):
    id: str
    original_request: str
    final_state: str
    overall_confidence: float | None
    total_tokens: int
    duration_ms: float | None
    revision_count: int
    created_at: datetime
    finished_at: datetime | None
    final_output: dict | None
    traces: list[dict]
    reviews: list[dict]
    errors: list[dict]
