"""
Gestion de la conexion a PostgreSQL con SQLAlchemy async.

Exporta:
- get_engine(): engine SQLAlchemy async (singleton)
- get_session(): async context manager que provee una sesion
- init_db(): crea todas las tablas si no existen
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import get_settings

logger = structlog.get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def get_session_factory() -> async_sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager que provee una sesion de DB con commit/rollback automatico."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Crea todas las tablas y aplica índices incrementales si no existen."""
    from src.db.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Índices en FKs y created_at (seguros de ejecutar múltiples veces)
        for stmt in [
            "CREATE INDEX IF NOT EXISTS ix_agent_traces_execution_id ON agent_traces (execution_id)",
            "CREATE INDEX IF NOT EXISTS ix_review_history_execution_id ON review_history (execution_id)",
            "CREATE INDEX IF NOT EXISTS ix_errors_execution_id ON errors (execution_id)",
            "CREATE INDEX IF NOT EXISTS ix_executions_created_at ON executions (created_at)",
            "CREATE INDEX IF NOT EXISTS ix_llm_cache_created_at ON llm_cache (created_at)",
            "ALTER TABLE llm_cache ALTER COLUMN messages DROP NOT NULL",
        ]:
            await conn.execute(text(stmt))
    logger.info("db_initialized", tables=list(Base.metadata.tables.keys()))


async def close_db() -> None:
    """Cierra el engine de conexion."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
