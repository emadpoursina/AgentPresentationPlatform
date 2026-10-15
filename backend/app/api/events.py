"""Event history (JSON) + SSE stream (PRD 10 real-time updates).

- `GET /api/missions/{id}/events` → JSON history for initial render.
- `GET /api/missions/{id}/events/stream` → SSE, replays missed rows via
  Last-Event-ID header or `?lastEventId=`, then tails live rows.
- `GET /api/events/stream` → global tail (optional `?mission_id=`).

The client shows a disconnected banner instead of stale state; EventSource
reconnects with `retry: 3000` and the server replays from Last-Event-ID.
"""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.app.events.store import event_store
from backend.app.missions.controller import MissionNotFoundError, get_controller

router = APIRouter(tags=["events"])


class EventHistory(BaseModel):
    mission_id: str | None = None
    events: list[dict]
    last_id: int


def _require_mission(mission_id: str) -> None:
    try:
        get_controller().get(mission_id)
    except MissionNotFoundError:
        raise HTTPException(status_code=404, detail="mission not found") from None


@router.get("/api/missions/{mission_id}/events", response_model=EventHistory)
def mission_event_history(
    mission_id: str,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> EventHistory:
    _require_mission(mission_id)
    events = event_store.list(mission_id=mission_id, after_id=after_id, limit=limit)
    return EventHistory(mission_id=mission_id, events=events, last_id=event_store.last_id())


@router.get("/api/events/history", response_model=EventHistory)
def global_event_history(
    mission_id: str | None = Query(default=None),
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> EventHistory:
    events = event_store.list(mission_id=mission_id, after_id=after_id, limit=limit)
    return EventHistory(mission_id=mission_id, events=events, last_id=event_store.last_id())


def _last_event_id(request: Request, explicit: int | None) -> int:
    if explicit is not None:
        return explicit
    raw = request.headers.get("last-event-id")
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _format_sse(event: dict) -> str:
    data = json.dumps(event, separators=(",", ":"))
    return f"id: {event['id']}\nevent: {event['type']}\ndata: {data}\n\n"


async def _stream_gen(
    request: Request,
    mission_id: str | None,
    start_after: int,
) -> AsyncIterator[str]:
    yield "retry: 3000\n\n"
    last_id = start_after
    # Replay missed rows first so reconnects are lossless.
    for event in event_store.list(mission_id=mission_id, after_id=last_id, limit=500):
        last_id = max(last_id, int(event["id"]))
        yield _format_sse(event)
    heartbeat = 0
    while True:
        if await request.is_disconnected():
            break
        rows = event_store.list(mission_id=mission_id, after_id=last_id, limit=100)
        for event in rows:
            last_id = max(last_id, int(event["id"]))
            yield _format_sse(event)
        heartbeat += 1
        if not rows and heartbeat % 30 == 0:
            # ~15s comment heartbeat keeps proxies/NATs from idling out.
            yield ": ping\n\n"
        await asyncio.sleep(0.5)


def _sse_response(gen: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/missions/{mission_id}/events/stream")
async def mission_event_stream(
    mission_id: str,
    request: Request,
    lastEventId: int | None = Query(default=None, ge=0),  # noqa: N803 – SSE convention
) -> StreamingResponse:
    _require_mission(mission_id)
    start_after = _last_event_id(request, lastEventId)
    return _sse_response(_stream_gen(request, mission_id, start_after))


@router.get("/api/events/stream")
async def global_event_stream(
    request: Request,
    mission_id: str | None = Query(default=None),
    lastEventId: int | None = Query(default=None, ge=0),  # noqa: N803 – SSE convention
) -> StreamingResponse:
    start_after = _last_event_id(request, lastEventId)
    return _sse_response(_stream_gen(request, mission_id, start_after))
