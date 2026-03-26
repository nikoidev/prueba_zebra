"""Tests de los schemas Pydantic."""

import pytest
from pydantic import ValidationError

from src.models import (
    Architecture,
    Component,
    DomainAnalysis,
    ErrorRecord,
    FinalOutput,
    OutputMetadata,
    ReviewResult,
    Risk,
    RiskAssessment,
    SharedContext,
    SubTask,
    TokenUsage,
    AgentTrace,
)
from datetime import datetime


def test_subtask_priority_validation():
    with pytest.raises(ValidationError):
        SubTask(description="test", domain="technical", priority=0)
    with pytest.raises(ValidationError):
        SubTask(description="test", domain="technical", priority=6)
    st = SubTask(description="test", domain="technical", priority=3)
    assert st.priority == 3


def test_subtask_has_auto_id():
    st = SubTask(description="test", domain="market", priority=1)
    assert st.id is not None
    assert len(st.id) == 8


def test_token_usage_defaults():
    tu = TokenUsage()
    assert tu.total_tokens == 0
    assert tu.cached is False


def test_domain_analysis_degraded_default():
    da = DomainAnalysis(
        subtask_id="abc",
        findings="test findings",
        recommendations=[],
        confidence=0.0,
    )
    assert da.degraded is False
    assert da.agent_name == "domain_expert"


def test_domain_analysis_confidence_range():
    with pytest.raises(ValidationError):
        DomainAnalysis(subtask_id="x", findings="f", recommendations=[], confidence=1.5)
    with pytest.raises(ValidationError):
        DomainAnalysis(subtask_id="x", findings="f", recommendations=[], confidence=-0.1)


def test_review_result_defaults():
    r = ReviewResult(
        approved=True,
        confidence=0.85,
        strengths=["s1"],
        weaknesses=[],
        suggestions=[],
        reasoning="ok",
    )
    assert r.revision_number == 1
    assert r.agent_name == "reviewer"


def test_shared_context_initialization():
    ctx = SharedContext(original_request="test request")
    assert ctx.current_state == "RECEIVED"
    assert ctx.subtasks == []
    assert ctx.domain_analyses == {}
    assert ctx.revision_count == 0
    assert ctx.traces == []
    assert ctx.errors == []
    assert ctx.final_output is None


def test_shared_context_has_auto_request_id():
    ctx = SharedContext(original_request="test")
    assert ctx.request_id is not None
    assert len(ctx.request_id) == 36  # UUID format


def test_architecture_defaults():
    arch = Architecture(
        summary="test",
        components=[],
        integration_notes="none",
        confidence=0.8,
    )
    assert arch.agent_name == "architect"
    assert arch.tech_decisions == []
    assert arch.revision_notes == ""


def test_risk_severity_validation():
    with pytest.raises(ValidationError):
        Risk(
            title="t",
            description="d",
            severity="extreme",  # no valido
            category="legal",
            mitigation="m",
        )


def test_final_output_to_markdown():
    arch = Architecture(
        summary="Test summary",
        components=[
            Component(
                name="API",
                description="REST API",
                technology="FastAPI",
                responsibilities=["handle requests"],
            )
        ],
        integration_notes="API connects to DB",
        confidence=0.9,
    )
    review = ReviewResult(
        approved=True,
        confidence=0.85,
        strengths=["good architecture"],
        weaknesses=[],
        suggestions=[],
        reasoning="Approved",
    )
    now = datetime.utcnow()
    output = FinalOutput(
        request_id="test-id",
        original_request="Design an API",
        solution=arch,
        domain_analyses={},
        review=review,
        risk_assessment=None,
        agent_traces=[],
        errors=[],
        metadata=OutputMetadata(
            request_id="test-id",
            started_at=now,
            finished_at=now,
            total_duration_ms=1000.0,
            total_tokens=500,
            cached_calls=0,
            agents_invoked=["decomposer", "architect"],
            states_traversed=["DECOMPOSING", "ARCHITECTING"],
            revisions_performed=0,
            errors_encountered=0,
        ),
        overall_confidence=0.87,
    )
    md = output.to_markdown()
    assert "Test summary" in md
    assert "FastAPI" in md
    assert "87%" in md


def test_error_record_timestamp():
    err = ErrorRecord(agent_name="test", error_type="ValueError", message="oops")
    assert err.timestamp is not None


def test_shared_context_json_roundtrip():
    ctx = SharedContext(original_request="roundtrip test")
    ctx.subtasks = [SubTask(description="subtask 1", domain="technical", priority=1)]
    data = ctx.model_dump(mode="json")
    ctx2 = SharedContext.model_validate(data)
    assert ctx2.request_id == ctx.request_id
    assert len(ctx2.subtasks) == 1
    assert ctx2.subtasks[0].description == "subtask 1"
