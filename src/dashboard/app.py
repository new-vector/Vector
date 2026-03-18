"""
app.py — FastAPI dashboard server.

Serves the real-time monitoring dashboard and provides WebSocket
endpoints for live strategy state updates.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Brinks Box Dashboard", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Connected WebSocket clients
_clients: set[WebSocket] = set()

# Latest engine state (updated by the engine)
_state: dict[str, Any] = {}


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    _clients.add(websocket)
    log.info("Dashboard client connected (%d total)", len(_clients))

    # Send current state immediately
    if _state:
        await websocket.send_json(_state)

    try:
        while True:
            # Keep connection alive; client can send ping
            await websocket.receive_text()
    except WebSocketDisconnect:
        _clients.discard(websocket)
        log.info("Dashboard client disconnected (%d remaining)", len(_clients))


async def broadcast(data: dict[str, Any]) -> None:
    """Broadcast state update to all connected dashboard clients."""
    global _state
    _state = data
    dead: set[WebSocket] = set()
    for ws in _clients:
        try:
            await ws.send_json(data)
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)


def run_dashboard(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Start the dashboard server (blocking)."""
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")
