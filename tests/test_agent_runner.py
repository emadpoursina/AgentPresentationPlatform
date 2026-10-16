"""F5 stub-executor tests: serial flow, event contracts, abort/retry/reset.

Covers tasks T069 (US1 serial flow + FakeExecutor), T095 (run-endpoint
branch-context sequencing), T079 (US2 event-contract invariants), and
T083–T085 (US3 abort / retry-resume / reset-during-execution).

Every test stubs the executor at the protocol seam and stubs the
model/quota gates — zero subprocesses, zero model quota (FR-023).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from backend.app.agents import modelinfo, quota
from backend.app.agents import runner as runner_mod
from backend.app.agents.executor import (
    AgentCancelled,
    AgentExitedError,
    AgentOutputError,
    AgentStepResult,
    AgentStepTimeout,
    AgentToolError,
    StepContext,
)
from backend.app.main import app
from backend.app.missions.controller import get_controller
from backend.app.missions.models import CreateMissionRequest, MissionStatus

PINNED_CONFIG = {
    "default": "muse-spark-1.3-contributor",
    "provider": "opencode-go",
    "base_url": "https://opencode.ai/zen/go/v1",
    "api_mode": "codex_responses",
}

AGENT_TOOL_TYPES = {
    "agent_started",
    "tool_started",
    "tool_completed",
    "agent_handoff",
    "agent_completed",
    "agent_failed",
}

RESEARCH_OUTPUT = "RESEARCH_FINDINGS: agents adoption risks in small teams."
CRITIC_OUTPUT = "CRITIC_REVIEW: the findings overstate certainty."
SUMMARY_OUTPUT = "SUMMARY_MAIN_CONCLUSION: adopt gradually with human review."

INSTRUCTION = "Focus the research on cost and rollout risk."


# -- FakeExecutor (contracts/hermes-executor.md fake/stub contract) ----------


@dataclass
class StepScript:
    output: str = "scripted agent output"
    tool_events: list[dict] = field(default_factory=list)
    fail: BaseException | None = None
    delay: float = 0.0  # seconds; polled for cancellation every 10ms


class FakeExecutor:
    """Scripted `AgentExecutor`: zero subprocesses, zero quota, milliseconds
    by default; failures/timeouts are raised from the script."""

    def __init__(self, steps: dict[str, StepScript] | None = None) -> None:
        self.steps = steps or {}
        self.cancel_event: threading.Event | None = None
        self.calls: list[StepContext] = []

    def run(self, ctx: StepContext, emit) -> AgentStepResult:
        self.calls.append(ctx)
        script = self.steps.get(
            ctx.profile_id, StepScript(output=f"default {ctx.profile_id} output")
        )
        if script.delay:
            deadline = time.monotonic() + script.delay
            while time.monotonic() < deadline:
                if self.cancel_event is not None and self.cancel_event.is_set():
                    raise AgentCancelled("execution cancelled (stub)")
                time.sleep(0.01)
        if script.fail is not None:
            raise script.fail
        tool_ends = 0
        for ev in script.tool_events:
            if ev.get("kind", "start") == "start":
                emit(
                    "tool_started",
                    {
                        "agent_id": ctx.agent_id,
                        "tool_name": ev.get("tool_name", "terminal"),
                        "action": ev.get("action", "ls -la"),
                    },
                )
            else:
                tool_ends += 1
                emit(
                    "tool_completed",
                    {
                        "agent_id": ctx.agent_id,
                        "tool_name": ev.get("tool_name", "terminal"),
                        "status": ev.get("status", "completed"),
                        "summary": ev.get("summary", "tool output"),
                        "exit_code": ev.get("exit_code", 0),
                    },
                )
        return AgentStepResult(
            output=script.output,
            session_id=f"sess-{ctx.agent_id}",
            tool_calls=tool_ends,
            duration_seconds=0.01,
        )


def _happy_executor() -> FakeExecutor:
    return FakeExecutor(
        {
            "researcher": StepScript(output=RESEARCH_OUTPUT),
            "critic": StepScript(output=CRITIC_OUTPUT),
            "summarizer": StepScript(output=SUMMARY_OUTPUT),
        }
    )


# -- shared fixtures / helpers ----------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch: pytest.MonkeyPatch):
    from backend.app.events.store import event_store
    from backend.app.missions.controller import controller as missions
    from backend.app.participants.controller import controller as participants
    from backend.app.polls.controller import controller as polls

    monkeypatch.delenv("PLAYGROUND_PRESENTER_TOKEN", raising=False)
    missions.clear()
    participants.clear()
    polls.clear()
    event_store.clear()
    quota.clear_cache()
    # Gate seams: no subprocess, no quota in unit tests (FR-023).
    monkeypatch.setattr(modelinfo, "_load_model_config", lambda: dict(PINNED_CONFIG))
    monkeypatch.setattr(
        quota,
        "_load_usage",
        lambda: {"windows": [{"label": "Monthly", "used_percent": 10.0}]},
    )
    yield
    _join_all_runs()
    runner_mod.clear_registry()


def _use_executor(monkeypatch: pytest.MonkeyPatch, executor: FakeExecutor) -> FakeExecutor:
    """Install `executor` as the process-wide runner executor factory."""

    def _make(cancel_event: threading.Event) -> FakeExecutor:
        executor.cancel_event = cancel_event
        return executor

    monkeypatch.setattr(runner_mod, "make_executor", _make)
    return executor


def _join_all_runs(timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    for run in runner_mod.active_runs():
        thread = run.thread
        if thread is not None and thread.is_alive():
            remaining = max(0.0, deadline - time.monotonic())
            thread.join(timeout=remaining)


def _make_mission(title: str = "Demo mission", *, start: bool = True):
    ctrl = get_controller()
    mission = ctrl.create(CreateMissionRequest(title=title))
    if start:
        ctrl.start(mission.id)
    return mission


def _events(mid: str) -> list[dict]:
    from backend.app.events.store import event_store

    return event_store.list(mission_id=mid, after_id=0, limit=500)


def _types(mid: str) -> list[str]:
    return [e["type"] for e in _events(mid)]


def _client() -> TestClient:
    return TestClient(app)


def _join_run(mid: str, timeout: float = 5.0) -> None:
    run = runner_mod.get_active(mid)
    assert run is not None and run.thread is not None, "run was never registered"
    run.thread.join(timeout=timeout)
    assert not run.thread.is_alive(), "run thread did not finish in time"


def _wait_status(client: TestClient, mid: str, status: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        mission = client.get(f"/api/missions/{mid}").json()
        if mission["status"] == status:
            return mission
        time.sleep(0.02)
    raise AssertionError(f"mission never reached status {status!r}")


# -- T069: US1 serial flow (SC-001/SC-002/SC-003/SC-005) ---------------------


def test_three_ordered_agent_executions_sc001(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_executor(monkeypatch, _happy_executor())
    mission = _make_mission()
    runner_mod.run_mission_sync(mission.id)

    ctrl = get_controller()
    stored = ctrl.get(mission.id)
    assert stored.status is MissionStatus.COMPLETED

    started = [e for e in _events(mission.id) if e["type"] == "agent_started"]
    assert [e["data"]["profile"] for e in started] == ["researcher", "critic", "summarizer"]
    assert [e["data"]["agent_id"] for e in started] == [
        "research-1",
        "critic-1",
        "summarize-1",
    ]
    completed = [e for e in _events(mission.id) if e["type"] == "agent_completed"]
    assert [e["data"]["agent_id"] for e in completed] == [
        "research-1",
        "critic-1",
        "summarize-1",
    ]
    # Records persisted on the mission itself (audit from the record alone).
    assert [r.step_id for r in stored.agent_runs] == ["research", "critique", "summarize"]
    assert all(r.status == "completed" for r in stored.agent_runs)


def test_handoffs_pass_real_outputs_verbatim_sc002(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _use_executor(monkeypatch, _happy_executor())
    mission = _make_mission()
    runner_mod.run_mission_sync(mission.id)

    by_profile = {ctx.profile_id: ctx.task_text for ctx in fake.calls}
    assert RESEARCH_OUTPUT in by_profile["critic"]  # Critic input has Researcher output
    assert RESEARCH_OUTPUT in by_profile["summarizer"]
    assert CRITIC_OUTPUT in by_profile["summarizer"]  # Summarizer input has both

    stored = get_controller().get(mission.id)
    records = {r.profile: r for r in stored.agent_runs}
    assert records["critic"].task_input == by_profile["critic"]
    assert records["researcher"].output == RESEARCH_OUTPUT


def test_researcher_task_includes_branch_instruction_sc003(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _use_executor(monkeypatch, _happy_executor())
    mission = _make_mission()
    ctrl = get_controller()
    stored = ctrl.get(mission.id)
    stored.branch_context.current_branch_instruction = INSTRUCTION
    runner_mod.run_mission_sync(mission.id)

    researcher_task = fake.calls[0].task_text
    assert INSTRUCTION in researcher_task
    assert mission.title in researcher_task or stored.objective in researcher_task
    # Recorded on the run record too (SC-003 audit from the record alone).
    record = next(r for r in ctrl.get(mission.id).agent_runs if r.profile == "researcher")
    assert INSTRUCTION in record.task_input


def test_researcher_explicit_no_decision_note_when_branch_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _use_executor(monkeypatch, _happy_executor())
    mission = _make_mission()
    runner_mod.run_mission_sync(mission.id)

    task = fake.calls[0].task_text
    assert "no audience decision applied" in task
    assert INSTRUCTION not in task


def test_objective_used_for_researcher_and_result_is_summarizer_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_executor(monkeypatch, _happy_executor())
    mission = _make_mission()
    get_controller().record_run_context(mission.id, objective="Operational topic text")
    runner_mod.run_mission_sync(mission.id)

    stored = get_controller().get(mission.id)
    assert stored.objective == "Operational topic text"
    # SC-005 / acceptance #4: result_summary is the Summarizer's real output.
    assert stored.result_summary == SUMMARY_OUTPUT
    assert stored.outcome == "success"
    assert stored.resolved_model is None  # recorded by the endpoint/CLI path


# -- T095: run-endpoint branch-context sequencing (SC-003 API path) ----------


def _open_vote_close(client: TestClient, mid: str) -> None:
    join = client.post("/api/participants/join", json={"display_name": "Ann"})
    participant_id = join.json()["id"]
    poll = client.post(
        f"/api/missions/{mid}/polls",
        json={
            "question": "Which direction next?",
            "options": [
                {"id": "a", "label": "Cost", "branch_instruction": INSTRUCTION},
                {"id": "b", "label": "Speed", "branch_instruction": "Go wide instead."},
            ],
            "deadline_seconds": 120,
            "reveal_mode": "live",
        },
    )
    assert poll.status_code == 201, poll.text
    poll_id = poll.json()["id"]
    vote = client.post(
        f"/api/missions/{mid}/polls/{poll_id}/vote",
        json={"participant_id": participant_id, "option_id": "a"},
    )
    assert vote.status_code == 200, vote.text
    close = client.post(f"/api/missions/{mid}/polls/{poll_id}/close")
    assert close.status_code == 200, close.text


def test_run_accepts_f1_started_running_after_decision_sc003(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _use_executor(monkeypatch, _happy_executor())
    client = _client()
    mid = client.post("/api/missions", json={"title": "Sequenced"}).json()["id"]
    # 1) F1 start: mission -> running (polls only open while running).
    assert client.post(f"/api/missions/{mid}/start").json()["status"] == "running"
    # 2) Poll resolves -> apply_decision populates branch_context BEFORE run.
    _open_vote_close(client, mid)
    branch = client.get(f"/api/missions/{mid}").json()["branch_context"]
    assert branch["current_branch_instruction"] == INSTRUCTION

    # 3) run accepted from F1-started running with no active F5 runner.
    res = client.post(f"/api/missions/{mid}/run", json={})
    assert res.status_code == 202, res.text
    _join_run(mid)
    mission = _wait_status(client, mid, "completed")

    researcher = next(
        r for r in mission["agent_runs"] if r["profile"] == "researcher"
    )
    assert INSTRUCTION in researcher["task_input"]
    assert fake.calls[0].task_text == researcher["task_input"]
    # Exactly one mission_started for the whole lifecycle (F1 start is its only source).
    assert _types(mid).count("mission_started") == 1
    # Additive mission fields recorded by the run endpoint.
    assert mission["resolved_model"] == (
        "muse-spark-1.3-contributor @ opencode-go (codex_responses)"
    )
    assert mission["quota_note"] is not None


def test_run_records_objective_and_returns_202(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_executor(monkeypatch, _happy_executor())
    client = _client()
    mid = client.post("/api/missions", json={"title": "Obj"}).json()["id"]
    res = client.post(f"/api/missions/{mid}/run", json={"objective": "Investigate costs"})
    assert res.status_code == 202
    _join_run(mid)
    mission = _wait_status(client, mid, "completed")
    assert mission["objective"] == "Investigate costs"
    assert "Investigate costs" in mission["agent_runs"][0]["task_input"]


def test_run_rejects_overlong_objective_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_executor(monkeypatch, _happy_executor())
    client = _client()
    mid = client.post("/api/missions", json={"title": "Long"}).json()["id"]
    res = client.post(f"/api/missions/{mid}/run", json={"objective": "x" * 501})
    assert res.status_code == 422


@pytest.mark.parametrize("setup", ["paused", "completed", "failed"])
def test_run_409_for_non_startable_status(setup: str) -> None:
    client = _client()
    mid = client.post("/api/missions", json={"title": setup.title()}).json()["id"]
    client.post(f"/api/missions/{mid}/start")
    if setup == "paused":
        client.post(f"/api/missions/{mid}/pause")
    elif setup == "completed":
        client.post(f"/api/missions/{mid}/complete", json={"summary": "ok"})
    else:
        client.post(f"/api/missions/{mid}/fail", json={"error": "boom"})

    res = client.post(f"/api/missions/{mid}/run", json={})
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail.startswith("mission not runnable")
    assert setup in detail


def test_run_409_when_mission_already_executing(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_executor(
        monkeypatch, FakeExecutor({"researcher": StepScript(delay=5.0)})
    )
    client = _client()
    mid = client.post("/api/missions", json={"title": "Busy"}).json()["id"]
    assert client.post(f"/api/missions/{mid}/run", json={}).status_code == 202

    res = client.post(f"/api/missions/{mid}/run", json={})
    assert res.status_code == 409
    assert res.json()["detail"] == "mission is already executing"

    # Cleanup: reset cancels the in-flight step and releases the registry.
    assert client.post(f"/api/missions/{mid}/reset").status_code == 200
    _join_run(mid)


def test_run_409_when_another_mission_running(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_executor(
        monkeypatch, FakeExecutor({"researcher": StepScript(delay=5.0)})
    )
    client = _client()
    busy = client.post("/api/missions", json={"title": "First"}).json()["id"]
    assert client.post(f"/api/missions/{busy}/run", json={}).status_code == 202

    other = client.post("/api/missions", json={"title": "Second"}).json()["id"]
    res = client.post(f"/api/missions/{other}/run", json={})
    assert res.status_code == 409
    assert res.json()["detail"] == "another mission is already running"

    assert client.post(f"/api/missions/{busy}/reset").status_code == 200
    _join_run(busy)


def test_run_404_unknown_mission() -> None:
    client = _client()
    assert client.post("/api/missions/nope/run", json={}).status_code == 404


# -- T079: US2 event-contract invariants (contracts/agent-event-payloads.md) --


def test_event_ordering_invariants_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_executor(
        monkeypatch,
        FakeExecutor(
            {
                "researcher": StepScript(
                    output=RESEARCH_OUTPUT,
                    tool_events=[{"kind": "start"}, {"kind": "end"}],
                ),
                "critic": StepScript(output=CRITIC_OUTPUT),
                "summarizer": StepScript(output=SUMMARY_OUTPUT),
            },
        ),
    )
    mission = _make_mission()
    runner_mod.run_mission_sync(mission.id)
    events = _events(mission.id)
    types = [e["type"] for e in events]

    # Invariant 1: per-step started -> (tool pair)* -> completed.
    # (`agent_handoff` into a step also carries that step_id — excluded here;
    # its ordering is invariant 2.)
    for step in ("research", "critique", "summarize"):
        step_types = [
            e["type"] for e in events
            if e["data"].get("step_id") == step and e["type"] != "agent_handoff"
        ]
        assert step_types[0] == "agent_started"
        assert step_types[-1] == "agent_completed"
        pairs = step_types[1:-1]
        assert all(t == "tool_started" for t in pairs[0::2])
        assert all(t == "tool_completed" for t in pairs[1::2])

    # Invariant 2: completed(i) < handoff(i->i+1) < started(i+1).
    completed_idx = [i for i, t in enumerate(types) if t == "agent_completed"]
    handoff_idx = [i for i, t in enumerate(types) if t == "agent_handoff"]
    started_idx = [i for i, t in enumerate(types) if t == "agent_started"]
    assert len(handoff_idx) == 2
    assert completed_idx[0] < handoff_idx[0] < started_idx[1]
    assert completed_idx[1] < handoff_idx[1] < started_idx[2]

    # Only the six canonical agent/tool types are emitted by F5.
    agent_tool = [t for t in types if t in AGENT_TOOL_TYPES]
    assert set(agent_tool) <= AGENT_TOOL_TYPES
    from backend.app.events.models import EVENT_TYPES

    assert set(types) <= set(EVENT_TYPES)  # EVENT_TYPES unchanged + sufficient

    # Tool-free steps emit zero tool events; counts match the script 1:1.
    for step in ("critique", "summarize"):
        assert not [
            e for e in events
            if e["data"].get("step_id") == step and e["type"].startswith("tool_")
        ]
    assert types.count("tool_started") == 1
    assert types.count("tool_completed") == 1
    # Payload shapes pinned to the contract key families.
    started = next(e for e in events if e["type"] == "agent_started")
    assert set(started["data"]) == {"agent_id", "profile", "step_id", "task"}
    assert len(started["data"]["task"]) <= 300
    completed_ev = next(e for e in events if e["type"] == "agent_completed")
    assert set(completed_ev["data"]) == {
        "agent_id", "profile", "step_id", "summary",
        "output_chars", "tool_calls", "duration_seconds", "session_id",
    }
    assert len(completed_ev["data"]["summary"]) <= 300
    handoff = next(e for e in events if e["type"] == "agent_handoff")
    assert {"from_agent", "to_agent", "from_profile", "to_profile",
            "reason", "summary", "step_id"} == set(handoff["data"])
    tool_completed = next(e for e in events if e["type"] == "tool_completed")
    assert len(tool_completed["data"]["summary"]) <= 300


def test_failed_log_has_no_mission_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_executor(
        monkeypatch,
        FakeExecutor(
            {
                "researcher": StepScript(output=RESEARCH_OUTPUT),
                "critic": StepScript(fail=AgentExitedError("model down")),
            },
        ),
    )
    mission = _make_mission()
    runner_mod.run_mission_sync(mission.id)
    types = _types(mission.id)
    assert "agent_failed" in types
    assert "mission_failed" in types
    assert "mission_completed" not in types  # invariant 3


# -- T083: US3 abort tests (SC-006/SC-007/FR-015/FR-020) ---------------------


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        (AgentStepTimeout("step timeout after 0.05s (killed)"), "timeout"),
        (AgentToolError("terminal exit 1"), "tool"),
        (AgentExitedError("hermes exited 1"), "model"),
        (AgentOutputError("empty agent output"), "output_invalid"),
    ],
)
def test_abort_to_failed_terminal(
    monkeypatch: pytest.MonkeyPatch, failure: BaseException, kind: str
) -> None:
    fake = FakeExecutor(
        {
            "researcher": StepScript(output=RESEARCH_OUTPUT),
            "critic": StepScript(fail=failure),
        }
    )
    _use_executor(monkeypatch, fake)
    mission = _make_mission()
    runner_mod.run_mission_sync(mission.id)

    ctrl = get_controller()
    stored = ctrl.get(mission.id)
    assert stored.status is MissionStatus.FAILED
    assert stored.failed_step_id == "critique"

    events = _events(mission.id)
    failed = [e for e in events if e["type"] == "agent_failed"]
    assert len(failed) == 1  # exactly once
    assert failed[0]["data"]["failure_kind"] == kind
    assert failed[0]["data"]["step_id"] == "critique"
    types = [e["type"] for e in events]
    assert types.index("agent_failed") < types.index("mission_failed")
    assert "mission_completed" not in types
    # Remaining chain never runs; completed records + reason preserved.
    assert all(c.profile_id != "summarizer" for c in fake.calls)
    by_profile = {r.profile: r for r in stored.agent_runs}
    assert by_profile["researcher"].status == "completed"
    assert by_profile["researcher"].output == RESEARCH_OUTPUT
    assert by_profile["critic"].status == "failed"
    assert by_profile["critic"].error
    assert stored.error


def test_abort_on_empty_and_oversized_output(monkeypatch: pytest.MonkeyPatch) -> None:
    for bad_output in ("", "x" * 20001):
        from backend.app.events.store import event_store

        event_store.clear()
        get_controller().clear()
        _use_executor(monkeypatch, FakeExecutor({"researcher": StepScript(output=bad_output)}))
        mission = _make_mission()
        runner_mod.run_mission_sync(mission.id)
        stored = get_controller().get(mission.id)
        assert stored.status is MissionStatus.FAILED
        failed = [e for e in _events(mission.id) if e["type"] == "agent_failed"]
        assert failed[0]["data"]["failure_kind"] == "output_invalid"
        runner_mod.clear_registry()


# -- T084: US3 retry-resume (SC-010/FR-021) ----------------------------------


def test_retry_resumes_at_failed_step_no_reexecution(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _use_executor(
        monkeypatch,
        FakeExecutor(
            {
                "researcher": StepScript(output=RESEARCH_OUTPUT),
                "critic": StepScript(fail=AgentExitedError("model hiccup")),
                "summarizer": StepScript(output=SUMMARY_OUTPUT),
            },
        ),
    )
    client = _client()
    mid = client.post("/api/missions", json={"title": "Retry me"}).json()["id"]
    assert client.post(f"/api/missions/{mid}/start").status_code == 200
    assert client.post(f"/api/missions/{mid}/run", json={}).status_code == 202
    _join_run(mid)
    assert _wait_status(client, mid, "failed")["failed_step_id"] == "critique"

    # Operator fixes the model; retry re-checks gates then resumes.
    fake.steps["critic"] = StepScript(output=CRITIC_OUTPUT)
    res = client.post(f"/api/missions/{mid}/retry", json={})
    assert res.status_code == 202, res.text
    assert res.json()["retry_count"] == 1
    _join_run(mid)
    mission = _wait_status(client, mid, "completed")

    events = _events(mid)
    resumed = next(e for e in events if e["data"].get("resumed_step") is not None)
    assert resumed["type"] == "mission_resumed"
    assert resumed["data"]["resumed_step"] == "critique"
    assert resumed["data"]["retry_count"] == 1
    started = [e for e in events if e["type"] == "agent_started"]
    # Previously completed steps are NOT re-executed (SC-010): research-1
    # appears once; the failed step retries under its own attempt id (A2).
    assert [e["data"]["agent_id"] for e in started] == [
        "research-1", "critic-1", "critic-2", "summarize-1",
    ]
    # mission_resumed precedes the RESUMED step's agent_started (critic-2).
    resumed_started = next(
        e for e in events if e["type"] == "agent_started"
        and e["data"].get("agent_id") == "critic-2"
    )
    assert resumed["id"] < resumed_started["id"]
    # Resumed step's task_input contains the preserved completed-agent output;
    # its completed record is the second attempt (critic-2).
    records = {r["profile"]: r for r in mission["agent_runs"]}
    assert records["critic"]["task_input"].count(RESEARCH_OUTPUT) == 1
    assert records["critic"]["agent_id"] == "critic-2"
    assert records["critic"]["status"] == "completed"
    assert [r["agent_id"] for r in mission["agent_runs"] if r["profile"] == "critic"] == [
        "critic-1", "critic-2",
    ]
    assert mission["retry_count"] == 1
    assert mission["failed_step_id"] is None  # cleared when execution advanced past


def types_index(events: list[dict], etype: str, after_id: int = 0) -> int:
    for i, e in enumerate(events):
        if e["type"] == etype and e["id"] >= after_id:
            return i
    raise AssertionError(f"event {etype!r} not found")


def test_retry_409_guards_and_gate_recheck(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    # 409 unless failed + failed_step_id.
    mid = client.post("/api/missions", json={"title": "No fail"}).json()["id"]
    assert client.post(f"/api/missions/{mid}/retry", json={}).status_code == 409
    client.post(f"/api/missions/{mid}/start")
    assert client.post(f"/api/missions/{mid}/retry", json={}).status_code == 409

    # Unknown mission -> 404.
    assert client.post("/api/missions/nope/retry", json={}).status_code == 404

    # Model pin re-checked on retry: a changed model refuses (FR-011).
    # First reach a genuine failed state via the stubbed runner.
    _use_executor(
        monkeypatch,
        FakeExecutor({"researcher": StepScript(fail=AgentExitedError("model down"))}),
    )
    mid2 = client.post("/api/missions", json={"title": "Pinned"}).json()["id"]
    client.post(f"/api/missions/{mid2}/start")
    assert client.post(f"/api/missions/{mid2}/run", json={}).status_code == 202
    _join_run(mid2)
    failed = _wait_status(client, mid2, "failed")
    assert failed["failed_step_id"] == "research"

    from backend.app.agents import modelinfo
    from backend.app.agents.modelinfo import ModelPinError

    def _changed():
        raise ModelPinError("resolved model changed (other @ other); re-run pre-flight")

    monkeypatch.setattr(modelinfo, "_load_model_config", _changed)
    res = client.post(f"/api/missions/{mid2}/retry", json={})
    assert res.status_code == 409
    assert "re-run" in res.json()["detail"]


def test_f1_resume_stays_keyless_discriminator(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    mid = client.post("/api/missions", json={"title": "F1 side"}).json()["id"]
    client.post(f"/api/missions/{mid}/start")
    client.post(f"/api/missions/{mid}/pause")
    assert client.post(f"/api/missions/{mid}/resume").status_code == 200
    resumed = [e for e in _events(mid) if e["type"] == "mission_resumed"]
    assert len(resumed) == 1
    assert "resumed_step" not in resumed[0]["data"]
    assert "retry_count" not in resumed[0]["data"]
    assert "status" in resumed[0]["data"]  # F1 payload shape frozen


# -- T085: US3 reset during execution ----------------------------------------


def test_reset_during_execution_no_orphan(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_executor(monkeypatch, FakeExecutor({"researcher": StepScript(delay=5.0)}))
    client = _client()
    mid = client.post("/api/missions", json={"title": "Reset me"}).json()["id"]
    assert client.post(f"/api/missions/{mid}/run", json={}).status_code == 202
    run = runner_mod.get_active(mid)
    assert run is not None and run.alive

    reset_at = _events(mid)[-1]["id"]
    assert client.post(f"/api/missions/{mid}/reset").status_code == 200
    _join_run(mid, timeout=2.0)

    mission = client.get(f"/api/missions/{mid}").json()
    assert mission["status"] == "created"
    assert mission["agent_runs"] == []  # F5 run-scoped fields cleared (T090)
    assert mission["failed_step_id"] is None
    assert mission["retry_count"] == 0
    assert mission["resolved_model"] is None
    assert mission["objective"] is None
    assert mission["quota_note"] is None
    # No further agent events after the reset (cancel stopped the step).
    after = [e for e in _events(mid) if e["id"] > reset_at]
    assert not [e for e in after if e["type"] in AGENT_TOOL_TYPES]
    assert not run.alive  # no orphan execution


# -- T078: CLI terminal path (quickstart Flow 2, stubbed) ---------------------


def test_cli_run_and_status_stubbed_flow2(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from backend.app import cli

    _use_executor(monkeypatch, _happy_executor())
    code = cli.main(["run", "What should a tiny team know before adopting agents?"])
    out = capsys.readouterr().out
    assert code == 0
    # Every event printed as `<seq> <type> <json data>` live, in order.
    printed = [
        line.split(" ", 2) for line in out.splitlines() if line[:1].isdigit()
    ]
    printed_types = [parts[1] for parts in printed]
    assert printed_types[0] == "mission_created"
    assert printed_types[1] == "mission_started"
    assert [t for t in printed_types if t == "agent_started"] == [
        "agent_started",
    ] * 3
    assert printed_types.index("mission_completed") == len(printed_types) - 1
    # The printed result is the Summarizer's real output (SC-005).
    assert "result:" in out
    assert SUMMARY_OUTPUT in out

    # `status <id>` shows the three runs with task_input/output + resolved model.
    from backend.app.missions.controller import get_controller

    mission = get_controller().list()[0]
    capsys.readouterr()
    assert cli.main(["status", mission.id]) == 0
    status_out = capsys.readouterr().out
    assert RESEARCH_OUTPUT in status_out
    assert CRITIC_OUTPUT in status_out
    assert SUMMARY_OUTPUT in status_out
    assert "researcher" in status_out and "summarizer" in status_out


def test_cli_rejects_overlong_topic_exit_2(capsys) -> None:
    from backend.app import cli

    code = cli.main(["run", "x" * 501])
    assert code == 2
    err = capsys.readouterr().err
    assert "500 characters or fewer" in err
    assert "no mission created" in err
    from backend.app.missions.controller import get_controller

    assert get_controller().list() == []
