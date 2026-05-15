"""
FastAPI app factory con lifespan (init/close DB) y montaje de archivos estaticos.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import router
from src.api.websocket import ws_router

logger = structlog.get_logger(__name__)

DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la DB al arrancar y la cierra al terminar."""
    from src.db.connection import close_db, init_db
    from src.observability import configure_logging

    configure_logging()
    await init_db()
    logger.info("server_ready")
    yield
    await close_db()
    logger.info("server_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Zebra Multi-Agent System",
        description="API REST + WebSocket para el sistema multi-agente Zebra",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # CORS para desarrollo con Vite en :5173
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API REST + WebSocket
    app.include_router(router)
    app.include_router(ws_router)

    # Servir frontend (solo si existe el build de produccion)
    if DIST.exists():
        assets_dir = DIST / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str):
            index = DIST / "index.html"
            return FileResponse(str(index))

    return app
