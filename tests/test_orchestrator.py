"""Tests del orquestador: transiciones de estado, loop de revision, degradacion."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models import (
    Architecture,
    Component,
    DomainAnalysis,
    ReviewResult,
    RiskAssessment,
    Risk,
    SharedContext,
    SubTask,
    TokenUsage,
)
from src.orchestrator import State, _next_state


# ---------------------------------------------------------------------------
# Tests de la maquina de estados
# ---------------------------------------------------------------------------


class TestStateMachine:
    def make_context(self, state: str = "RECEIVED") -> SharedContext:
        ctx = SharedContext(original_request="test")
        ctx.current_state = state
        return ctx

    def make_review(self, approved: bool, confidence: float) -> ReviewResult:
        return ReviewResult(
            approved=approved,
            confidence=confidence,
            strengths=["s"],
            weaknesses=["w"] if not approved else [],
            suggestions=["fix it"] if not approved else [],
            reasoning="test",
        )

    def test_linear_transitions(self):
        transitions = [
            ("RECEIVED", "DECOMPOSING"),
            ("DECOMPOSING", "ANALYZING"),
            ("ANALYZING", "ARCHITECTING"),
            ("REVISING", "REVIEWING"),
            ("FINALIZING", "DONE"),
        ]
        for from_state, expected_next in transitions:
            ctx = self.make_context(from_state)
            result = _next_state(ctx)
            assert result.value == expected_next, f"From {from_state}: expected {expected_next}, got {result.value}"

    def test_reviewing_approved_goes_to_finalizing(self):
        ctx = self.make_context("REVIEWING")
        ctx.review = self.make_review(approved=True, confidence=0.9)
        result = _next_state(ctx)
        assert result == State.FINALIZING

    def test_reviewing_low_confidence_goes_to_revising(self):
        ctx = self.make_context("REVIEWING")
        ctx.review = self.make_review(approved=False, confidence=0.5)
        # threshold default es 0.7, max_revisions default es 2
        result = _next_state(ctx)
        assert result == State.REVISING

    def test_reviewing_max_revisions_reached_goes_to_finalizing(self):
        ctx = self.make_context("REVIEWING")
        ctx.review = self.make_review(approved=False, confidence=0.5)
        ctx.revision_count = 2  # max_revisions = 2
        result = _next_state(ctx)
        assert result == State.FINALIZING

    def test_reviewing_no_review_goes_to_failed(self):
        ctx = self.make_context("REVIEWING")
        ctx.review = None
        result = _next_state(ctx)
        assert result == State.FAILED

    def test_reviewing_high_confidence_but_not_approved_revises(self):
        """Si confidence >= threshold pero approved=False, igual se revisa."""
        ctx = self.make_context("REVIEWING")
        ctx.review = self.make_review(approved=False, confidence=0.8)
        result = _next_state(ctx)
        assert result == State.REVISING


# ---------------------------------------------------------------------------
# Tests del pipeline completo (mocking de todos los agentes)
# ---------------------------------------------------------------------------


def make_subtask(domain: str = "technical") -> SubTask:
    return SubTask(description=f"Subtarea de {domain}", domain=domain, priority=1)


def make_architecture() -> Architecture:
    return Architecture(
        summary="Test architecture",
        components=[
            Component(name="API", description="API", technology="FastAPI", responsibilities=["serve"])
        ],
        integration_notes="Test integration",
        confidence=0.85,
    )


def make_review(approved: bool = True, confidence: float = 0.85) -> ReviewResult:
    return ReviewResult(
        approved=approved,
        confidence=confidence,
        strengths=["good"],
        weaknesses=[] if approved else ["missing X"],
        suggestions=[] if approved else ["add X"],
        reasoning="test",
    )


def make_risk_assessment() -> RiskAssessment:
    return RiskAssessment(
        risks=[Risk(
            title="Test risk",
            description="A risk",
            severity="low",
            category="technical",
            mitigation="Monitor it",
        )],
        overall_risk_level="low",
    )


class TestOrchestratorPipeline:
    def _make_agent_mock(self, updates: dict):
        """Crea un mock de agente que aplica updates al contexto."""
        async def execute(context, **kwargs):
            for key, val in updates.items():
                setattr(context, key, val)
            return context

        mock = MagicMock()
        mock.return_value.execute = execute
        return mock

    @pytest.mark.asyncio
    async def test_happy_path(self):
        """Pipeline completo sin revisiones."""
        from src.orchestrator import run

        subtasks = [make_subtask("technical"), make_subtask("market")]
        arch = make_architecture()
        review = make_review(approved=True, confidence=0.9)
        risk = make_risk_assessment()
        domain_analyses = {
            subtasks[0].id: DomainAnalysis(subtask_id=subtasks[0].id, findings="f", recommendations=[], confidence=0.9),
            subtasks[1].id: DomainAnalysis(subtask_id=subtasks[1].id, findings="f", recommendations=[], confidence=0.8),
        }

        async def mock_decomposer(context, **kwargs):
            context.subtasks = subtasks
            return context

        async def mock_domain_expert(context, **kwargs):
            context.domain_analyses = domain_analyses
            return context

        async def mock_architect(context, **kwargs):
            context.architecture = arch
            return context

        async def mock_reviewer(context, **kwargs):
            context.review = review
            return context

        async def mock_risk_analyst(context, **kwargs):
            context.risk_assessment = risk
            return context

        with (
            patch("src.orchestrator.DecomposerAgent") as MockDecomp,
            patch("src.orchestrator.DomainExpertAgent") as MockDomain,
            patch("src.orchestrator.ArchitectAgent") as MockArch,
            patch("src.orchestrator.ReviewerAgent") as MockReview,
            patch("src.orchestrator.RiskAnalystAgent") as MockRisk,
        ):
            MockDecomp.return_value.execute = mock_decomposer
            MockDomain.return_value.execute = mock_domain_expert
            MockArch.return_value.execute = mock_architect
            MockReview.return_value.execute = mock_reviewer
            MockRisk.return_value.execute = mock_risk_analyst

            result = await run("Test request", db_session=None)

        assert result is not None
        assert result.overall_confidence > 0
        assert result.solution is not None
        assert result.review.approved is True
        assert result.metadata.revisions_performed == 0

    @pytest.mark.asyncio
    async def test_revision_loop(self):
        """El pipeline hace una revision y luego aprueba."""
        from src.orchestrator import run

        subtasks = [make_subtask()]
        arch = make_architecture()
        low_review = make_review(approved=False, confidence=0.5)
        high_review = make_review(approved=True, confidence=0.85)
        domain_analyses = {
            subtasks[0].id: DomainAnalysis(subtask_id=subtasks[0].id, findings="f", recommendations=[], confidence=0.9),
        }
        risk = make_risk_assessment()

        architect_call_count = 0
        reviewer_call_count = 0

        async def mock_architect(context, **kwargs):
            nonlocal architect_call_count
            architect_call_count += 1
            context.architecture = arch
            return context

        async def mock_reviewer(context, **kwargs):
            nonlocal reviewer_call_count
            reviewer_call_count += 1
            context.review = low_review if reviewer_call_count == 1 else high_review
            return context

        with (
            patch("src.orchestrator.DecomposerAgent") as MockDecomp,
            patch("src.orchestrator.DomainExpertAgent") as MockDomain,
            patch("src.orchestrator.ArchitectAgent") as MockArch,
            patch("src.orchestrator.ReviewerAgent") as MockReview,
            patch("src.orchestrator.RiskAnalystAgent") as MockRisk,
        ):
            MockDecomp.return_value.execute = AsyncMock(side_effect=lambda ctx, **kw: setattr(ctx, 'subtasks', subtasks) or ctx)
            MockDomain.return_value.execute = AsyncMock(side_effect=lambda ctx, **kw: setattr(ctx, 'domain_analyses', domain_analyses) or ctx)
            MockArch.return_value.execute = mock_architect
            MockReview.return_value.execute = mock_reviewer
            MockRisk.return_value.execute = AsyncMock(side_effect=lambda ctx, **kw: setattr(ctx, 'risk_assessment', risk) or ctx)

            result = await run("Test request", db_session=None)

        assert architect_call_count == 2  # inicial + 1 revision
        assert reviewer_call_count == 2   # inicial + tras revision
        assert result.metadata.revisions_performed == 1

    @pytest.mark.asyncio
    async def test_non_critical_agent_failure(self):
        """RiskAnalyst puede fallar sin romper el pipeline."""
        from src.orchestrator import run

        subtasks = [make_subtask()]
        arch = make_architecture()
        review = make_review(approved=True, confidence=0.9)
        domain_analyses = {
            subtasks[0].id: DomainAnalysis(subtask_id=subtasks[0].id, findings="f", recommendations=[], confidence=0.9),
        }

        async def mock_risk_analyst_fails(context, **kwargs):
            # No setea risk_assessment (simula fallo graceful)
            return context

        with (
            patch("src.orchestrator.DecomposerAgent") as MockDecomp,
            patch("src.orchestrator.DomainExpertAgent") as MockDomain,
            patch("src.orchestrator.ArchitectAgent") as MockArch,
            patch("src.orchestrator.ReviewerAgent") as MockReview,
            patch("src.orchestrator.RiskAnalystAgent") as MockRisk,
        ):
            MockDecomp.return_value.execute = AsyncMock(side_effect=lambda ctx, **kw: setattr(ctx, 'subtasks', subtasks) or ctx)
            MockDomain.return_value.execute = AsyncMock(side_effect=lambda ctx, **kw: setattr(ctx, 'domain_analyses', domain_analyses) or ctx)
            MockArch.return_value.execute = AsyncMock(side_effect=lambda ctx, **kw: setattr(ctx, 'architecture', arch) or ctx)
            MockReview.return_value.execute = AsyncMock(side_effect=lambda ctx, **kw: setattr(ctx, 'review', review) or ctx)
            MockRisk.return_value.execute = mock_risk_analyst_fails

            result = await run("Test request", db_session=None)

        # El pipeline completa aunque risk_assessment es None
        assert result is not None
        assert result.risk_assessment is None
