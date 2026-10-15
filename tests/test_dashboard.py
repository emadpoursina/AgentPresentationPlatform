"""F4: presenter dashboard real-events-only (spec 003, T047/T049/T052).

Static contract (no browser needed) + API-shape availability:
- index.html has all six PRD 5.5 sections + banner + real-only labels.
- app.js subscribes to every EVENT_TYPES member, uses textContent-only,
  keeps exact banner copy and Last-Event-ID replay wiring.
- Existing read APIs expose every field the dashboard consumes.
F1-F3 behavior is regression-only (see T058); nothing here re-tests it.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.events import EVENT_TYPES
from backend.app.main import app

STATIC_DIR = Path(__file__).resolve().parents[1] / "frontend" / "static"


def _fresh_client():
    from backend.app.events.store import event_store
    from backend.app.missions.controller import controller as missions
    from backend.app.participants.controller import controller as participants
    from backend.app.polls.controller import controller as polls

    missions.clear()
    participants.clear()
    polls.clear()
    event_store.clear()
    return TestClient(app)


def _html() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


def _js() -> str:
    return (STATIC_DIR / "app.js").read_text(encoding="utf-8")


# -- US1: header/result contract (T047) ----------------------------------------


def test_dashboard_sections_present() -> None:
    html = _html()
    for section_id in ("mission", "agents", "tools", "handoffs", "influence", "result"):
        assert f'id="{section_id}"' in html, f"missing section #{section_id}"
    assert 'id="events"' in html  # raw log retained as source of truth
    assert 'id="conn"' in html
    assert 'id="presence-count"' in html


def test_dashboard_real_only_labels_present() -> None:
    html = _html().lower()
    assert "real events only" in html
    assert "workflow position only" in html


def test_dashboard_progress_and_result_elements_present() -> None:
    html = _html()
    assert 'id="mission-progress"' in html
    assert 'id="mission-progress-bar"' in html
    assert 'id="result-summary"' in html
    assert 'id="result-outcome"' in html


def test_mission_api_exposes_dashboard_fields() -> None:
    client = _fresh_client()
    mid = client.post("/api/missions", json={"title": "Dash F4"}).json()["id"]
    client.post(f"/api/missions/{mid}/start")
    m = client.get(f"/api/missions/{mid}").json()
    for field in (
        "title",
        "status",
        "steps",
        "current_step_index",
        "result_summary",
        "outcome",
        "error",
        "branch_context",
    ):
        assert field in m, f"mission missing {field}"
    # Honest workflow-position progress is derivable client-side from
    # status/steps/index (matches Mission.progress: terminal → 1.0).
    assert isinstance(m["steps"], list) and len(m["steps"]) == 3
    assert m["current_step_index"] == 0
    assert m["branch_context"]["applied_decisions"] == []


def test_complete_vs_fail_outcome_distinct() -> None:
    client = _fresh_client()
    ok_id = client.post("/api/missions", json={"title": "OK"}).json()["id"]
    client.post(f"/api/missions/{ok_id}/start")
    done = client.post(
        f"/api/missions/{ok_id}/complete", json={"summary": "ok", "outcome": "success"}
    ).json()
    assert done["outcome"] == "success"

    fail_id = client.post("/api/missions", json={"title": "Bad"}).json()["id"]
    client.post(f"/api/missions/{fail_id}/start")
    failed = client.post(f"/api/missions/{fail_id}/fail", json={"error": "boom"}).json()
    assert failed["outcome"] == "failed"
    assert failed["error"] == "boom"
    assert failed["outcome"] != done["outcome"]


# -- US2: agent/tool readiness (T049) ------------------------------------------


def test_agent_tool_handoff_sections_and_empty_states() -> None:
    html = _html()
    for list_id in ("agents-list", "tools-list", "handoffs-list"):
        assert f'id="{list_id}"' in html, f"missing #{list_id}"
    lowered = html.lower()
    assert "no agent activity yet" in lowered
    assert "no tool activity yet" in lowered
    assert "no handoffs yet" in lowered


def test_canonical_agent_tool_types_exist() -> None:
    for name in (
        "agent_started",
        "tool_started",
        "tool_completed",
        "agent_handoff",
        "agent_completed",
        "agent_failed",
    ):
        assert name in EVENT_TYPES


def test_dashboard_subscribes_to_all_event_types() -> None:
    js = _js()
    for name in EVENT_TYPES:
        assert name in js, f"app.js missing subscription for {name}"


def test_dashboard_renders_textcontent_only() -> None:
    js = _js()
    assert "textContent" in js
    assert "innerHTML" not in js  # untrusted data must never be HTML


def test_agent_tool_events_flow_through_history() -> None:
    """F5 contract: canonical agent/tool events appended server-side appear
    in history with timestamp + mission ref for the dashboard reducer."""
    from backend.app.events.store import event_store

    client = _fresh_client()
    mid = client.post("/api/missions", json={"title": "Agents"}).json()["id"]
    client.post(f"/api/missions/{mid}/start")
    event_store.append("agent_started", mid, {"agent_id": "r1", "profile": "researcher"})
    event_store.append("tool_started", mid, {"tool_name": "browser", "action": "open"})
    event_store.append(
        "tool_completed", mid, {"tool_name": "browser", "status": "ok", "summary": "done"}
    )
    event_store.append(
        "agent_handoff",
        mid,
        {"from_agent": "researcher", "to_agent": "critic", "reason": "review"},
    )
    history = client.get(f"/api/missions/{mid}/events").json()["events"]
    by_type = {e["type"] for e in history}
    assert {"agent_started", "tool_started", "tool_completed", "agent_handoff"} <= by_type
    for e in history:
        assert e["mission_id"] == mid
        assert e["timestamp"]


# -- US3: influence + stream trust (T052) --------------------------------------


def test_influence_section_and_branch_labels() -> None:
    html = _html()
    assert 'id="influence' in html
    lowered = html.lower()
    assert "audience influence" in lowered
    assert "branch" in lowered
    assert "outcome" in lowered


def test_poll_and_branch_fields_available() -> None:
    client = _fresh_client()
    mid = client.post("/api/missions", json={"title": "Influence"}).json()["id"]
    client.post(f"/api/missions/{mid}/start")
    pid = client.post(
        f"/api/missions/{mid}/polls",
        json={
            "question": "Which way?",
            "options": [
                {"id": "a", "label": "A", "branch_instruction": "Do A next."},
                {"id": "b", "label": "B", "branch_instruction": "Do B next."},
            ],
        },
    ).json()["id"]
    joined = client.post("/api/participants/join", json={"display_name": "Ann"}).json()[
        "id"
    ]
    client.post(
        f"/api/missions/{mid}/polls/{pid}/vote",
        json={"participant_id": joined, "option_id": "a"},
    )
    client.post(f"/api/missions/{mid}/polls/{pid}/close")
    current = client.get(f"/api/missions/{mid}/polls/current").json()
    assert current == {"poll": None}  # completed polls leave no current poll
    mission = client.get(f"/api/missions/{mid}").json()
    assert mission["branch_context"]["current_branch_instruction"] == "Do A next."
    assert mission["branch_context"]["applied_decisions"][0]["winning_option_id"] == "a"
    types = [e["type"] for e in client.get(f"/api/missions/{mid}/events").json()["events"]]
    assert "audience_decision_applied" in types


def test_stream_trust_wiring_present() -> None:
    js = _js()
    # Exact banner copy (PRD 10 disconnected state).
    assert "Connected — live." in js
    assert "Disconnected — showing last known state, not live." in js
    # SSE replay wiring.
    assert "lastEventId" in js
    assert "Last-Event-ID" in js or "lastEventId" in js
    assert "EventSource" in js
    assert "retry: 3000" in js or "retry" in js
    # Poll/decision handling + malformed-row guard.
    for name in (
        "poll_opened",
        "vote_recorded",
        "poll_closing",
        "poll_closed",
        "audience_decision_applied",
    ):
        assert name in js, f"app.js missing influence event {name}"
    assert "JSON.parse" in js
