"""
Configuracion centralizada del sistema via variables de entorno.
Usar pydantic-settings para validacion y carga automatica desde .env.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def active_provider(self) -> str:
        """Devuelve el proveedor activo segun las claves disponibles."""
        if self.default_provider == "openai" and self.has_openai:
            return "openai"
        if self.default_provider == "anthropic" and self.has_anthropic:
            return "anthropic"
        if self.default_provider == "gemini" and self.has_gemini:
            return "gemini"
        # Fallback automatico si el proveedor primario no tiene key
        if self.has_openai:
            return "openai"
        if self.has_anthropic:
            return "anthropic"
        if self.has_gemini:
            return "gemini"
        raise ValueError(
            "No se encontro ninguna API key configurada. "
            "Configura OPENAI_API_KEY, ANTHROPIC_API_KEY o GEMINI_API_KEY en el archivo .env"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton de configuracion. Se carga una sola vez."""
    return Settings()
