"""Tests del wrapper LLM: reintentos, fallback, parseo de JSON."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from src.llm import LLMError, LLMParseError, _parse_response
from src.models import TokenUsage


class SimpleOutput(BaseModel):
    value: str
    score: float


class TestParseResponse:
    def test_valid_json(self):
        raw = json.dumps({"value": "test", "score": 0.9})
        result = _parse_response(raw, SimpleOutput, [])
        assert result.value == "test"
        assert result.score == 0.9

    def test_markdown_code_block_stripped(self):
        raw = "```json\n{\"value\": \"test\", \"score\": 0.8}\n```"
        result = _parse_response(raw, SimpleOutput, [])
        assert result.value == "test"

    def test_invalid_json_raises_parse_error(self):
        raw = "this is not json"
        with pytest.raises(LLMParseError):
            _parse_response(raw, SimpleOutput, [])

    def test_wrong_schema_raises_parse_error(self):
        raw = json.dumps({"unexpected_field": "value"})
        with pytest.raises(LLMParseError):
            _parse_response(raw, SimpleOutput, [])

    def test_whitespace_stripped(self):
        raw = '   {"value": "hello", "score": 0.5}   '
        result = _parse_response(raw, SimpleOutput, [])
        assert result.value == "hello"


class TestCallWithRetry:
    @pytest.mark.asyncio
    async def test_successful_call(self):
        from src.llm import _call_with_retry

        mock_response = ('{"value": "ok", "score": 0.9}', TokenUsage(total_tokens=100))

        with patch("src.llm._call_openai", new_callable=AsyncMock) as mock_openai:
            mock_openai.return_value = mock_response
            with patch("src.llm.get_settings") as mock_settings:
                mock_settings.return_value.active_provider = "openai"
                mock_settings.return_value.max_retries = 3
                mock_settings.return_value.retry_min_wait = 0.01
                mock_settings.return_value.retry_max_wait = 0.1
                result_content, result_usage = await _call_with_retry(
                    [{"role": "user", "content": "test"}], "gpt-4o", 0.3
                )

        assert result_content is not None

    @pytest.mark.asyncio
    async def test_returns_none_on_all_failures(self):
        from src.llm import _call_with_retry

        with patch("src.llm._call_openai", new_callable=AsyncMock) as mock_openai:
            mock_openai.side_effect = Exception("Network error")
            with patch("src.llm.get_settings") as mock_settings:
                mock_settings.return_value.active_provider = "openai"
                mock_settings.return_value.max_retries = 2
                mock_settings.return_value.retry_min_wait = 0.01
                mock_settings.return_value.retry_max_wait = 0.1
                content, usage = await _call_with_retry(
                    [{"role": "user", "content": "test"}], "gpt-4o", 0.3
                )

        assert content is None


class TestCallLlmWithCache:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_llm(self):
        from src.llm import call_llm

        cached_data = {
            "response": {"value": "cached", "score": 0.7},
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cached": False},
        }

        mock_session = MagicMock()

        with patch("src.llm._get_cache", new_callable=AsyncMock) as mock_get_cache:
            mock_get_cache.return_value = (
                AsyncMock(return_value=cached_data),  # get_cached_response
                AsyncMock(),  # save_to_cache
            )
            with patch("src.llm._call_with_retry", new_callable=AsyncMock) as mock_retry:
                with patch("src.llm.get_settings") as mock_settings:
                    mock_settings.return_value.active_model = "gpt-4o"
                    mock_settings.return_value.active_fallback_model = "gpt-4o-mini"
                    result, usage = await call_llm(
                        messages=[{"role": "user", "content": "test"}],
                        response_model=SimpleOutput,
                        db_session=mock_session,
                    )

        mock_retry.assert_not_called()
        assert result.value == "cached"
        assert usage.cached is True

    @pytest.mark.asyncio
    async def test_no_cache_calls_llm(self):
        from src.llm import call_llm

        raw_response = json.dumps({"value": "fresh", "score": 0.8})
        usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)

        with patch("src.llm._get_cache", new_callable=AsyncMock) as mock_get_cache:
            mock_get_cache.return_value = (
                AsyncMock(return_value=None),  # cache miss
                AsyncMock(),
            )
            with patch("src.llm._call_with_retry", new_callable=AsyncMock) as mock_retry:
                mock_retry.return_value = (raw_response, usage)
                with patch("src.llm.get_settings") as mock_settings:
                    settings = MagicMock()
                    settings.fallback_model = "gpt-4o-mini"
                    mock_settings.return_value = settings

                    mock_session = MagicMock()
                    result, result_usage = await call_llm(
                        messages=[{"role": "user", "content": "test"}],
                        response_model=SimpleOutput,
                        db_session=mock_session,
                    )

        assert result.value == "fresh"

    @pytest.mark.asyncio
    async def test_fallback_model_on_primary_failure(self):
        from src.llm import call_llm

        raw_response = json.dumps({"value": "fallback_result", "score": 0.6})
        usage = TokenUsage(total_tokens=80)
        call_count = 0

        async def mock_retry(messages, model, temperature):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None, TokenUsage()  # primario falla
            return raw_response, usage  # fallback exito

        with patch("src.llm._get_cache", new_callable=AsyncMock) as mock_get_cache:
            mock_get_cache.return_value = (
                AsyncMock(return_value=None),
                AsyncMock(),
            )
            with patch("src.llm._call_with_retry", side_effect=mock_retry):
                with patch("src.llm.get_settings") as mock_settings:
                    settings = MagicMock()
                    settings.fallback_model = "gpt-4o-mini"
                    settings.default_model = "gpt-4o"
                    mock_settings.return_value = settings

                    result, _ = await call_llm(
                        messages=[{"role": "user", "content": "test"}],
                        response_model=SimpleOutput,
                        db_session=None,
                        use_cache=False,
                    )

        assert call_count == 2
        assert result.value == "fallback_result"

    @pytest.mark.asyncio
    async def test_raises_llm_error_when_all_fail(self):
        from src.llm import call_llm

        with patch("src.llm._get_cache", new_callable=AsyncMock) as mock_get_cache:
            mock_get_cache.return_value = (AsyncMock(return_value=None), AsyncMock())
            with patch("src.llm._call_with_retry", new_callable=AsyncMock) as mock_retry:
                mock_retry.return_value = (None, TokenUsage())  # siempre falla
                with patch("src.llm.get_settings") as mock_settings:
                    settings = MagicMock()
                    settings.fallback_model = "gpt-4o-mini"
                    settings.default_model = "gpt-4o"
                    settings.max_retries = 1
                    mock_settings.return_value = settings

                    with pytest.raises(LLMError):
                        await call_llm(
                            messages=[{"role": "user", "content": "test"}],
                            response_model=SimpleOutput,
                            db_session=None,
                            use_cache=False,
                        )
