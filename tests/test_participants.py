"""F2: join + QR + presence (PRD 5.1, acceptance #1)."""

from datetime import timedelta

from fastapi.testclient import TestClient

from backend.app.events import EVENT_TYPES
from backend.app.main import app

JOIN_URL = "http://192.168.1.5:8000"


def _fresh_client(monkeypatch):
    from backend.app.events.store import event_store
    from backend.app.missions.controller import controller as missions
    from backend.app.participants.controller import controller as participants

    missions.clear()
    participants.clear()
    event_store.clear()
    monkeypatch.setenv("PLAYGROUND_JOIN_URL", JOIN_URL)
    return TestClient(app)


def test_presence_event_types_registered() -> None:
    assert "participant_joined" in EVENT_TYPES
    assert "participant_left" in EVENT_TYPES


def test_join_info_reflects_current_url_and_qr(monkeypatch) -> None:
    client = _fresh_client(monkeypatch)
    info = client.get("/api/join-info").json()
    assert info["ready"] is True
    assert info["join_url"] == f"{JOIN_URL}/join.html"
    assert info["qr_url"] == "/api/join-info/qr"

    qr = client.get("/api/join-info/qr")
    assert qr.status_code == 200
    assert qr.headers["content-type"] == "image/png"
    assert qr.content[:8] == b"\x89PNG\r\n\x1a\n"

    # QR tracks the current address, never a stale one.
    monkeypatch.setenv("PLAYGROUND_JOIN_URL", "http://10.0.0.2:8000")
    qr2 = client.get("/api/join-info/qr")
    assert qr2.content != qr.content


def test_named_and_anonymous_join_counted(monkeypatch) -> None:
    client = _fresh_client(monkeypatch)
    named = client.post("/api/participants/join", json={"display_name": "Ada"}).json()
    assert named["display_name"] == "Ada"
    assert named["anonymous"] is False
    assert named["status"] == "connected"

    anon = client.post("/api/participants/join", json={}).json()
    assert anon["anonymous"] is True
    assert anon["display_name"] is None

    roster = client.get("/api/participants").json()
    assert roster["count"] == 2


def test_invalid_names_rejected_without_counting(monkeypatch) -> None:
    client = _fresh_client(monkeypatch)
    bad = ["", "   ", "x" * 31, "<script>alert(1)</script>", "party-🎉", "semi;colon"]
    for name in bad:
        res = client.post("/api/participants/join", json={"display_name": name})
        assert res.status_code == 400, name
        assert "detail" in res.json()
    assert client.get("/api/participants").json()["count"] == 0


def test_duplicate_names_stay_distinct(monkeypatch) -> None:
    client = _fresh_client(monkeypatch)
    first = client.post("/api/participants/join", json={"display_name": "Sam"}).json()
    second = client.post("/api/participants/join", json={"display_name": "Sam"}).json()
    assert first["id"] != second["id"]
    roster = client.get("/api/participants").json()
    assert roster["count"] == 2
    assert [p["display_name"] for p in roster["participants"]] == ["Sam", "Sam"]


def test_leave_decrements_and_rejoin_restores(monkeypatch) -> None:
    client = _fresh_client(monkeypatch)
    pid = client.post("/api/participants/join", json={"display_name": "Jo"}).json()["id"]
    assert client.get("/api/participants").json()["count"] == 1

    assert client.post(f"/api/participants/{pid}/leave").json()["status"] == "left"
    assert client.get("/api/participants").json()["count"] == 0
    # Idempotent: no second event, still 200.
    assert client.post(f"/api/participants/{pid}/leave").status_code == 200

    rejoined = client.post(f"/api/participants/{pid}/rejoin").json()
    assert rejoined["id"] == pid
    assert rejoined["status"] == "connected"
    assert client.get("/api/participants").json()["count"] == 1

    history = client.get("/api/events/history").json()["events"]
    joined = [e for e in history if e["type"] == "participant_joined"]
    left = [e for e in history if e["type"] == "participant_left"]
    assert len(joined) == 2 and all(e["mission_id"] == "session" for e in joined)
    assert len(left) == 1 and left[0]["data"]["reason"] == "left"


def test_heartbeat_and_unknown_ids(monkeypatch) -> None:
    client = _fresh_client(monkeypatch)
    pid = client.post("/api/participants/join", json={}).json()["id"]
    assert client.post(f"/api/participants/{pid}/heartbeat").status_code == 200
    assert client.post("/api/participants/nope/heartbeat").status_code == 404
    assert client.post("/api/participants/nope/leave").status_code == 404
    assert client.post("/api/participants/nope/rejoin").status_code == 404
    client.post(f"/api/participants/{pid}/leave")
    assert client.post(f"/api/participants/{pid}/heartbeat").status_code == 409


def test_timeout_sweep_demotes_stale_presence(monkeypatch) -> None:
    from backend.app.participants.controller import controller as participants
    from backend.app.participants.models import utcnow

    client = _fresh_client(monkeypatch)
    pid = client.post("/api/participants/join", json={"display_name": "Old"}).json()["id"]
    participants._participants[pid].last_seen_at = utcnow() - timedelta(seconds=3600)

    roster = client.get("/api/participants").json()
    assert roster["count"] == 0
    history = client.get("/api/events/history").json()["events"]
    timeouts = [
        e
        for e in history
        if e["type"] == "participant_left" and e["data"].get("reason") == "timeout"
    ]
    assert len(timeouts) == 1
