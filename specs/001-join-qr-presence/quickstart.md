# Quickstart: Join with QR Code and Presence (F2)

Validates F2 end to end. See [contracts/participants-api.md](contracts/participants-api.md) for endpoint shapes and [data-model.md](data-model.md) for rules.

## Prerequisites

- `uv sync --group dev`
- Server: `uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`
- Two HTTP clients (e.g. two phones, or phone + `curl`) on the same network.

## Scenarios

### 1. Join info is reachable and fresh

1. `GET /api/health` → `{"status": "ok"}`.
2. `GET /api/join-info` → `ready: true` and a `join_url` with a LAN host (not loopback).
3. Open `qr_url` twice, changing nothing — both scans decode to the same current `join_url`.
4. **Expected**: presentation page shows a scannable code plus the typed URL and setup notes.

### 2. Named and anonymous joins (acceptance §13 #1)

1. `POST /api/participants/join {"display_name": "Ada"}` → **201** with an opaque `id`.
2. `POST /api/participants/join {}` → **201**, `anonymous: true`, `display_name: null`.
3. `GET /api/participants` → `count: 2`.
4. **Expected**: presenter screen count reads 2 within seconds; each joiner sees a joined confirmation.

### 3. Invalid names rejected, count untouched

Each `POST /api/participants/join` → **400** with a clear `detail`, and `GET /api/participants` count unchanged:

- `{"display_name": ""}`, `{"display_name": "   "}`, 31-char name, `{"display_name": "<script>"}` (or emoji).
- **Expected**: 100% rejection per SC-005; no roster entries created.

### 4. Duplicates distinguished

1. Join twice with `{"display_name": "Sam"}` from two clients → two **201**s with different ids.
2. `GET /api/participants` → both listed, `count` increased by 2.
3. **Expected**: no merged identities.

### 5. Live count decrements (clarified behavior)

1. With count at N, `POST /api/participants/{id}/leave` → **200**; count becomes N−1 within seconds.
2. Repeat leave → still **200**, count unchanged (idempotent, single `participant_left` event).
3. `POST /api/participants/{id}/rejoin` → **200** with original `id`/`joined_at`; count back to N; no duplicate entry.
4. Global `GET /api/events/history` shows exactly one `participant_joined` per join and one `participant_left` per leave transition.
5. **Expected**: real events only; silent drops converge via timeout (research §2 defaults).

### 6. Phone rehearsal (SC-004)

1. Display the presentation page; scan the on-screen code with 3+ real phones on the hotspot.
2. Each phone joins (named or anonymous) on the first attempt without help.
3. **Expected**: ≥90% first-attempt success; failures point at hotspot isolation/firewall per the setup notes, never at a stale QR.

## Regression gates

- `uv run ruff check .` — clean.
- `uv run pytest -q` — all pass, including new `tests/test_participants.py` (validation, duplicates, leave/rejoin, QR freshness, event emission).
