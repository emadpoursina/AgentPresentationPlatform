"""FastAPI entrypoint: health, mission controller (F1), event stream, static UI."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.events import router as events_router
from backend.app.api.missions import router as missions_router

STATIC_DIR = Path(__file__).resolve().parents[2] / "frontend" / "static"

app = FastAPI(title="Live Agent Playground", version="0.1.0")

app.include_router(missions_router)
app.include_router(events_router)


@app.get("/api/health", response_class=JSONResponse)
def health() -> dict[str, str]:
    return {"status": "ok"}


if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
