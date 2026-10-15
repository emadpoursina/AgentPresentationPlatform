"""Scaffold FastAPI entrypoint. No mission/agent/business logic here.

Feature cards add: mission routes, polls/votes, SSE/WebSocket event stream,
QR join URL, presenter controls, Telegram Q&A fallback.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parents[3] / "frontend" / "static"

app = FastAPI(title="Live Agent Playground", version="0.1.0")


@app.get("/api/health", response_class=JSONResponse)
def health() -> dict[str, str]:
    return {"status": "ok"}


if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
