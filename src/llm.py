"""
Wrapper de llamadas al LLM.

Responsabilidades:
- Consultar cache en PostgreSQL antes de llamar al LLM
- Llamar al proveedor configurado (OpenAI o Anthropic)
- Parsear la respuesta con Pydantic (JSON mode)
- Reintentos con backoff exponencial via tenacity
- Fallback automatico al modelo secundario si el primario falla
- Persistir respuestas nuevas en cache
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel, ValidationError
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import get_settings
from src.models import TokenUsage

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

# Importaciones opcionales de proveedores
try:
    from openai import AsyncOpenAI, APIError as OpenAIError, RateLimitError

    _openai_available = True
except ImportError:
    _openai_available = False

try:
    import anthropic

    _anthropic_available = True
except ImportError:
    _anthropic_available = False

try:
    from google import genai as google_genai
    from google.genai import types as genai_types

    _gemini_available = True
except ImportError:
    _gemini_available = False


class LLMError(Exception):
    """Error irrecuperable al llamar al LLM."""


class LLMParseError(LLMError):
    """El LLM devolvio un JSON que no cumple el schema esperado."""


# ---------------------------------------------------------------------------
# Cache (lazy import para evitar dependencia circular con db)
# ---------------------------------------------------------------------------


async def _get_cache():
    from src.db.cache import get_cached_response, save_to_cache

    return get_cached_response, save_to_cache


# ---------------------------------------------------------------------------
# Llamadas por proveedor
# ---------------------------------------------------------------------------


async def _call_openai(
    messages: list[dict],
    model: str,
    temperature: float,
) -> tuple[str, TokenUsage]:
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content or "{}"
    usage = TokenUsage(
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        total_tokens=response.usage.total_tokens,
    )
    return content, usage


async def _call_anthropic(
    messages: list[dict],
    model: str,
    temperature: float,
) -> tuple[str, TokenUsage]:
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Anthropic usa system separado
    system_msg = ""
    filtered = []
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        else:
            filtered.append(m)

    # Pedir JSON explicito en el system prompt
    system_msg += "\n\nResponde SIEMPRE con un JSON valido y nada mas."

    response = await client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=temperature,
        system=system_msg,
        messages=filtered,
    )

    content = response.content[0].text
    usage = TokenUsage(
        prompt_tokens=response.usage.input_tokens,
        completion_tokens=response.usage.output_tokens,
        total_tokens=response.usage.input_tokens + response.usage.output_tokens,
    )
    return content, usage


async def _call_gemini(
    messages: list[dict],
    model: str,
    temperature: float,
) -> tuple[str, TokenUsage]:
    settings = get_settings()
    client = google_genai.Client(api_key=settings.gemini_api_key)

    # Separar system prompt de los mensajes de conversacion
    system_instruction = None
    contents = []
    for m in messages:
        if m["role"] == "system":
            system_instruction = m["content"]
        elif m["role"] == "user":
            contents.append(genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=m["content"])],
            ))
        elif m["role"] == "assistant":
            contents.append(genai_types.Content(
                role="model",
                parts=[genai_types.Part(text=m["content"])],
            ))

    # Si no hay mensajes de conversacion (solo system), enviar un content vacio de user
    if not contents:
        contents.append(genai_types.Content(
            role="user",
            parts=[genai_types.Part(text="Procede.")],
        ))

    config = genai_types.GenerateContentConfig(
        temperature=temperature,
        response_mime_type="application/json",
        system_instruction=system_instruction,
    )

    response = await client.aio.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )

    content = response.text or "{}"
    meta = response.usage_metadata
    prompt_tokens = meta.prompt_token_count if meta else 0
    completion_tokens = meta.candidates_token_count if meta else 0

    usage = TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    return content, usage


# ---------------------------------------------------------------------------
# Funcion principal
# ---------------------------------------------------------------------------


async def call_llm(
    messages: list[dict[str, str]],
    response_model: type[T],
    model: str | None = None,
    temperature: float = 0.3,
    use_cache: bool = True,
    db_session=None,
) -> tuple[T, TokenUsage]:
    """
    Llama al LLM y devuelve la respuesta parseada con Pydantic.

    Flujo:
    1. Consulta cache (si use_cache=True y hay sesion de DB)
    2. Llama al proveedor primario con reintentos
    3. Si falla, intenta con el modelo fallback
    4. Parsea la respuesta JSON con Pydantic
    5. Guarda en cache si la llamada fue exitosa

    Args:
        messages: Lista de mensajes en formato OpenAI (role/content)
        response_model: Clase Pydantic que define el schema esperado
        model: Modelo a usar (por defecto el configurado en settings)
        temperature: Temperatura del LLM
        use_cache: Si True, consulta y actualiza cache en PostgreSQL
        db_session: Sesion de DB (opcional, necesaria para cache)

    Returns:
        Tupla (respuesta_parseada, token_usage)

    Raises:
        LLMError: Si todos los intentos fallan
        LLMParseError: Si el JSON del LLM no cumple el schema
    """
    settings = get_settings()
    active_model = model or settings.active_model

    # --- 1. Consultar cache ---
    if use_cache and db_session is not None:
        try:
            get_cached, _ = await _get_cache()
            cached = await get_cached(db_session, messages, active_model)
            if cached is not None:
                parsed = response_model.model_validate(cached["response"])
                token_data = {**cached["token_usage"], "cached": True}
                usage = TokenUsage(**token_data)
                logger.info(
                    "llm_cache_hit",
                    model=active_model,
                    response_model=response_model.__name__,
                )
                return parsed, usage
        except Exception as e:
            logger.warning("llm_cache_error", error=str(e))

    # --- 2. Llamar al LLM con reintentos ---
    raw_content, usage = await _call_with_retry(messages, active_model, temperature)

    # --- 3. Fallback si el primario fallo ---
    if raw_content is None:
        fallback = settings.active_fallback_model
        logger.warning("llm_primary_failed_trying_fallback", fallback=fallback)
        raw_content, usage = await _call_with_retry(messages, fallback, temperature)
        if raw_content is None:
            raise LLMError(
                f"El LLM no respondio despues de {settings.max_retries} intentos "
                f"con {active_model} y {fallback}."
            )

    # --- 4. Parsear respuesta ---
    parsed = _parse_response(raw_content, response_model, messages)

    # --- 5. Guardar en cache ---
    if use_cache and db_session is not None:
        try:
            _, save_cache = await _get_cache()
            await save_cache(
                db_session,
                messages,
                active_model,
                parsed.model_dump(),
                usage.model_dump(),
            )
        except Exception as e:
            logger.warning("llm_cache_save_error", error=str(e))

    return parsed, usage


async def _call_with_retry(
    messages: list[dict],
    model: str,
    temperature: float,
) -> tuple[str | None, TokenUsage]:
    """Llama al LLM con reintentos. Devuelve (None, empty_usage) si falla."""
    settings = get_settings()
    provider = settings.active_provider

    exceptions_to_retry = (Exception,)
    if _openai_available:
        exceptions_to_retry = (OpenAIError, RateLimitError, json.JSONDecodeError)

    @retry(
        retry=retry_if_exception_type(exceptions_to_retry),
        stop=stop_after_attempt(settings.max_retries),
        wait=wait_exponential(
            min=settings.retry_min_wait, max=settings.retry_max_wait
        ),
        reraise=False,
    )
    async def _attempt() -> tuple[str, TokenUsage]:
        if provider == "openai":
            return await _call_openai(messages, model, temperature)
        elif provider == "gemini":
            return await _call_gemini(messages, model, temperature)
        else:
            return await _call_anthropic(messages, model, temperature)

    try:
        return await _attempt()
    except (RetryError, Exception) as e:
        logger.error("llm_all_retries_failed", model=model, error=str(e))
        return None, TokenUsage()


def _parse_response(
    raw: str,
    response_model: type[T],
    original_messages: list[dict],
) -> T:
    """Parsea JSON del LLM y valida con Pydantic. Reintenta si el JSON esta malformado."""
    # Limpiar posibles markdown code blocks
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1])

    try:
        data = json.loads(cleaned)
        return response_model.model_validate(data)
    except json.JSONDecodeError as e:
        raise LLMParseError(f"El LLM devolvio JSON invalido: {e}\nRespuesta: {raw[:200]}")
    except ValidationError as e:
        raise LLMParseError(
            f"La respuesta del LLM no cumple el schema {response_model.__name__}: {e}"
        )
