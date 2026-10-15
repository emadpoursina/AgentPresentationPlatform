"""Thin mission coordinator (PRD 4C). Not a second agent framework.

Owns predefined workflow state, allowed transitions, and event emission.
Hermes remains responsible for agent execution (F5); audience voting
arrives in F3 and will call into `apply_decision` hooks here without
changing this state machine.
"""

from __future__ import annotations

import threading
import uuid

from backend.app.events.store import EventStore
from backend.app.events.store import event_store as _event_store

from .models import (
    CompleteMissionRequest,
    CreateMissionRequest,
    FailMissionRequest,
    Mission,
    MissionStatus,
    MissionStep,
    default_steps,
    utcnow,
)


class MissionNotFoundError(KeyError):
    pass


class InvalidTransitionError(ValueError):
    def __init__(self, mission_id: str, action: str, status: MissionStatus) -> None:
        super().__init__(f"cannot {action} mission {mission_id} while {status.value}")
        self.mission_id = mission_id
        self.action = action
        self.status = status


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class MissionController:
    """In-memory coordinator; single active mission at a time (serial)."""

    def __init__(self, store: EventStore) -> None:
        self._store = store
        self._lock = threading.Lock()
        self._missions: dict[str, Mission] = {}

    # -- queries ---------------------------------------------------------
    def list(self) -> list[Mission]:
        with self._lock:
            return list(self._missions.values())

    def get(self, mission_id: str) -> Mission:
        with self._lock:
            try:
                return self._missions[mission_id]
            except KeyError:
                raise MissionNotFoundError(mission_id) from None

    def clear(self) -> None:
        """Test/reset helper: drops all missions (event log cleared separately)."""
        with self._lock:
            self._missions.clear()

    # -- lifecycle --------------------------------------------------------
    def create(self, req: CreateMissionRequest) -> Mission:
        now = utcnow()
        steps: list[MissionStep] = req.steps if req.steps is not None else default_steps()
        if not steps:
            steps = default_steps()
        mission = Mission(
            id=_new_id(),
            title=req.title,
            status=MissionStatus.CREATED,
            steps=steps,
            current_step_index=0,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._missions[mission.id] = mission
        self._store.append(
            "mission_created",
            mission.id,
            {"title": mission.title, "steps": [s.id for s in mission.steps]},
        )
        return mission

    def start(self, mission_id: str) -> Mission:
        mission = self.get(mission_id)
        if mission.status is not MissionStatus.CREATED:
            raise InvalidTransitionError(mission_id, "start", mission.status)
        return self._transition(
            mission, MissionStatus.RUNNING, "mission_started", {"title": mission.title}
        )

    def pause(self, mission_id: str) -> Mission:
        mission = self.get(mission_id)
        if mission.status is not MissionStatus.RUNNING:
            raise InvalidTransitionError(mission_id, "pause", mission.status)
        return self._transition(mission, MissionStatus.PAUSED, "mission_paused", {})

    def resume(self, mission_id: str) -> Mission:
        mission = self.get(mission_id)
        if mission.status is not MissionStatus.PAUSED:
            raise InvalidTransitionError(mission_id, "resume", mission.status)
        return self._transition(mission, MissionStatus.RUNNING, "mission_resumed", {})

    def complete(self, mission_id: str, req: CompleteMissionRequest) -> Mission:
        mission = self.get(mission_id)
        if mission.status not in (MissionStatus.RUNNING, MissionStatus.PAUSED):
            raise InvalidTransitionError(mission_id, "complete", mission.status)
        with self._lock:
            mission.status = MissionStatus.COMPLETED
            mission.result_summary = req.summary or None
            mission.outcome = req.outcome
            mission.error = None
            mission.current_step_index = len(mission.steps)
            mission.updated_at = utcnow()
        self._store.append(
            "mission_completed",
            mission.id,
            {"summary": req.summary, "outcome": req.outcome},
        )
        return mission

    def fail(self, mission_id: str, req: FailMissionRequest) -> Mission:
        mission = self.get(mission_id)
        if mission.status not in (MissionStatus.RUNNING, MissionStatus.PAUSED):
            raise InvalidTransitionError(mission_id, "fail", mission.status)
        with self._lock:
            mission.status = MissionStatus.FAILED
            mission.error = req.error
            mission.outcome = "failed"
            mission.updated_at = utcnow()
        # Distinct type from mission_completed so a failure can never
        # render as success (acceptance #9).
        self._store.append("mission_failed", mission.id, {"error": req.error})
        return mission

    def reset(self, mission_id: str) -> Mission:
        mission = self.get(mission_id)
        previous = mission.status
        with self._lock:
            mission.status = MissionStatus.CREATED
            mission.current_step_index = 0
            mission.result_summary = None
            mission.outcome = None
            mission.error = None
            mission.updated_at = utcnow()
        self._store.append("mission_reset", mission.id, {"previous_status": previous.value})
        return mission

    # -- internals --------------------------------------------------------
    def _transition(
        self, mission: Mission, to: MissionStatus, event: str, data: dict
    ) -> Mission:
        with self._lock:
            mission.status = to
            mission.updated_at = utcnow()
        payload = {"status": to.value, **data}
        current = mission.current_step
        if current is not None:
            payload.setdefault("current_step", current.id)
        self._store.append(event, mission.id, payload)
        return mission


# Module singletons wired into FastAPI routes.
controller = MissionController(_event_store)


def get_controller() -> MissionController:
    return controller
