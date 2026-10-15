# Quickstart: Polls, Voting, Decision-Applied Branch (F3)

Validation guide for the later Walkthrough. Uses `uv run` commands per AGENTS.md; F1 (T001–T009 approx.) and F2 (T010–T018 approx.) are taken as done — do not redo them, only the regression checks noted. See [contracts/polls-api.md](contracts/polls-api.md) and [data-model.md](data-model.md) for shapes.

## Prerequisites

- Server: `uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`
- Optional: `PLAYGROUND_PRESENTER_TOKEN=demo-secret` to exercise presenter authorization (then pass `-H "X-Presenter-Token: demo-secret"` on open/close/resolve calls; missing/wrong token returns `403 presenter authorization required`, audience votes stay ungated).
- Two joined participants (F2 join flow) — record their ids as `$A` and `$B`.

## Flow 1 — Vote, change vote, invalid votes rejected (Stories 1+4, SC-001/002/003)

1. Create + start a mission; open a live-mode poll with 3 options and `deadline_seconds: 120`.
2. `$A` votes option 1, `$B` votes option 2 → tally `{1:1, 2:1}`, both visible live without refresh.
3. `$A` changes to option 2 → tally `{2:2}`, exactly one vote per voter (SC-003 shape).
4. Reject cases (each returns 4xx, tally unchanged): unknown participant id, unknown option id, malformed body, empty body (SC-002).
5. Repeat with a `controlled`-mode poll: pre-close `vote_recorded` events carry only `total_votes`; full counts appear only after close.

## Flow 2 — Lifecycle: deadline, early close, tie-break, no-vote fallback (Story 2, SC-004/005)

1. Open a poll with `deadline_seconds: 10` → after ~10s votes reject with 409 and state is `closing`/`completed` without presenter action.
2. Open another poll, presenter `POST .../close` → further votes reject within 5 seconds (SC-004).
3. Force a tie (A→opt1, B→opt2), close, `POST .../resolve {"winning_option_id":"opt1"}` → completed with `decided_by: presenter_tiebreak`; a non-tied choice is rejected with 400.
4. Open a poll, close with zero votes, resolve with an option → completed with `decided_by: presenter_fallback`, no fabricated winner (SC-005).
5. Throughout: audience screens show open → closing → completed within seconds; disconnect shows the stale-state banner, never stale standings as current.

## Flow 3 — Decision drives a real branch (Story 3, SC-006/007, acceptance #6)

1. Open a poll whose options carry distinct `branch_instruction` values; complete it and resolve winner W1.
2. `GET /api/missions/{id}` shows `branch_context` with W1 and the next step's instructions reflecting W1's text.
3. Reset the mission, repeat with winner W2 → next-step instructions differ (SC-006: same mission, two winners, two different next steps).
4. `GET /api/missions/{id}/events` contains `poll_opened → vote_recorded* → poll_closed → audience_decision_applied` with timestamps + mission ids and zero fabricated entries (SC-007).

## Regression (F1/F2, only if suspected)

- Mission start/pause/reset still 200/409-correct; presence count still converges on join/leave; SSE replay via `Last-Event-ID` still lossless. Do not re-run T001–T018 wholesale.

## Commands

- `uv sync --group dev`
- `uv run ruff check .`
- `uv run pytest -q`
