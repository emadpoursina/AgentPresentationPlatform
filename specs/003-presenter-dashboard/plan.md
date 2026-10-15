# Implementation Plan: Presenter Dashboard Real-Events-Only (F4)

**Branch**: `feat/003-presenter-dashboard` | **Date**: 2026-10-15 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-presenter-dashboard/spec.md` — F4 presenter dashboard real-events-only per `scratch/prd.md` 5.5 (acceptance #8). F1 (mission/SSE), F2 (join/presence), F3 (polls/branch) taken as done (T001–T044); this plan builds on them without redoing them.

## Summary

F4 is a frontend-only slice on the F1–F3 baseline: restructure `frontend/static/index.html` into six PRD 5.5 sections (mission header, agent activity, tool activity, handoffs, audience influence, final result + raw event log), add a single client-side reducer in `frontend/static/app.js` that builds the whole snapshot from `GET events` history + SSE tail (same `applyEvent` for both, `Last-Event-ID` dedup), reuse existing read APIs exclusively (no new backend, models, or event types), keep `textContent`-only rendering + honest empty states + the exact connected/disconnected banner contract, and pin it all with a new `tests/test_dashboard.py` (section presence, full event-type subscription, API-field availability). F5 agent execution only needs to emit the canonical events — no F4 protocol change.

## Technical Context

**Language/Version**: Python 3.12 (`requires-python = ">=3.12"`) + dependency-free vanilla HTML/JS + SSE (no build step).

**Primary Dependencies**: FastAPI 0.143.1, uvicorn 0.54.0, Pydantic 2.14.1, httpx 0.28.1 (tests). No new dependencies (no sanitizer lib — `textContent`-only; no frontend framework; no WS lib — SSE as-is).

**Storage**: No new storage. Dashboard state is an ephemeral client-side reduction; server truth stays in the F1 in-memory event log + mission store, F2 roster, F3 poll maps + `Mission.branch_context`.

**Testing**: pytest 9.1.1, ruff 0.17.0. Commands (tester runs): `uv sync --group dev`, `uv run ruff check .`, `uv run pytest -q`.

**Target Platform**: Local-network server (`uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`) + presenter browser + audience phones over hotspot/Wi-Fi.

**Project Type**: Web application (FastAPI backend + vanilla `frontend/static/`).

**Performance Goals**: Every section reflects real transitions within ~3s without refresh (SC-002/003/004); history seed `limit=100`, on-screen log capped at 200 rows newest-first; idle dashboard advances nothing.

**Constraints**: Every row traces to one real event (FR-007); progress = workflow position only (FR-001); failure never renders as success (FR-002); `textContent`-only for all untrusted strings, malformed SSE rows ignored with stream left open (FR-011); banner copy exact + stale-never-as-live (FR-009); subscribe all canonical + extended types (FR-010); existing read APIs only, no new backend (FR-012); must not redo F1–F3 or re-run T001–T044 except on regression.

**Scale/Scope**: One room, tens of devices, serial missions. Roughly: `index.html` restructure (6 sections + labels), `app.js` reducer + 5 section renderers (~300 lines), `tests/test_dashboard.py` (static + API-shape), spec docs (this dir).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is an unratified placeholder template with no enforceable principles, so there are no constitution-derived gates to violate. Evaluated against standing project rules from `AGENTS.md` / PRD instead:

- [x] Hermes stays the agent executor; F4 executes nothing, only renders events — PASS.
- [x] Dashboard shows only real events; reducer emits zero rows without an event; no timers advance state — PASS.
- [x] Audience input affects real state (F3-owned); F4 only displays it + branch linkage — PASS.
- [x] API keys server-side only; no new privileged surface; presenter controls untouched (F1/F3-owned) — PASS.
- [x] Main workflow never depends on Telegram; F4 is web-only — PASS.

No violations. No Complexity Tracking entry required.

*Post-design re-check (after Phase 1): still PASS — design adds no execution, no mocked events, no storage, no auth surface, and no backend change at all.*

## Project Structure

### Documentation (this feature)

```text
specs/003-presenter-dashboard/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   └── dashboard-api.md
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── api/                 # UNCHANGED (missions/events/participants/polls reused as-is)
│   ├── events/              # UNCHANGED (no new types; F5 will emit canonical agent/tool ones)
│   ├── missions/            # UNCHANGED (branch_context/consumed as-is)
│   └── main.py              # UNCHANGED (no new router)
frontend/
└── static/
    ├── index.html           # EXTEND: six PRD 5.5 sections + real-only labels + empty states
    └── app.js               # EXTEND: snapshot reducer + 5 section renderers + dedup guard
tests/
├── test_events.py           # existing (regression only)
├── test_health.py           # existing (regression only)
├── test_missions.py         # existing (regression only)
├── test_participants.py     # existing (regression only)
├── test_polls.py            # existing (regression only)
└── test_dashboard.py        # NEW: sections + subscriptions + API-field availability
```

**Structure Decision**: Web-application layout following the existing `backend/app/{api,missions,participants,polls,events}` convention with zero backend changes; all F4 work lands in `frontend/static/index.html` + `frontend/static/app.js` plus `tests/test_dashboard.py`. No new top-level packages or frameworks.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — no violations.
