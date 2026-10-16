"""Serial workflow runner + shared pre-flight gates (F5).

- `run_preflight` — the model-pin + quota-gate sequence both `POST /run`/
  `POST /retry` (backend/app/api/missions.py) and the CLI (backend/app/cli.py)
  must apply *before* any execution starts.
- `SerialWorkflowRunner` core loop (T073/T074/T077): compose → `agent_started`
  → injected `AgentExecutor` (sync, one active mission via the module-level
  run registry) → validate/store → `agent_completed` → `agent_handoff` →
  advance; honest completion only when all three steps succeed (FR-008).
- Failure mapping + abort (T086): one `agent_failed {failure_kind}` then
  `controller.fail` → FAILED terminal; never continues, never auto-retries.
- Retry-resume (T088): re-enters the loop at `failed_step_id`, composing that
  step's task from the preserved `agent_runs` outputs; completed steps emit
  nothing.

Everything is synchronous (research.md §1) — the API path runs the loop in one
daemon worker thread per accepted run; the CLI path calls `run_mission_sync`
on the main thread.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from backend.app.agents import modelinfo, quota
from backend.app.agents.executor import (
    AgentExecutor,
    AgentOutputError,
    AgentStepResult,
    StepContext,
    failure_kind_for,
)
from backend.app.agents.modelinfo import ResolvedModel
from backend.app.agents.profiles import AGENT_SLUGS, get_profile
from backend.app.agents.settings import RunLimits
from backend.app.events.store import event_store
from backend.app.missions.controller import MissionNotFoundError, get_controller
from backend.app.missions.models import (
    AgentRunRecord,
    CompleteMissionRequest,
    FailMissionRequest,
    Mission,
    MissionStatus,
    utcnow,
)

__all__ = [
    "ActiveRun",
    "LowQuotaError",
    "ModelPinError",
    "active_runs",
    "clear_registry",
    "compose_task",
    "get_active",
    "make_executor",
    "run_mission_sync",
    "run_preflight",
    "start_background",
]

HANDOFF_REASONS: dict[str, str] = {
    "critic": "critique the findings per the predefined workflow",
    "summarizer": "synthesize both handoffs per the predefined workflow",
}


def run_preflight(
    *, confirm_low_quota: bool = False, limits: RunLimits | None = None
) -> tuple[str, str | None]:
    """Apply the pre-execution gates in contract order (workflow-api.md):
    model pin first, then the quota gate.

    Returns `(resolved_model, quota_note)` for recording on the mission.
    Raises `ModelPinError` (refuse, never switch) or `LowQuotaError` (blocked
    until the operator passes `confirm_low_quota`)."""
    limits = limits or RunLimits.from_env()
    resolved: ResolvedModel = modelinfo.resolve()  # FR-011 pin guard
    decision = quota.check(confirm_low_quota, limits=limits)  # FR-024 gate
    if not decision.allowed:
        raise LowQuotaError(decision.note)
    return resolved.display, decision.note or None


# Re-exported for endpoint/CLI handlers that map gate failures to 409/exit 2.
LowQuotaError = quota.LowQuotaError
ModelPinError = modelinfo.ModelPinError


# -- run registry (one active mission per process, FR-009) -------------------


@dataclass
class ActiveRun:
    """Bookkeeping for one accepted run: cancel event (reset wiring, rule 5)
    + the worker thread (joined by tests / observability)."""

    mission_id: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    @property
    def alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()


_registry_lock = threading.Lock()
_registry: dict[str, ActiveRun] = {}


def make_executor(cancel_event: threading.Event) -> AgentExecutor:
    """Process-wide executor factory — the protocol seam tests replace
    (FakeExecutor) so default gates make zero model calls (FR-023)."""
    from backend.app.agents.executor import HermesCliExecutor

    return HermesCliExecutor(cancel_event)


def get_active(mission_id: str) -> ActiveRun | None:
    with _registry_lock:
        return _registry.get(mission_id)


def active_runs() -> list[ActiveRun]:
    with _registry_lock:
        return list(_registry.values())


def clear_registry() -> None:
    """Test/reset helper: drops all run bookkeeping (teardown only — entries
    are never removed on completion so post-run joins stay valid)."""
    with _registry_lock:
        _registry.clear()


def start_background(mission_id: str) -> ActiveRun:
    """Register a run and spawn the single daemon worker thread. Raises
    RuntimeError if this mission or any other mission is already executing."""
    global _registry
    with _registry_lock:
        for run in _registry.values():
            if run.alive:
                if run.mission_id == mission_id:
                    raise RuntimeError("mission is already executing")
                raise RuntimeError("another mission is already running")
        run = ActiveRun(mission_id=mission_id)
        run.thread = threading.Thread(
            target=run_mission_sync,
            args=(mission_id,),
            name=f"f5-run-{mission_id}",
            daemon=True,
        )
        _registry[mission_id] = run
    run.thread.start()
    return run


# -- task composition (T073) --------------------------------------------------


def compose_task(mission: Mission, profile_id: str, prior: dict[str, str],
                 max_output_chars: int) -> str:
    """Compose one step's exact task text (recorded verbatim on the
    AgentRunRecord — SC-002/SC-003 audits read it from the record alone).

    Researcher: objective/title + the branch instruction when an audience
    decision was applied, else an explicit "no audience decision applied"
    note (never invented). Critic/Summarizer: role instructions + the prior
    agents' real outputs, each truncated to `max_output_chars` first."""
    profile = get_profile(profile_id)

    def bound(profile_id_: str) -> str:
        return prior.get(profile_id_, "")[:max_output_chars]

    if profile_id == "researcher":
        subject = (mission.objective or mission.title).strip()
        instruction = mission.branch_context.current_branch_instruction
        parts = [
            profile.instructions,
            f"Mission objective: {subject}",
        ]
        if instruction:
            parts.append(f"Audience direction (applied): {instruction}")
        else:
            parts.append(
                "Audience direction: no audience decision applied for this run."
            )
    elif profile_id == "critic":
        parts = [
            profile.instructions,
            "Researcher's output:",
            bound("researcher"),
        ]
    else:
        parts = [
            profile.instructions,
            "Researcher's output:",
            bound("researcher"),
            "Critic's review:",
            bound("critic"),
        ]
    return "\n\n".join(part for part in parts if part)


# -- the core loop (T074/T077/T086/T088) -------------------------------------


def run_mission_sync(
    mission_id: str, *, on_event: Callable[[dict], None] | None = None
) -> None:
    """Drive the serial workflow synchronously on the calling thread.

    `on_event` (CLI live printing) receives each store payload as it is
    appended; API callers pass nothing. The loop starts at `failed_step_id`
    when present (resume-at-failed-step, FR-021) — completed steps are never
    re-executed and emit no events."""
    ctrl = get_controller()
    try:
        mission = ctrl.get(mission_id)
    except MissionNotFoundError:
        return

    run = get_active(mission_id)
    cancel = run.cancel_event if run is not None else threading.Event()
    limits = RunLimits.from_env()
    executor = make_executor(cancel)

    def emit(event_type: str, data: dict) -> None:
        payload = event_store.append(event_type, mission_id, data)
        if on_event is not None:
            on_event(payload)

    if mission.status is MissionStatus.CREATED:
        mission = ctrl.start(mission_id)  # CLI/direct path: F1 start is the only source
    if mission.status is not MissionStatus.RUNNING:
        return  # not startable (paused/reset under us) — do not execute

    # Resume-at-failed-step (T088): preserved outputs flow into the task.
    start_index = 0
    if mission.failed_step_id:
        start_index = next(
            (i for i, s in enumerate(mission.steps) if s.id == mission.failed_step_id),
            0,
        )

    prior: dict[str, str] = {
        r.profile: r.output
        for r in mission.agent_runs
        if r.status == "completed"
    }
    attempts: dict[str, int] = {}
    for r in mission.agent_runs:
        attempts[r.step_id] = attempts.get(r.step_id, 0) + 1

    for index in range(start_index, len(mission.steps)):
        if cancel.is_set():
            return  # reset during execution: no further agent events (T085)
        step = mission.steps[index]
        profile = get_profile(step.agent_profile)
        attempts[step.id] = attempts.get(step.id, 0) + 1
        agent_id = f"{AGENT_SLUGS[profile.id]}-{attempts[step.id]}"
        task_text = compose_task(mission, profile.id, prior, limits.max_output_chars)

        record = AgentRunRecord(
            step_id=step.id,
            profile=profile.id,
            agent_id=agent_id,
            task_input=task_text,
            status="running",
            started_at=utcnow(),
        )
        ctrl.begin_step(mission_id, index, record)
        emit("agent_started", {
            "agent_id": agent_id,
            "profile": profile.id,
            "step_id": step.id,
            "task": task_text[:300],
        })

        def tool_emit(event_type: str, data: dict, _agent=agent_id, _step=step.id) -> None:
            # Executor supplies tool fields; the runner owns identity keys.
            payload = dict(data)
            payload.setdefault("agent_id", _agent)
            payload.setdefault("step_id", _step)
            emit(event_type, payload)

        ctx = StepContext(
            agent_id=agent_id,
            profile_id=profile.id,
            toolsets=profile.toolsets,  # `-t none` sentinel / `-t terminal`
            task_text=task_text,
            timeout_seconds=limits.step_timeout_seconds,
            run_budget_seconds=limits.run_budget_seconds,
            max_turns=limits.max_turns,
            workdir=str(Path("data/runs") / mission_id),
        )

        began = time.monotonic()
        try:
            result: AgentStepResult = executor.run(ctx, tool_emit)
            output = (result.output or "").strip()
            if not output:
                raise AgentOutputError("empty agent output")
            if len(output) > limits.max_output_chars:
                raise AgentOutputError(
                    f"agent output {len(output)} chars exceeds "
                    f"{limits.max_output_chars}"
                )
        except Exception as exc:  # typed executor errors + wrapped surprises
            if cancel.is_set():
                return  # reset raced the abort — mission already reset (T085)
            try:
                current = ctrl.get(mission_id)
            except MissionNotFoundError:
                return
            if current.status is not MissionStatus.RUNNING:
                return  # reset/transition raced the abort — never resurrect
            error = (str(exc) or type(exc).__name__)[:2000]
            kind = failure_kind_for(exc)
            ctrl.fail_step(mission_id, step.id, agent_id, error)
            emit("agent_failed", {
                "agent_id": agent_id,
                "profile": profile.id,
                "step_id": step.id,
                "error": error,
                "failure_kind": kind,
            })
            ctrl.fail(mission_id, FailMissionRequest(error=f"{kind}: {error}"))
            return  # abort-to-failed-terminal: chain never continues (FR-020)

        duration = round(time.monotonic() - began, 3)
        ctrl.finish_step(
            mission_id,
            agent_id,
            status="completed",
            output=output,
            tool_calls=result.tool_calls,
            duration_seconds=duration,
            session_id=result.session_id,
        )
        prior[profile.id] = output
        emit("agent_completed", {
            "agent_id": agent_id,
            "profile": profile.id,
            "step_id": step.id,
            "summary": output[:300],
            "output_chars": len(output),
            "tool_calls": result.tool_calls,
            "duration_seconds": duration,
            "session_id": result.session_id,
        })
        ctrl.advance_step(mission_id)

        if index + 1 < len(mission.steps):
            next_step = mission.steps[index + 1]
            next_profile = get_profile(next_step.agent_profile)
            next_agent = (
                f"{AGENT_SLUGS[next_profile.id]}-{attempts.get(next_step.id, 0) + 1}"
            )
            emit("agent_handoff", {
                "from_agent": agent_id,
                "to_agent": next_agent,
                "from_profile": profile.id,
                "to_profile": next_profile.id,
                "reason": HANDOFF_REASONS.get(
                    next_profile.id, "continue the predefined workflow"
                ),
                "summary": output[:300],
                "step_id": next_step.id,
            })

    # Honest completion (FR-008/T077): only all-three-success reaches here.
    final_output = prior.get("summarizer", "")
    ctrl.complete(
        mission_id,
        CompleteMissionRequest(summary=final_output[:5000], outcome="success"),
    )
