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


async def list_openai_models() -> list[str]:
    """
    Consulta la API de OpenAI y devuelve los modelos de chat disponibles,
    excluyendo embeddings, DALL-E, TTS, Whisper, fine-tuned y snapshots deprecados.
    """
    _CHAT_PREFIXES = ("gpt-4o", "gpt-4-turbo", "o1", "o3", "o4")
    _EXCLUDE_PATTERNS = {"audio", "realtime", "tts", "transcribe", "search", "diarize"}
    _EXCLUDE_EXACT = {
        "gpt-4-0314", "gpt-4-0613",
        "gpt-4-32k", "gpt-4-32k-0314", "gpt-4-32k-0613",
    }

    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.models.list()
    models = []
    for m in response.data:
        model_id = m.id
        if "ft:" in model_id or model_id.startswith("ft-"):
            continue
        if not any(model_id.startswith(p) for p in _CHAT_PREFIXES):
            continue
        if model_id in _EXCLUDE_EXACT:
            continue
        if model_id.endswith("-instruct"):
            continue
        if any(p in model_id for p in _EXCLUDE_PATTERNS):
            continue
        models.append(model_id)
    return sorted(set(models))


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


async def list_gemini_models() -> list[str]:
    """
    Consulta la API de Gemini y devuelve los modelos de texto disponibles,
    excluyendo modelos deprecados y especializados (TTS, imagen, robótica, etc.).
    """
    # Patrones que identifican modelos no-texto o no aptos para generateContent general
    _EXCLUDE_PATTERNS = {"tts", "image", "robotics", "computer-use", "customtools"}
    # Prefijos deprecados para nuevos usuarios (dan 404)
    _DEPRECATED_PREFIXES = ("gemini-2.0-", "gemini-1.5-", "gemini-1.0-")

    settings = get_settings()
    client = google_genai.Client(api_key=settings.gemini_api_key)
    models = []
    async for m in await client.aio.models.list():
        name = m.name  # formato: "models/gemini-..."
        if "gemini" not in name:
            continue
        # Excluir modelos deprecados si el API expone lifecycle_state
        lifecycle = getattr(m, "lifecycle_state", None)
        if lifecycle and str(lifecycle).upper() in ("DEPRECATED", "SCHEDULED_FOR_DEPRECATION"):
            continue
        # Solo incluir modelos que soporten generateContent
        supported = getattr(m, "supported_actions", None)
        if supported is not None and "generateContent" not in supported:
            continue
        short_name = name.replace("models/", "")
        # Excluir modelos deprecados para nuevos usuarios
        if short_name.startswith(_DEPRECATED_PREFIXES):
            continue
        # Excluir modelos especializados (TTS, imagen, robótica, etc.)
        if any(p in short_name for p in _EXCLUDE_PATTERNS):
            continue
        models.append(short_name)
    return sorted(set(models))


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


def _build_example_from_schema(schema: dict) -> dict:
    """Genera un ejemplo concreto de JSON a partir del JSON schema de Pydantic."""
    defs = schema.get("$defs", {})

    def _resolve(prop: dict) -> object:
        if "$ref" in prop:
            ref_name = prop["$ref"].split("/")[-1]
            return _resolve(defs.get(ref_name, {}))
        if "allOf" in prop:
            for item in prop["allOf"]:
                resolved = _resolve(item)
                if resolved is not None:
                    return resolved
            return {}
        if "anyOf" in prop:
            for item in prop["anyOf"]:
                if item.get("type") != "null":
                    return _resolve(item)
            return None
        t = prop.get("type", "string")
        if t == "object":
            props = prop.get("properties", {})
            return {k: _resolve(v) for k, v in props.items()}
        if t == "array":
            items = prop.get("items", {})
            return [_resolve(items)]
        if t == "string":
            if "enum" in prop:
                return prop["enum"][0]
            return "..."
        if t == "integer":
            return 0
        if t == "number":
            return 0.0
        if t == "boolean":
            return True
        return "..."

    props = schema.get("properties", {})
    return {k: _resolve(v) for k, v in props.items()}


def _inject_schema(messages: list[dict], response_model: type) -> list[dict]:
    """Añade un ejemplo JSON concreto al mensaje de sistema para guiar al LLM."""
    schema = response_model.model_json_schema()
    example = _build_example_from_schema(schema)
    example_json = json.dumps(example, indent=2, ensure_ascii=False)

    enriched = [m.copy() for m in messages]
    instruction = (
        "\n\nIMPORTANTE: Tu respuesta DEBE ser ÚNICAMENTE un objeto JSON válido "
        "(sin texto, sin markdown, sin explicaciones) con EXACTAMENTE esta estructura. "
        "Rellena los valores con contenido real:\n"
        f"{example_json}"
    )
    for msg in enriched:
        if msg["role"] == "system":
            msg["content"] += instruction
            return enriched
    enriched.insert(0, {"role": "system", "content": instruction.strip()})
    return enriched


def _try_wrap_list(data: list, response_model: type[T]) -> dict | list:
    """
    Si el LLM devolvió una lista en vez de un dict, intenta envolverla
    en el campo lista del modelo (cuando hay exactamente 1 campo de tipo array).
    """
    schema = response_model.model_json_schema()
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    list_fields = [k for k, v in props.items() if v.get("type") == "array"]
    if len(list_fields) != 1:
        return data  # ambiguo, devolver sin cambios
    field = list_fields[0]
    wrapped: dict = {field: data}
    # Rellenar campos requeridos faltantes con defaults seguros
    type_defaults = {"string": "", "number": 0.0, "integer": 0, "boolean": False, "array": []}
    for k, v in props.items():
        if k != field and k in required:
            wrapped.setdefault(k, type_defaults.get(v.get("type", ""), ""))
    return wrapped


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
    enriched = _inject_schema(messages, response_model)
    raw_content, usage = await _call_with_retry(enriched, active_model, temperature)

    # --- 3. Fallback si el primario fallo ---
    if raw_content is None:
        fallback = settings.active_fallback_model
        logger.warning("llm_primary_failed_trying_fallback", fallback=fallback)
        raw_content, usage = await _call_with_retry(enriched, fallback, temperature)
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
    except json.JSONDecodeError as e:
        raise LLMParseError(f"El LLM devolvio JSON invalido: {e}\nRespuesta: {raw[:200]}")

    # Normalización defensiva: si el LLM devolvió una lista en vez de dict, intentar envolver
    if isinstance(data, list):
        data = _try_wrap_list(data, response_model)

    try:
        return response_model.model_validate(data)
    except ValidationError as e:
        raise LLMParseError(
            f"La respuesta del LLM no cumple el schema {response_model.__name__}: {e}"
        )
