"""T070: the single real end-to-end serial mission (double-gated, FR-023).

Opt-in only — requires BOTH the registered `real_e2e` marker and
`F5_REAL_E2E=1`, so the default `uv run pytest -q` gate never touches the
model. Running this test consumes real monthly quota (three Hermes steps);
it is executed at most once per implementation iteration.

The test drives the exact production path: gates (model pin + quota,
confirmed via the env flag) -> mission create/start -> `run_mission_sync`
with the real `HermesCliExecutor` -> persisted events + mission record.
"""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.real_e2e,
    pytest.mark.skipif(
        os.environ.get("F5_REAL_E2E") != "1",
        reason="real end-to-end mission is opt-in: set F5_REAL_E2E=1",
    ),
]

AGENT_TOOL_TYPES = {
    "agent_started",
    "tool_started",
    "tool_completed",
    "agent_handoff",
    "agent_completed",
    "agent_failed",
}


def test_real_serial_mission_end_to_end() -> None:
    from backend.app.agents.runner import run_mission_sync, run_preflight
    from backend.app.events.store import event_store
    from backend.app.missions.controller import get_controller
    from backend.app.missions.models import CreateMissionRequest, MissionStatus

    ctrl = get_controller()
    ctrl.clear()
    event_store.clear()

    # Pre-flight gates: real `hermes config get model` + `hermes usage`.
    # The F5_REAL_E2E=1 flag is the operator's low-quota confirmation (FR-024).
    resolved_model, quota_note = run_preflight(confirm_low_quota=True)

    mission = ctrl.create(
        CreateMissionRequest(title="What should a tiny team know before adopting agents?")
    )
    ctrl.record_run_context(
        mission.id,
        objective=mission.title,
        resolved_model=resolved_model,
        quota_note=quota_note,
    )
    ctrl.start(mission.id)

    run_mission_sync(mission.id)

    stored = ctrl.get(mission.id)
    events = event_store.list(mission_id=mission.id, after_id=0, limit=500)
    types = [e["type"] for e in events]
    agent_events = [e for e in events if e["type"] in AGENT_TOOL_TYPES]

    # SC-001: three distinct, ordered agent executions.
    started = [e for e in events if e["type"] == "agent_started"]
    assert [e["data"]["profile"] for e in started] == ["researcher", "critic", "summarizer"]
    assert types.count("agent_started") == 3
    assert types.count("agent_completed") == 3
    assert types.count("agent_handoff") == 2

    # SC-002: real handoff contents, programmatically composed.
    records = {r.profile: r for r in stored.agent_runs}
    assert all(r.status == "completed" for r in records.values())
    assert records["researcher"].output in records["critic"].task_input
    assert records["researcher"].output in records["summarizer"].task_input
    assert records["critic"].output in records["summarizer"].task_input

    # SC-009: resolved model recorded from the runtime value.
    assert stored.resolved_model == resolved_model
    assert "muse-spark-1.3-contributor" in stored.resolved_model
    assert stored.quota_note is not None

    # Mission completed honestly with the Summarizer's real output.
    assert stored.status is MissionStatus.COMPLETED
    assert stored.result_summary == records["summarizer"].output[:5000]
    assert stored.outcome == "success"
    assert "mission_completed" in types
    assert "mission_failed" not in types

    # Least privilege in the real run: tool-free steps never emit tool events.
    tool_free_tools = [
        e
        for e in agent_events
        if e["type"] in ("tool_started", "tool_completed")
        and e["data"].get("step_id") != "research"
    ]
    assert tool_free_tools == []
    # Every agent/tool event maps 1:1 to a real execution (SC-004).
    assert len(agent_events) == 3 + 3 + 2 + len(
        [e for e in agent_events if e["type"] in ("tool_started", "tool_completed")]
    )
