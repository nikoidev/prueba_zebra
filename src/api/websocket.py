"""
WebSocket endpoint para ejecutar el pipeline con progreso en tiempo real.

Protocolo:
  Cliente -> Servidor: {"request": "...", "provider": "openai", "model": "gpt-4o"}
  Servidor -> Cliente (progreso): {"type": "progress", "state": "...", "agent_name": "...", ...}
  Servidor -> Cliente (completado): {"type": "complete", "result": {...}}
  Servidor -> Cliente (error): {"type": "error", "message": "..."}
"""
from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.config import set_provider_override
from src.db.connection import get_session_factory

logger = structlog.get_logger(__name__)

ws_router = APIRouter()


@ws_router.websocket("/api/ws/execute")
async def ws_execute(websocket: WebSocket):
    await websocket.accept()
    db_session = None
    db_ctx = None

    try:
        # 1. Leer configuracion del cliente
        data = await websocket.receive_json()
        request = data.get("request", "").strip()
        provider = data.get("provider", "")
        model = data.get("model", "")

        if not request:
            await websocket.send_json({"type": "error", "message": "Request vacio"})
            return

        # 2. Configurar provider/modelo
        set_provider_override(provider, model)

        # 3. Abrir sesion de DB
        factory = get_session_factory()
        db_ctx = factory()
        db_session = await db_ctx.__aenter__()

        # 4. Limpieza de DB al iniciar (opcional, no bloquea)
        try:
            from src.db.cache import cleanup_expired_cache
            from src.db.repository import cleanup_old_executions
            await cleanup_expired_cache(db_session)
            await cleanup_old_executions(db_session)
            await db_session.commit()
        except Exception:
            pass

        # 5. Callback de progreso: envia mensajes WS tras cada agente
        async def progress_callback(state, agent_name, last_trace, context):
            msg = {
                "type": "progress",
                "state": state,
                "agent_name": agent_name,
                "revision_count": context.revision_count,
                "traces_so_far": len(context.traces),
            }
            if last_trace is not None:
                msg["duration_ms"] = round(last_trace.duration_ms, 1)
                msg["tokens"] = last_trace.token_usage.total_tokens
                msg["from_cache"] = last_trace.token_usage.cached
                msg["model_used"] = last_trace.model_used
            try:
                await websocket.send_json(msg)
            except Exception:
                pass  # WebSocket puede haberse cerrado

        # 6. Ejecutar pipeline
        from src.orchestrator import run
        result = await run(
            request=request,
            db_session=db_session,
            verbose=False,
            progress_callback=progress_callback,
        )

        # 7. Enviar resultado completo
        await websocket.send_json({
            "type": "complete",
            "result": result.model_dump(mode="json"),
        })

    except WebSocketDisconnect:
        logger.info("ws_client_disconnected")
    except Exception as e:
        logger.error("ws_pipeline_error", error=str(e))
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        if db_ctx is not None and db_session is not None:
            try:
                await db_ctx.__aexit__(None, None, None)
            except Exception:
                pass
