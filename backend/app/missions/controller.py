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
    AgentRunRecord,
    BranchContext,
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
            mission.branch_context = BranchContext()
            mission.updated_at = utcnow()
        self._store.append("mission_reset", mission.id, {"previous_status": previous.value})
        return mission

    # -- F5 runner hooks (T075): narrow transitions, no execution logic ----
    # The controller stays the sole owner of every status transition; the
    # runner only ever calls these + `fail`/`complete`. Nothing here touches a
    # subprocess (plan.md PRD §4C).

    def record_run_context(
        self,
        mission_id: str,
        *,
        objective: str | None = None,
        resolved_model: str | None = None,
        quota_note: str | None = None,
    ) -> Mission:
        """Record F5 run-scoped context (endpoint/CLI pre-flight results).
        Only non-None values overwrite, so partial calls stay additive."""
        mission = self.get(mission_id)
        with self._lock:
            if objective is not None:
                mission.objective = objective
            if resolved_model is not None:
                mission.resolved_model = resolved_model
            if quota_note is not None:
                mission.quota_note = quota_note
            mission.updated_at = utcnow()
        return mission

    def begin_step(self, mission_id: str, index: int, record: AgentRunRecord) -> None:
        """Start hook: pin the workflow position and append the running record."""
        mission = self.get(mission_id)
        with self._lock:
            mission.current_step_index = index
            mission.agent_runs.append(record)
            mission.updated_at = utcnow()

    def finish_step(self, mission_id: str, agent_id: str, **fields) -> None:
        """Complete hook: fill the stored record with the real result fields."""
        mission = self.get(mission_id)
        with self._lock:
            for record in mission.agent_runs:
                if record.agent_id == agent_id:
                    for key, value in fields.items():
                        setattr(record, key, value)
                    record.completed_at = utcnow()
                    break
            mission.updated_at = utcnow()

    def fail_step(self, mission_id: str, step_id: str, agent_id: str, error: str) -> None:
        """Abort hook: mark the record failed and pin `failed_step_id` — the
        anchor resume-at-failed-step (FR-021) re-enters on (T086/T088)."""
        mission = self.get(mission_id)
        with self._lock:
            for record in mission.agent_runs:
                if record.agent_id == agent_id:
                    record.status = "failed"
                    record.error = error[:2000]
                    record.completed_at = utcnow()
                    break
            mission.failed_step_id = step_id
            mission.updated_at = utcnow()

    def advance_step(self, mission_id: str) -> Mission:
        """Advance hook: move past the completed step; clearing
        `failed_step_id` here honors "cleared only when execution advances
        past that step" (T088)."""
        mission = self.get(mission_id)
        with self._lock:
            mission.current_step_index = min(
                mission.current_step_index + 1, len(mission.steps)
            )
            mission.failed_step_id = None
            mission.updated_at = utcnow()
        return mission

    def retry(self, mission_id: str) -> Mission:
        """The SOLE owner of the `failed` → `running` status flip (I2).
        Does `retry_count += 1` and emits `mission_resumed {resumed_step,
        retry_count}` — neither the endpoint nor the runner mutates status off
        `failed` (contracts/workflow-api.md `retry`)."""
        mission = self.get(mission_id)
        if mission.status is not MissionStatus.FAILED or not mission.failed_step_id:
            raise InvalidTransitionError(mission_id, "retry", mission.status)
        with self._lock:
            mission.retry_count += 1
            mission.status = MissionStatus.RUNNING
            mission.updated_at = utcnow()
            payload = {
                "status": MissionStatus.RUNNING.value,
                "resumed_step": mission.failed_step_id,
                "retry_count": mission.retry_count,
            }
        current = mission.current_step
        if current is not None:
            payload.setdefault("current_step", current.id)
        self._store.append("mission_resumed", mission.id, payload)
        return mission

    def clear_run_state(self, mission_id: str) -> Mission:
        """F5 reset wiring (T090): drop run-scoped fields so no stale state
        survives into the next `created` run (mirrors F1 reset clearing
        `result_summary`; F1 `reset` above is untouched)."""
        mission = self.get(mission_id)
        with self._lock:
            mission.agent_runs = []
            mission.failed_step_id = None
            mission.retry_count = 0
            mission.resolved_model = None
            mission.objective = None
            mission.quota_note = None
            mission.updated_at = utcnow()
        return mission

    def apply_decision(
        self,
        mission_id: str,
        poll_id: str,
        winning_option_id: str,
        branch_map: dict[str, str],
        decided_by: str = "tally",
    ) -> Mission:
        """Narrow F3 hook: record a completed poll's outcome and patch the
        next step's task instructions from the winning option. Thin
        coordinator only — no agent execution (Hermes owns that in F5);
        Hermes reads `branch_context` when running the next step."""
        from backend.app.polls.models import AudienceDecision

        mission = self.get(mission_id)
        if mission.status not in (MissionStatus.RUNNING, MissionStatus.PAUSED):
            raise InvalidTransitionError(mission_id, "apply decision", mission.status)
        if winning_option_id not in branch_map:
            raise ValueError(f"unknown winning option: {winning_option_id!r}")
        instruction = (branch_map[winning_option_id] or "").strip()
        decision = AudienceDecision(
            poll_id=poll_id,
            mission_id=mission_id,
            winning_option_id=winning_option_id,
            decided_by=decided_by,  # type: ignore[arg-type]
            applied_at=utcnow(),
        )
        with self._lock:
            mission.branch_context.applied_decisions.append(decision)
            if instruction:
                mission.branch_context.current_branch_instruction = instruction
                current = mission.current_step
                if current is not None:
                    current.description = instruction
            mission.updated_at = utcnow()
        self._store.append(
            "audience_decision_applied",
            mission.id,
            {
                "poll_id": poll_id,
                "winning_option_id": winning_option_id,
                "decided_by": decided_by,
                "next_step": instruction
                or (mission.current_step.description if mission.current_step else ""),
            },
        )
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
