# Implementation Plan: Polls, Voting, Decision-Applied Branch (F3)

**Branch**: `chore/bootstrap-scaffold` | **Date**: 2026-10-15 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-polls-voting-decision/spec.md` — F3 polls/voting/decision-applied branch per `scratch/prd.md` 5.2–5.4 (acceptance #6). F1 (mission state machine, event store, SSE) and F2 (participant roster, Balanced-30, QR/presence) are taken as done (T001–T018); this plan builds on them without redoing them.

## Summary

F3 adds audience voting to the F1/F2 baseline: a new in-memory `polls` domain module (models + controller mirroring the proven missions/participants pattern) with a `open → closing → completed` state machine, lazy server-side deadline enforcement, dict-keyed one-vote-per-participant replacement semantics, aggregate-only vote events with live/controlled reveal modes, a narrow `MissionController.apply_decision` hook that patches next-step instructions from the winning option (controller stays thin; Hermes owns agent execution in F5), and vanilla-JS voter + dashboard additions rendered `textContent`-only over the existing SSE stream plus one new `poll_closed` event type.

## Technical Context

**Language/Version**: Python 3.12 (`requires-python = ">=3.12"`)

**Primary Dependencies**: FastAPI 0.143.1, uvicorn 0.54.0, Pydantic 2.14.1, httpx 0.28.1 (tests). No new dependencies (no sanitizer lib — `textContent`-only rendering; no timer/scheduler lib — lazy sweep).

**Storage**: In-memory poll/vote state (dict-keyed, `threading.Lock`), consistent with the F1 event store and F2 roster; PRD P2 excludes long-term storage and poll state is per-mission ephemeral (outcomes persist via the event log + `Mission.branch_context`). Declared `aiosqlite` dependency retained for a future persistence slice, not used by F3.

**Testing**: pytest 9.1.1, ruff 0.17.0. Commands (tester runs): `uv sync --group dev`, `uv run ruff check .`, `uv run pytest -q`.

**Target Platform**: Local-network server (`uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`) plus audience phones/desktop browsers over hotspot/Wi-Fi.

**Project Type**: Web application (FastAPI backend + dependency-free vanilla HTML/JS frontend in `frontend/static/`).

**Performance Goals**: Vote cast/change reflected within a few seconds without refresh (SC-007, FR-018); early close stops votes within 5s (SC-004); valid vote completable in under 30s on LAN (SC-001); rehearsal scale ~10 voters with vote changes tallied exactly (SC-003).

**Constraints**: Every vote validated server-side with failures leaving the tally untouched (FR-007); only joined-roster participants vote (FR-005); per-voter choices never leave the server (FR-015); dashboard shows only real events (FR-016); all poll content rendered as plain text (FR-019); presenter routes under optional-token server-side authorization (FR-020, research §7); controller stays thin, no agent execution (PRD 4C); one open poll per mission; must not redo F1/F2 or re-run T001–T018 except on regression.

**Scale/Scope**: One room, tens of voters, serial missions. Roughly: 1 new domain module (`polls`), 1 new API router, small `Mission` model addition (`branch_context`) + `apply_decision` hook, 1–2 new event types, voter + dashboard frontend additions, 1 new test module (`tests/test_polls.py`).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is an unratified placeholder template with no enforceable principles, so there are no constitution-derived gates to violate. Evaluated against standing project rules from `AGENTS.md` / PRD instead:

- [x] Hermes stays the agent executor; `apply_decision` only records the decision and patches step instructions — no agent framework in the controller — PASS.
- [x] Dashboard shows only real events; `poll_opened`/`vote_recorded`/`poll_closed`/`audience_decision_applied` emitted only for actual transitions — PASS.
- [x] Audience input affects real state (vote tallies, workflow branch) and every input is validated server-side; poll content rendered as plain text — PASS.
- [x] API keys server-side only; presenter controls gated when token configured; no participant access to host, credentials, or browser control — PASS.
- [x] Main workflow never depends on Telegram; F3 is web-only — PASS.

No violations. No Complexity Tracking entry required.

*Post-design re-check (after Phase 1): still PASS — design introduces no agent execution, no mocked events, no new privileged surface beyond the optional presenter token, and in-memory per-mission storage only.*

## Project Structure

### Documentation (this feature)

```text
specs/002-polls-voting-decision/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   └── polls-api.md
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── api/
│   │   ├── events.py          # existing SSE/history (subscribe poll_closed)
│   │   ├── missions.py        # existing (unchanged)
│   │   ├── participants.py    # existing (unchanged; roster reused for eligibility)
│   │   └── polls.py           # NEW: open/current/vote/close/resolve routes
│   ├── events/
│   │   ├── models.py          # EXTEND: poll_closed (+ poll_closing) types
│   │   └── store.py           # existing (unchanged API)
│   ├── missions/
│   │   ├── models.py          # EXTEND: Mission.branch_context (applied decisions)
│   │   └── controller.py      # EXTEND: apply_decision hook (thin, no agent exec)
│   ├── polls/                 # NEW domain module (mirrors missions/participants)
│   │   ├── __init__.py
│   │   ├── models.py          # Poll, Option, Vote map, AudienceDecision, state machine
│   │   └── controller.py      # in-memory polls: open/vote/close/resolve + lazy deadline sweep
│   └── main.py                # EXTEND: include polls router
frontend/
└── static/
    ├── index.html             # EXTEND: presenter poll panel (open/close/resolve) + results
    ├── app.js                 # EXTEND: poll render, countdown, controlled-reveal handling
    ├── poll.html / poll.js    # NEW (or voter section): voter view for joined participants
    └── join.html / join.js    # existing (link voter view; unchanged join logic)
tests/
├── test_events.py             # existing (regression only)
├── test_health.py             # existing (regression only)
├── test_missions.py           # existing (regression only)
├── test_participants.py       # existing (regression only)
└── test_polls.py              # NEW: vote/replace/reject, lifecycle, tie/no-vote, branch, reveal
```

**Structure Decision**: Web-application layout following the existing `backend/app/{api,missions,participants,events}` convention with a new `backend/app/polls/` domain module, thin routes in `backend/app/api/polls.py`, vanilla-JS frontend additions under `frontend/static/`, and contract/integration tests in `tests/test_polls.py`. No new top-level packages or frameworks.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — no violations.
