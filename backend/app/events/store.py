"""In-memory event store with SSE-friendly replay.

F1 scope is a local single-process demo (P2 explicitly excludes long-term
storage), so persistence is an in-memory append-only log guarded by a
threading lock. The SSE endpoint replays via `after_id` (Last-Event-ID)
and then polls for new rows, which keeps reconnect logic trivial and
lossless for brief network interruptions.

Future slices (F3 polls, F5 agents) append to the same store; no API
change is needed. A SQLite backing can replace `_events` later without
touching callers.
"""

from __future__ import annotations

import threading
from typing import Any

from .models import utcnow


class EventStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[dict] = []
        self._seq = 0

    def append(self, type: str, mission_id: str, data: dict[str, Any] | None = None) -> dict:
        """Append an event and return its serialised dict."""
        # Import here to avoid circulars; validation lives in the model.
        from .models import EVENT_TYPES, ActivityEvent

        if type not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {type!r}")
        safe_data = dict(data or {})
        with self._lock:
            self._seq += 1
            event = ActivityEvent(
                id=self._seq,
                type=type,
                mission_id=mission_id,
                timestamp=utcnow(),
                data=safe_data,
            )
            payload = event.model_dump(mode="json")
            self._events.append(payload)
            return payload

    def list(
        self,
        mission_id: str | None = None,
        after_id: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        with self._lock:
            rows = list(self._events)
        out = [e for e in rows if e["id"] > after_id]
        if mission_id is not None:
            out = [e for e in out if e["mission_id"] == mission_id]
        return out[: max(1, min(limit, 500))]

    def last_id(self) -> int:
        with self._lock:
            return self._seq

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._seq = 0


# Process-wide singleton used by the controller and API routes.
event_store = EventStore()
