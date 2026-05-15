#!/usr/bin/env python3
"""
Entry point del servidor web Zebra.

Uso:
    python server.py                    # Produccion: sirve API + frontend/dist/
    uvicorn server:app --reload         # Desarrollo con hot-reload
"""
import uvicorn
from src.api.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
