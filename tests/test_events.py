"""F1: event model shape + history + SSE replay (acceptance #8)."""

import json

from fastapi.testclient import TestClient

from backend.app.events import EVENT_TYPES
from backend.app.main import app


def _fresh_client():
    from backend.app.events.store import event_store
    from backend.app.missions.controller import controller

    controller.clear()
    event_store.clear()
    return TestClient(app)


def test_canonical_types_present() -> None:
    for name in [
        "mission_started",
        "poll_opened",
        "vote_recorded",
        "audience_decision_applied",
        "agent_started",
        "tool_started",
        "tool_completed",
        "agent_handoff",
        "agent_completed",
        "agent_failed",
        "mission_completed",
    ]:
        assert name in EVENT_TYPES


def test_event_shape_has_timestamp_mission_id_type_metadata() -> None:
    client = _fresh_client()
    mid = client.post("/api/missions", json={"title": "Shape"}).json()["id"]
    client.post(f"/api/missions/{mid}/start")
    history = client.get(f"/api/missions/{mid}/events").json()
    assert history["mission_id"] == mid
    assert len(history["events"]) >= 1
    ev = history["events"][0]
    assert ev["mission_id"] == mid
    assert ev["type"] in EVENT_TYPES
    assert "timestamp" in ev and ev["timestamp"]
    assert "data" in ev and isinstance(ev["data"], dict)
    assert ev["id"] >= 1


def test_dashboard_reflects_real_events_acceptance_13_8() -> None:
    client = _fresh_client()
    mid = client.post("/api/missions", json={"title": "Dash"}).json()["id"]
    client.post(f"/api/missions/{mid}/start")
    client.post(f"/api/missions/{mid}/pause")
    history = client.get(f"/api/missions/{mid}/events").json()
    types = [e["type"] for e in history["events"]]
    assert types == sorted(types, key=lambda e: history["events"][types.index(e)]["id"])
    assert "mission_started" in types
    assert "mission_paused" in types
    # ids strictly increasing
    ids = [e["id"] for e in history["events"]]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)


def test_sse_stream_replays_and_tails() -> None:
    import asyncio

    from backend.app.api.events import _stream_gen

    client = _fresh_client()
    mid = client.post("/api/missions", json={"title": "SSE"}).json()["id"]
    client.post(f"/api/missions/{mid}/start")
    first_id = client.get(f"/api/missions/{mid}/events").json()["events"][0]["id"]

    class _Req:
        def __init__(self, disconnect_after: int = 2) -> None:
            self.calls = 0
            self.disconnect_after = disconnect_after

        async def is_disconnected(self) -> bool:
            self.calls += 1
            return self.calls > self.disconnect_after

    async def _collect(mission_id: str | None, start_after: int, limit_chunks: int = 10):
        chunks: list[str] = []
        async for chunk in _stream_gen(_Req(), mission_id, start_after):  # type: ignore[arg-type]
            chunks.append(chunk)
            if len(chunks) >= limit_chunks:
                break
        return "".join(chunks)

    body = asyncio.run(_collect(mid, 0))
    assert "retry: 3000" in body
    assert "mission_started" in body

    # Targeted replay: after first_id-1 includes first event, after first_id excludes it.
    h_all = client.get(f"/api/missions/{mid}/events?after_id={first_id - 1}").json()
    assert any(e["id"] == first_id for e in h_all["events"])
    h_next = client.get(f"/api/missions/{mid}/events?after_id={first_id}").json()
    assert all(e["id"] > first_id for e in h_next["events"])


def test_sse_format_contains_retry_id_event_data() -> None:
    from backend.app.api.events import _format_sse

    ev = {
        "id": 7,
        "type": "mission_started",
        "mission_id": "abc",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "data": {"title": "x"},
    }
    sse = _format_sse(ev)
    assert "id: 7" in sse
    assert "event: mission_started" in sse
    assert "data: " in sse
    payload = json.loads([ln for ln in sse.splitlines() if ln.startswith("data: ")][0][6:])
    assert payload["mission_id"] == "abc"
