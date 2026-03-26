"""
Configuracion centralizada del sistema via variables de entorno.
Usar pydantic-settings para validacion y carga automatica desde .env.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Permite a run.py sobreescribir el proveedor/modelo elegido interactivamente
_provider_override: str | None = None
_model_override: str | None = None


def set_provider_override(provider: str, model: str) -> None:
    """Establece el proveedor y modelo elegidos por el usuario en la CLI."""
    global _provider_override, _model_override
    _provider_override = provider
    _model_override = model


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM Providers ---
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    default_provider: Literal["openai", "anthropic", "gemini"] = "openai"
    default_model: str = "gpt-4o"
    fallback_model: str = "gpt-4o-mini"

    # --- Base de datos ---
    database_url: str = "postgresql+asyncpg://zebra:zebra_secret@localhost:5432/zebra_agents"

    # --- Control de flujo ---
    review_confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    max_revisions: int = Field(default=2, ge=0)
    max_retries: int = Field(default=3, ge=1)
    retry_min_wait: float = 1.0
    retry_max_wait: float = 10.0

    # --- Observabilidad ---
    log_level: str = "INFO"

    def _is_real_key(self, key: str) -> bool:
        """Devuelve True si la key parece real (no un placeholder del .env.example)."""
        return bool(key) and "your" not in key.lower() and len(key) >= 10

    @property
    def has_openai(self) -> bool:
        return self._is_real_key(self.openai_api_key)

    @property
    def has_anthropic(self) -> bool:
        return self._is_real_key(self.anthropic_api_key)

    # Modelos por defecto cuando el usuario no configuro uno compatible
    _DEFAULT_MODELS: dict[str, tuple[str, str]] = {
        "openai":    ("gpt-4o",              "gpt-4o-mini"),
        "anthropic": ("claude-sonnet-4-6",   "claude-haiku-4-5-20251001"),
        "gemini":    ("gemini-2.0-flash",    "gemini-1.5-flash"),
    }

    @property
    def has_gemini(self) -> bool:
        return self._is_real_key(self.gemini_api_key)

    @property
    def available_providers(self) -> list[str]:
        """Lista de proveedores con API key real configurada."""
        providers = []
        if self.has_openai:
            providers.append("openai")
        if self.has_anthropic:
            providers.append("anthropic")
        if self.has_gemini:
            providers.append("gemini")
        return providers

    @property
    def active_provider(self) -> str:
        """Devuelve el proveedor activo segun las claves disponibles."""
        # Override del usuario via CLI (tiene maxima prioridad)
        if _provider_override:
            return _provider_override
        if self.default_provider == "openai" and self.has_openai:
            return "openai"
        if self.default_provider == "anthropic" and self.has_anthropic:
            return "anthropic"
        if self.default_provider == "gemini" and self.has_gemini:
            return "gemini"
        # Fallback automatico: usar el primer provider con key real
        available = self.available_providers
        if available:
            return available[0]
        raise ValueError(
            "No se encontro ninguna API key valida. "
            "Configura OPENAI_API_KEY, ANTHROPIC_API_KEY o GEMINI_API_KEY en el archivo .env"
        )

    def _is_model_compatible(self, model: str, provider: str) -> bool:
        """Devuelve True si el modelo parece compatible con el proveedor."""
        openai_prefixes = ("gpt-", "o1", "o3", "o4")
        anthropic_prefixes = ("claude-",)
        gemini_prefixes = ("gemini-",)
        if provider == "openai":
            return any(model.startswith(p) for p in openai_prefixes)
        if provider == "anthropic":
            return any(model.startswith(p) for p in anthropic_prefixes)
        if provider == "gemini":
            return any(model.startswith(p) for p in gemini_prefixes)
        return False

    @property
    def active_model(self) -> str:
        """Modelo compatible con el proveedor activo."""
        # Override del usuario via CLI
        if _model_override:
            return _model_override
        provider = self.active_provider
        if self._is_model_compatible(self.default_model, provider):
            return self.default_model
        return self._DEFAULT_MODELS[provider][0]

    @property
    def active_fallback_model(self) -> str:
        """Modelo de fallback compatible con el proveedor activo."""
        provider = self.active_provider
        if self._is_model_compatible(self.fallback_model, provider):
            return self.fallback_model
        return self._DEFAULT_MODELS[provider][1]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton de configuracion. Se carga una sola vez."""
    return Settings()
