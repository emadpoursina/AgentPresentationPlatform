"""F3: polls/voting/decision-applied branch (spec 002, T023/T028/T034/T038).

Covers US1 votes, US2 lifecycle, US3 real branch, US4 reveal modes.
F1/F2 setup (mission start, participant join) is reused, not re-tested.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("PLAYGROUND_PRESENTER_TOKEN", raising=False)


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


def _running_mission(client):
    mid = client.post("/api/missions", json={"title": "Poll night"}).json()["id"]
    started = client.post(f"/api/missions/{mid}/start").json()
    assert started["status"] == "running"
    return mid


def _join(client, name="Ann"):
    return client.post("/api/participants/join", json={"display_name": name}).json()["id"]


def _options(*ids, branches=None):
    out = []
    for i in ids:
        opt = {"id": i, "label": f"Label {i}"}
        if branches and i in branches:
            opt["branch_instruction"] = branches[i]
        elif branches:
            opt["branch_instruction"] = f"Do {i} next."
        out.append(opt)
    return out


def _open(client, mid, options=None, **kw):
    body = {
        "question": kw.pop("question", "Which direction next?"),
        "options": options if options is not None else _options("a", "b", "c"),
        "deadline_seconds": kw.pop("deadline_seconds", 120),
        "reveal_mode": kw.pop("reveal_mode", "live"),
        **kw,
    }
    return client.post(f"/api/missions/{mid}/polls", json=body)


def _events(client, mid):
    return client.get(f"/api/missions/{mid}/events").json()["events"]


def _types(client, mid):
    return [e["type"] for e in _events(client, mid)]


def _expire(poll_id):
    """Force a deadline in the past so the next read path sweeps it shut."""
    from backend.app.polls.controller import controller as polls
    from backend.app.polls.models import utcnow

    poll = polls.get(poll_id)
    poll.deadline_at = utcnow() - timedelta(seconds=1)
    return poll


# -- US1: vote in an open poll (T023) -----------------------------------------


def test_vote_cast_and_change_replaces() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    b = _join(client, "Bo")
    pid = _open(client, mid).json()["id"]

    assert client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                       json={"participant_id": a, "option_id": "a"}).status_code == 200
    assert client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                       json={"participant_id": b, "option_id": "b"}).status_code == 200
    # A changes before close: tally must credit only the latest choice.
    changed = client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                          json={"participant_id": a, "option_id": "b"}).json()
    assert changed["tally"] == {"a": 0, "b": 2, "c": 0}
    assert changed["total_votes"] == 2


def test_same_option_retry_idempotent_no_new_event() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    pid = _open(client, mid).json()["id"]
    url = f"/api/missions/{mid}/polls/{pid}/vote"

    first = client.post(url, json={"participant_id": a, "option_id": "a"}).json()
    before = [e for e in _events(client, mid) if e["type"] == "vote_recorded"]
    second = client.post(url, json={"participant_id": a, "option_id": "a"}).json()
    after = [e for e in _events(client, mid) if e["type"] == "vote_recorded"]
    assert second["tally"] == first["tally"] == {"a": 1, "b": 0, "c": 0}
    assert len(after) == len(before)  # no duplicate event, no double count


def test_reject_unknown_participant_404_tally_unchanged() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    pid = _open(client, mid).json()["id"]
    client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                json={"participant_id": a, "option_id": "a"})
    res = client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                      json={"participant_id": "nope", "option_id": "b"})
    assert res.status_code == 404
    current = client.get(f"/api/missions/{mid}/polls/current").json()["poll"]
    assert current["tally"] == {"a": 1, "b": 0, "c": 0}


def test_reject_departed_and_timed_out_voters() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    gone = _join(client, "Gone")
    stale = _join(client, "Stale")
    pid = _open(client, mid).json()["id"]
    url = f"/api/missions/{mid}/polls/{pid}/vote"

    client.post(f"/api/participants/{gone}/leave")
    assert client.post(url, json={"participant_id": gone, "option_id": "a"}).status_code == 403

    # Age one voter past the presence timeout: post-sweep they are not connected.
    from backend.app.participants.controller import controller as participants

    participants.get(stale).last_seen_at -= timedelta(seconds=3600)
    assert client.post(url, json={"participant_id": stale, "option_id": "a"}).status_code == 403

    assert client.post(url, json={"participant_id": a, "option_id": "a"}).status_code == 200
    current = client.get(f"/api/missions/{mid}/polls/current").json()["poll"]
    assert current["total_votes"] == 1


def test_reject_unknown_option_400_tally_unchanged() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    pid = _open(client, mid).json()["id"]
    url = f"/api/missions/{mid}/polls/{pid}/vote"
    client.post(url, json={"participant_id": a, "option_id": "a"})

    res = client.post(url, json={"participant_id": a, "option_id": "write-in"})
    assert res.status_code == 400
    current = client.get(f"/api/missions/{mid}/polls/current").json()["poll"]
    assert current["tally"] == {"a": 1, "b": 0, "c": 0}
    assert current["total_votes"] == 1  # prior vote stands


def test_reject_malformed_payloads_400() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    pid = _open(client, mid).json()["id"]
    url = f"/api/missions/{mid}/polls/{pid}/vote"

    assert client.post(url).status_code == 400  # empty body
    assert client.post(url, content="not json",
                       headers={"Content-Type": "application/json"}).status_code == 400
    assert client.post(url, json=["a", "b"]).status_code == 400  # not an object
    assert client.post(url, json={}).status_code == 400  # missing keys
    assert client.post(url, json={"participant_id": a}).status_code == 400
    assert client.post(url, json={"participant_id": 123, "option_id": "a"}).status_code == 400
    assert client.post(url, json={"participant_id": a, "option_id": 123}).status_code == 400
    current = client.get(f"/api/missions/{mid}/polls/current").json()["poll"]
    assert current["total_votes"] == 0


def test_reject_vote_after_completed_close_409() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    pid = _open(client, mid).json()["id"]
    url = f"/api/missions/{mid}/polls/{pid}/vote"
    client.post(url, json={"participant_id": a, "option_id": "a"})
    client.post(f"/api/missions/{mid}/polls/{pid}/close")

    res = client.post(url, json={"participant_id": a, "option_id": "b"})
    assert res.status_code == 409
    current = client.get(f"/api/missions/{mid}/polls/current").json()
    assert current == {"poll": None}
    history = [e for e in _events(client, mid) if e["type"] == "poll_closed"]
    assert history[0]["data"]["final_counts"] == {"a": 1, "b": 0, "c": 0}


def test_double_tap_converges_to_single_count() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    pid = _open(client, mid).json()["id"]
    url = f"/api/missions/{mid}/polls/{pid}/vote"

    for _ in range(3):  # rapid double-tap on the same option
        assert client.post(url, json={"participant_id": a, "option_id": "a"}).status_code == 200
    assert client.post(url, json={"participant_id": a, "option_id": "b"}).status_code == 200
    current = client.get(f"/api/missions/{mid}/polls/current").json()["poll"]
    assert current["tally"] == {"a": 0, "b": 1, "c": 0}


# -- US2: presenter runs the lifecycle (T028) ----------------------------------


def test_open_validation_rejects() -> None:
    client = _fresh_client()
    mid = _running_mission(client)

    assert _open(client, mid, _options("solo")).status_code == 400  # <2 options
    assert _open(client, mid, _options(*[f"o{i}" for i in range(7)])).status_code == 400  # >6
    assert _open(client, mid, question="   ").status_code == 400  # blank question
    assert _open(client, mid, question="x" * 201).status_code == 400
    dupes = [{"id": "a", "label": "One"}, {"id": "a", "label": "Two"}]
    assert _open(client, mid, dupes).status_code == 400  # duplicate ids
    assert _open(client, mid, deadline_seconds=5).status_code == 400
    assert _open(client, mid, deadline_seconds=9999).status_code == 400
    assert _open(client, mid, reveal_mode="secret").status_code == 400
    assert "poll" not in _types(client, mid) or "poll_opened" not in _types(client, mid)

    good = _open(client, mid)
    assert good.status_code == 201
    assert _open(client, mid).status_code == 409  # second open rejected


def test_open_requires_running_mission() -> None:
    client = _fresh_client()
    created = client.post("/api/missions", json={"title": "Idle"}).json()["id"]
    assert _open(client, created).status_code == 409  # created, not running
    assert _open(client, "missing").status_code == 404


def test_deadline_auto_close_outright_winner() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    pid = _open(client, mid, deadline_seconds=10).json()["id"]
    client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                json={"participant_id": a, "option_id": "a"})
    _expire(pid)

    current = client.get(f"/api/missions/{mid}/polls/current").json()
    assert current == {"poll": None}  # completed polls leave no current poll
    types = _types(client, mid)
    assert "poll_closed" in types
    closed = [e for e in _events(client, mid) if e["type"] == "poll_closed"][0]
    assert closed["data"]["winning_option_id"] == "a"
    assert closed["data"]["decided_by"] == "tally"
    # Late arrival after the sweep is rejected.
    late = client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                       json={"participant_id": a, "option_id": "b"})
    assert late.status_code == 409


def test_deadline_tie_goes_to_closing_for_resolve() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    b = _join(client, "Bo")
    pid = _open(client, mid, _options("a", "b"), deadline_seconds=10).json()["id"]
    client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                json={"participant_id": a, "option_id": "a"})
    client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                json={"participant_id": b, "option_id": "b"})
    _expire(pid)

    current = client.get(f"/api/missions/{mid}/polls/current").json()["poll"]
    assert current["state"] == "closing"
    vote = client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                       json={"participant_id": a, "option_id": "a"})
    assert vote.status_code == 409  # voting already stopped in closing
    resolved = client.post(f"/api/missions/{mid}/polls/{pid}/resolve",
                           json={"winning_option_id": "b"}).json()
    assert resolved["state"] == "completed"
    assert resolved["outcome"]["decided_by"] == "presenter_tiebreak"


def test_early_close_stops_votes_immediately() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    b = _join(client, "Bo")
    pid = _open(client, mid).json()["id"]
    client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                json={"participant_id": a, "option_id": "a"})
    closed = client.post(f"/api/missions/{mid}/polls/{pid}/close").json()
    assert closed["state"] == "completed"  # outright winner completes at once

    late = client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                       json={"participant_id": b, "option_id": "b"})
    assert late.status_code == 409
    again = client.post(f"/api/missions/{mid}/polls/{pid}/close")
    assert again.status_code == 409  # already completed


def test_tiebreak_must_be_among_tied() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    b = _join(client, "Bo")
    pid = _open(client, mid, _options("a", "b", "c")).json()["id"]
    client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                json={"participant_id": a, "option_id": "a"})
    client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                json={"participant_id": b, "option_id": "b"})
    assert client.post(f"/api/missions/{mid}/polls/{pid}/close").json()["state"] == "closing"

    bad = client.post(f"/api/missions/{mid}/polls/{pid}/resolve",
                      json={"winning_option_id": "c"})
    assert bad.status_code == 400  # not among the tied options
    bad2 = client.post(f"/api/missions/{mid}/polls/{pid}/resolve",
                       json={"winning_option_id": "zzz"})
    assert bad2.status_code == 400
    ok = client.post(f"/api/missions/{mid}/polls/{pid}/resolve",
                     json={"winning_option_id": "a"}).json()
    assert ok["outcome"] == {"winning_option_id": "a", "decided_by": "presenter_tiebreak"}


def test_zero_vote_fallback_records_presenter_choice() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    pid = _open(client, mid).json()["id"]
    assert client.post(f"/api/missions/{mid}/polls/{pid}/close").json()["state"] == "closing"

    done = client.post(f"/api/missions/{mid}/polls/{pid}/resolve",
                       json={"winning_option_id": "c"}).json()
    assert done["state"] == "completed"
    assert done["outcome"] == {"winning_option_id": "c", "decided_by": "presenter_fallback"}
    assert done["tally"] == {"a": 0, "b": 0, "c": 0}
    applied = [e for e in _events(client, mid) if e["type"] == "audience_decision_applied"]
    assert applied and applied[0]["data"]["decided_by"] == "presenter_fallback"


def test_outright_winner_needs_no_resolve() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    pid = _open(client, mid, _options("a", "b")).json()["id"]
    client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                json={"participant_id": a, "option_id": "b"})
    assert client.post(f"/api/missions/{mid}/polls/{pid}/close").json()["outcome"] == {
        "winning_option_id": "b", "decided_by": "tally"}
    assert client.post(f"/api/missions/{mid}/polls/{pid}/resolve",
                       json={"winning_option_id": "b"}).status_code == 409


def test_current_poll_view_hides_branch_instructions() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    opened = _open(client, mid, _options("a", "b", branches={"a": "Secret A", "b": "Secret B"}))
    assert opened.status_code == 201
    view = opened.json()
    assert all(set(o.keys()) == {"id", "label"} for o in view["options"])
    dumped = opened.text
    assert "Secret A" not in dumped and "Secret B" not in dumped


def test_second_open_rejected_while_closing() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    b = _join(client, "Bo")
    pid = _open(client, mid, _options("a", "b")).json()["id"]
    client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                json={"participant_id": a, "option_id": "a"})
    client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                json={"participant_id": b, "option_id": "b"})
    client.post(f"/api/missions/{mid}/polls/{pid}/close")
    assert _open(client, mid, _options("a", "b")).status_code == 409


def test_presenter_token_gate(monkeypatch) -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    monkeypatch.setenv("PLAYGROUND_PRESENTER_TOKEN", "demo-secret")

    assert _open(client, mid).status_code == 403  # missing token
    wrong = client.post(f"/api/missions/{mid}/polls", json={
        "question": "Q?", "options": _options("a", "b")},
        headers={"X-Presenter-Token": "wrong"})
    assert wrong.status_code == 403
    ok = client.post(f"/api/missions/{mid}/polls", json={
        "question": "Q?", "options": _options("a", "b")},
        headers={"X-Presenter-Token": "demo-secret"})
    assert ok.status_code == 201
    pid = ok.json()["id"]
    # Audience votes stay ungated even with a token configured.
    a = _join(client, "Ann")
    assert client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                       json={"participant_id": a, "option_id": "a"}).status_code == 200
    assert client.post(f"/api/missions/{mid}/polls/{pid}/close").status_code == 403
    assert client.post(f"/api/missions/{mid}/polls/{pid}/close",
                       headers={"X-Presenter-Token": "demo-secret"}).status_code == 200


# -- US3: winning choice drives a real branch (T034) ---------------------------


def test_decision_applied_patches_branch_context() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    branches = {"deep": "Critic verifies cited sources.",
                "wide": "Critic finds counterarguments."}
    pid = _open(client, mid, _options("deep", "wide", branches=branches)).json()["id"]
    client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                json={"participant_id": a, "option_id": "deep"})
    client.post(f"/api/missions/{mid}/polls/{pid}/close")

    mission = client.get(f"/api/missions/{mid}").json()
    assert mission["branch_context"]["current_branch_instruction"] == \
        "Critic verifies cited sources."
    assert mission["branch_context"]["applied_decisions"][0]["winning_option_id"] == "deep"
    assert mission["branch_context"]["applied_decisions"][0]["decided_by"] == "tally"
    assert mission["steps"][mission["current_step_index"]]["description"] == \
        "Critic verifies cited sources."


def test_two_winners_produce_two_different_next_steps() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    branches = {"deep": "Critic verifies cited sources.",
                "wide": "Critic finds counterarguments."}

    p1 = _open(client, mid, _options("deep", "wide", branches=branches)).json()["id"]
    client.post(f"/api/missions/{mid}/polls/{p1}/vote",
                json={"participant_id": a, "option_id": "deep"})
    client.post(f"/api/missions/{mid}/polls/{p1}/close")
    first = client.get(f"/api/missions/{mid}").json()["branch_context"]

    p2 = _open(client, mid, _options("deep", "wide", branches=branches)).json()["id"]
    client.post(f"/api/missions/{mid}/polls/{p2}/vote",
                json={"participant_id": a, "option_id": "wide"})
    client.post(f"/api/missions/{mid}/polls/{p2}/close")
    second = client.get(f"/api/missions/{mid}").json()["branch_context"]

    assert first["current_branch_instruction"] == "Critic verifies cited sources."
    assert second["current_branch_instruction"] == "Critic finds counterarguments."
    assert first["current_branch_instruction"] != second["current_branch_instruction"]
    assert len(second["applied_decisions"]) == 2


def test_event_history_sequence_with_timestamps_and_mission_ids() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    b = _join(client, "Bo")
    pid = _open(client, mid, _options("a", "b")).json()["id"]
    client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                json={"participant_id": a, "option_id": "a"})
    client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                json={"participant_id": b, "option_id": "b"})
    client.post(f"/api/missions/{mid}/polls/{pid}/close")
    client.post(f"/api/missions/{mid}/polls/{pid}/resolve",
                json={"winning_option_id": "a"})

    poll_types = [e for e in _events(client, mid)
                  if e["type"] in ("poll_opened", "vote_recorded",
                                   "poll_closed", "audience_decision_applied")]
    assert [e["type"] for e in poll_types] == [
        "poll_opened", "vote_recorded", "vote_recorded",
        "poll_closed", "audience_decision_applied"]
    for e in poll_types:
        assert e["mission_id"] == mid
        assert e["timestamp"]
        assert e["data"].get("poll_id") == pid
    applied = poll_types[-1]
    assert applied["data"]["winning_option_id"] == "a"
    assert applied["data"]["decided_by"] == "presenter_tiebreak"
    assert applied["data"]["next_step"]
    # No fabricated entries: every dashboard event came from a real transition.
    assert len([e for e in poll_types if e["type"] == "vote_recorded"]) == 2


# -- US4: live vs controlled reveal (T038) --------------------------------------


def test_live_vote_recorded_carries_counts_without_ballots() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    pid = _open(client, mid, _options("a", "b"), reveal_mode="live").json()["id"]
    client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                json={"participant_id": a, "option_id": "a"})

    recorded = [e for e in _events(client, mid) if e["type"] == "vote_recorded"]
    assert len(recorded) == 1
    assert recorded[0]["data"]["counts"] == {"a": 1, "b": 0}
    assert recorded[0]["data"]["total"] == 1
    blob = str(recorded[0]["data"])
    assert a not in blob  # per-voter choices never leave the server


def test_controlled_hides_counts_until_close() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    b = _join(client, "Bo")
    pid = _open(client, mid, _options("a", "b"), reveal_mode="controlled").json()["id"]
    client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                json={"participant_id": a, "option_id": "a"})
    client.post(f"/api/missions/{mid}/polls/{pid}/vote",
                json={"participant_id": b, "option_id": "b"})

    recorded = [e for e in _events(client, mid) if e["type"] == "vote_recorded"]
    assert len(recorded) == 2
    assert all("counts" not in e["data"] for e in recorded)
    assert all(e["data"]["total"] == n for e, n in zip(recorded, (1, 2), strict=True))

    pre = client.get(f"/api/missions/{mid}/polls/current").json()["poll"]
    assert pre["tally"] is None  # counts hidden pre-close
    assert pre["total_votes"] == 2
    assert pre["reveal_mode"] == "controlled"

    done = client.post(f"/api/missions/{mid}/polls/{pid}/close").json()
    assert done["state"] == "closing"  # tie awaits presenter resolve
    resolved = client.post(f"/api/missions/{mid}/polls/{pid}/resolve",
                           json={"winning_option_id": "a"}).json()
    assert resolved["tally"] == {"a": 1, "b": 1}  # identical counting rules
    closed = [e for e in _events(client, mid) if e["type"] == "poll_closed"][0]
    assert closed["data"]["final_counts"] == {"a": 1, "b": 1}


def test_reveal_mode_echoed_and_counting_identical() -> None:
    client = _fresh_client()
    mid = _running_mission(client)
    a = _join(client, "Ann")
    live = _open(client, mid, _options("a", "b"), reveal_mode="live").json()
    assert live["reveal_mode"] == "live"
    assert live["tally"] == {"a": 0, "b": 0}
    client.post(f"/api/missions/{mid}/polls/{live['id']}/vote",
                json={"participant_id": a, "option_id": "a"})
    client.post(f"/api/missions/{mid}/polls/{live['id']}/close")
    closed_live = [e for e in _events(client, mid) if e["type"] == "poll_closed"][-1]
    assert closed_live["data"]["final_counts"] == {"a": 1, "b": 0}
