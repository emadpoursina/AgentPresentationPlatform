"""F1: mission controller state machine + reset + failure≠success."""

from fastapi.testclient import TestClient

from backend.app.main import app


def _fresh_client():
    # Reset singletons between tests (in-memory F1 store).
    from backend.app.events.store import event_store
    from backend.app.missions.controller import controller

    controller.clear()
    event_store.clear()
    return TestClient(app)


def test_start_and_reset_acceptance_13_2() -> None:
    client = _fresh_client()
    created = client.post("/api/missions", json={"title": "Demo"}).json()
    assert created["status"] == "created"

    started = client.post(f"/api/missions/{created['id']}/start").json()
    assert started["status"] == "running"

    reset = client.post(f"/api/missions/{created['id']}/reset").json()
    assert reset["status"] == "created"
    assert reset["error"] is None
    assert reset["result_summary"] is None


def test_full_lifecycle_pause_resume_complete() -> None:
    client = _fresh_client()
    mid = client.post("/api/missions", json={"title": "Lifecycle"}).json()["id"]
    assert client.post(f"/api/missions/{mid}/start").json()["status"] == "running"
    assert client.post(f"/api/missions/{mid}/pause").json()["status"] == "paused"
    assert client.post(f"/api/missions/{mid}/resume").json()["status"] == "running"
    done = client.post(
        f"/api/missions/{mid}/complete", json={"summary": "ok", "outcome": "success"}
    ).json()
    assert done["status"] == "completed"
    assert done["outcome"] == "success"


def test_failure_is_not_success_acceptance_13_9() -> None:
    client = _fresh_client()
    mid = client.post("/api/missions", json={"title": "Fail"}).json()["id"]
    client.post(f"/api/missions/{mid}/start")
    failed = client.post(f"/api/missions/{mid}/fail", json={"error": "boom"}).json()
    assert failed["status"] == "failed"
    assert failed["outcome"] == "failed"
    assert failed["error"] == "boom"

    history = client.get(f"/api/missions/{mid}/events").json()
    types = [e["type"] for e in history["events"]]
    assert "mission_failed" in types
    assert "mission_completed" not in types


def test_illegal_transitions_are_409() -> None:
    client = _fresh_client()
    mid = client.post("/api/missions", json={"title": "Bad"}).json()["id"]
    # pause before start
    assert client.post(f"/api/missions/{mid}/pause").status_code == 409
    # complete before start
    assert (
        client.post(f"/api/missions/{mid}/complete", json={"summary": "x"}).status_code
        == 409
    )
    # double start
    client.post(f"/api/missions/{mid}/start")
    assert client.post(f"/api/missions/{mid}/start").status_code == 409
    # unknown mission
    assert client.post("/api/missions/nope/start").status_code == 404


def test_title_validation() -> None:
    client = _fresh_client()
    assert client.post("/api/missions", json={"title": "   "}).status_code == 422
