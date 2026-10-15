"""Session presence roster (PRD 5.1, F2).

In-memory like the F1 event store: presence is session-scoped and
P2 excludes long-term storage. One real event per actual transition;
a lazy timeout sweep (no threads) runs on every read/write path.
"""

from __future__ import annotations

import threading
import uuid

from backend.app.events.store import EventStore
from backend.app.events.store import event_store as _event_store

from .models import (
    Participant,
    normalize_display_name,
    utcnow,
)

SESSION_SCOPE = "session"
PARTICIPANT_TIMEOUT_SECONDS = 60.0


class ParticipantNotFoundError(KeyError):
    pass


class ParticipantGoneError(ValueError):
    def __init__(self, participant_id: str, status: str) -> None:
        super().__init__(f"participant {participant_id} is {status}; rejoin to return")
        self.participant_id = participant_id
        self.status = status


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class ParticipantsController:
    """Id-keyed roster; duplicate display names stay distinct records."""

    def __init__(
        self, store: EventStore, timeout_seconds: float = PARTICIPANT_TIMEOUT_SECONDS
    ) -> None:
        self._store = store
        self._timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._participants: dict[str, Participant] = {}

    # -- queries ---------------------------------------------------------
    def get(self, participant_id: str) -> Participant:
        with self._lock:
            try:
                return self._participants[participant_id]
            except KeyError:
                raise ParticipantNotFoundError(participant_id) from None

    def roster(self) -> list[Participant]:
        self.sweep_timeouts()
        with self._lock:
            return [p for p in self._participants.values() if p.status == "connected"]

    def count(self) -> int:
        return len(self.roster())

    def clear(self) -> None:
        """Test helper: drops all participants (event log cleared separately)."""
        with self._lock:
            self._participants.clear()

    # -- transitions -----------------------------------------------------
    def join(self, display_name: str | None) -> Participant:
        name = normalize_display_name(display_name)  # ValueError on invalid
        now = utcnow()
        self.sweep_timeouts()
        participant = Participant(
            id=_new_id(),
            display_name=name,
            anonymous=name is None,
            status="connected",
            joined_at=now,
            last_seen_at=now,
        )
        with self._lock:
            self._participants[participant.id] = participant
            live = self._live_count_locked()
        self._store.append(
            "participant_joined",
            SESSION_SCOPE,
            {
                "participant_id": participant.id,
                "display_name": participant.display_name,
                "anonymous": participant.anonymous,
                "count": live,
            },
        )
        return participant

    def heartbeat(self, participant_id: str) -> Participant:
        participant = self.get(participant_id)
        if participant.status != "connected":
            raise ParticipantGoneError(participant_id, participant.status)
        with self._lock:
            participant.last_seen_at = utcnow()
        return participant

    def leave(self, participant_id: str) -> Participant:
        participant = self.get(participant_id)
        with self._lock:
            if participant.status == "left":
                return participant
            was_connected = participant.status == "connected"
            participant.status = "left"
            participant.last_seen_at = utcnow()
            live = self._live_count_locked()
        if was_connected:
            self._store.append(
                "participant_left",
                SESSION_SCOPE,
                {"participant_id": participant.id, "reason": "left", "count": live},
            )
        return participant

    def rejoin(self, participant_id: str) -> Participant:
        participant = self.get(participant_id)
        with self._lock:
            if participant.status == "connected":
                return participant
            participant.status = "connected"
            participant.last_seen_at = utcnow()
            live = self._live_count_locked()
        self._store.append(
            "participant_joined",
            SESSION_SCOPE,
            {
                "participant_id": participant.id,
                "display_name": participant.display_name,
                "anonymous": participant.anonymous,
                "count": live,
            },
        )
        return participant

    def sweep_timeouts(self) -> list[Participant]:
        """Demote stale connected records; one event per demotion."""
        now = utcnow()
        newly: list[Participant] = []
        with self._lock:
            for participant in self._participants.values():
                if participant.status != "connected":
                    continue
                idle = (now - participant.last_seen_at).total_seconds()
                if idle >= self._timeout_seconds:
                    participant.status = "timed_out"
                    participant.last_seen_at = now
                    newly.append(participant)
            live = self._live_count_locked()
        for participant in newly:
            self._store.append(
                "participant_left",
                SESSION_SCOPE,
                {"participant_id": participant.id, "reason": "timeout", "count": live},
            )
        return newly

    # -- internals --------------------------------------------------------
    def _live_count_locked(self) -> int:
        return sum(1 for p in self._participants.values() if p.status == "connected")


controller = ParticipantsController(_event_store)


def get_participants_controller() -> ParticipantsController:
    return controller
