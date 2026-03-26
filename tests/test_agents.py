"""Tests de los agentes. Mockean call_llm para no hacer llamadas reales al LLM."""

from unittest.mock import AsyncMock, patch

import pytest

from src.models import (
    Architecture,
    Component,
    DomainAnalysis,
    ReviewResult,
    SharedContext,
    SubTask,
    TokenUsage,
)


def make_context(request: str = "Test request") -> SharedContext:
    return SharedContext(original_request=request)


def make_token_usage() -> TokenUsage:
    return TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)


# ---------------------------------------------------------------------------
# DecomposerAgent
# ---------------------------------------------------------------------------


class TestDecomposerAgent:
    @pytest.mark.asyncio
    async def test_populates_subtasks(self):
        from src.agents.decomposer import DecomposerAgent, _DecomposerOutput, _SubTaskRaw

        mock_output = _DecomposerOutput(
            subtasks=[
                _SubTaskRaw(description="Analisis de mercado", domain="market", priority=1),
                _SubTaskRaw(description="Arquitectura tecnica", domain="technical", priority=2),
                _SubTaskRaw(description="Riesgos legales", domain="legal", priority=3),
            ],
            reasoning="Test decomposition",
        )

        with patch("src.agents.decomposer.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (mock_output, make_token_usage())
            agent = DecomposerAgent()
            ctx = make_context()
            result = await agent.execute(ctx)

        assert len(result.subtasks) == 3
        assert result.subtasks[0].domain == "market"
        assert result.subtasks[1].domain == "technical"
        assert len(result.traces) == 1
        assert result.traces[0].agent_name == "decomposer"

    @pytest.mark.asyncio
    async def test_fallback_on_empty_subtasks(self):
        from src.agents.decomposer import DecomposerAgent, _DecomposerOutput

        mock_output = _DecomposerOutput(subtasks=[], reasoning="empty")

        with patch("src.agents.decomposer.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (mock_output, make_token_usage())
            agent = DecomposerAgent()
            ctx = make_context("Design a system")
            result = await agent.execute(ctx)

        # Fallback: debe crear una sola subtarea
        assert len(result.subtasks) == 1
        assert result.subtasks[0].domain == "other"

    @pytest.mark.asyncio
    async def test_propagates_llm_error(self):
        from src.agents.decomposer import DecomposerAgent
        from src.llm import LLMError

        with patch("src.agents.decomposer.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = LLMError("LLM unavailable")
            agent = DecomposerAgent()
            ctx = make_context()

            with pytest.raises(LLMError):
                await agent.execute(ctx)

        # El error debe estar registrado en el contexto
        assert len(ctx.errors) == 1
        assert ctx.errors[0].agent_name == "decomposer"


# ---------------------------------------------------------------------------
# DomainExpertAgent
# ---------------------------------------------------------------------------


class TestDomainExpertAgent:
    @pytest.mark.asyncio
    async def test_parallel_analysis(self):
        from src.agents.domain_expert import DomainExpertAgent, _DomainOutput

        mock_output = _DomainOutput(
            findings="Test findings",
            recommendations=["Rec 1", "Rec 2"],
            assumptions=["Assumption 1"],
            confidence=0.85,
        )

        with patch("src.agents.domain_expert.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (mock_output, make_token_usage())
            agent = DomainExpertAgent()
            ctx = make_context()
            ctx.subtasks = [
                SubTask(description="Subtarea 1", domain="technical", priority=1),
                SubTask(description="Subtarea 2", domain="market", priority=2),
            ]
            result = await agent.execute(ctx)

        assert len(result.domain_analyses) == 2
        assert mock_llm.call_count == 2  # una llamada por subtarea
        for subtask in ctx.subtasks:
            assert subtask.id in result.domain_analyses
            assert result.domain_analyses[subtask.id].confidence == 0.85

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_partial_failure(self):
        from src.agents.domain_expert import DomainExpertAgent, _DomainOutput
        from src.llm import LLMError

        call_count = 0

        async def mock_llm_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise LLMError("First subtask failed")
            return (
                _DomainOutput(
                    findings="OK", recommendations=[], confidence=0.8
                ),
                make_token_usage(),
            )

        with patch("src.agents.domain_expert.call_llm", side_effect=mock_llm_side_effect):
            agent = DomainExpertAgent()
            ctx = make_context()
            ctx.subtasks = [
                SubTask(description="Failing subtask", domain="legal", priority=1),
                SubTask(description="Passing subtask", domain="technical", priority=2),
            ]
            result = await agent.execute(ctx)

        assert len(result.domain_analyses) == 2
        # Primera subtarea debe estar degradada
        failing_id = ctx.subtasks[0].id
        passing_id = ctx.subtasks[1].id
        assert result.domain_analyses[failing_id].degraded is True
        assert result.domain_analyses[failing_id].confidence == 0.0
        assert result.domain_analyses[passing_id].degraded is False
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_empty_subtasks(self):
        from src.agents.domain_expert import DomainExpertAgent

        with patch("src.agents.domain_expert.call_llm", new_callable=AsyncMock) as mock_llm:
            agent = DomainExpertAgent()
            ctx = make_context()
            result = await agent.execute(ctx)

        mock_llm.assert_not_called()
        assert result.domain_analyses == {}


# ---------------------------------------------------------------------------
# ReviewerAgent
# ---------------------------------------------------------------------------


class TestReviewerAgent:
    def make_architecture(self, confidence: float = 0.8) -> Architecture:
        return Architecture(
            summary="Test architecture",
            components=[
                Component(
                    name="API",
                    description="REST API",
                    technology="FastAPI",
                    responsibilities=["serve requests"],
                )
            ],
            integration_notes="Standard integration",
            confidence=confidence,
        )

    @pytest.mark.asyncio
    async def test_approved_review(self):
        from src.agents.reviewer import ReviewerAgent, _ReviewOutput

        mock_output = _ReviewOutput(
            approved=True,
            confidence=0.9,
            strengths=["Good architecture", "Clear components"],
            weaknesses=[],
            suggestions=[],
            reasoning="The solution is well-designed.",
        )

        with patch("src.agents.reviewer.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (mock_output, make_token_usage())
            agent = ReviewerAgent()
            ctx = make_context()
            ctx.architecture = self.make_architecture()
            result = await agent.execute(ctx)

        assert result.review is not None
        assert result.review.approved is True
        assert result.review.confidence == 0.9
        assert result.review.revision_number == 1

    @pytest.mark.asyncio
    async def test_rejected_review(self):
        from src.agents.reviewer import ReviewerAgent, _ReviewOutput

        mock_output = _ReviewOutput(
            approved=False,
            confidence=0.5,
            strengths=["Some good points"],
            weaknesses=["Missing security", "No data strategy"],
            suggestions=["Add auth layer", "Define data model"],
            reasoning="Incomplete solution.",
        )

        with patch("src.agents.reviewer.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (mock_output, make_token_usage())
            agent = ReviewerAgent()
            ctx = make_context()
            ctx.architecture = self.make_architecture()
            result = await agent.execute(ctx)

        assert result.review.approved is False
        assert result.review.confidence == 0.5
        assert len(result.review.weaknesses) == 2

    @pytest.mark.asyncio
    async def test_degraded_review_on_llm_error(self):
        from src.agents.reviewer import ReviewerAgent
        from src.llm import LLMError

        with patch("src.agents.reviewer.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = LLMError("LLM error")
            agent = ReviewerAgent()
            ctx = make_context()
            ctx.architecture = self.make_architecture()
            result = await agent.execute(ctx)

        assert result.review is not None
        assert result.review.approved is False
        assert result.review.confidence == 0.0
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_revision_number_increments(self):
        from src.agents.reviewer import ReviewerAgent, _ReviewOutput

        mock_output = _ReviewOutput(
            approved=True, confidence=0.8,
            strengths=["ok"], weaknesses=[], suggestions=[], reasoning="ok"
        )

        with patch("src.agents.reviewer.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (mock_output, make_token_usage())
            agent = ReviewerAgent()
            ctx = make_context()
            ctx.architecture = self.make_architecture()
            ctx.revision_count = 2  # Simular segunda revision
            result = await agent.execute(ctx)

        assert result.review.revision_number == 3  # revision_count + 1
