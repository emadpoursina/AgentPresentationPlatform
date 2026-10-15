# Implementation Plan: Join with QR Code and Presence (F2)

**Branch**: `chore/bootstrap-scaffold` | **Date**: 2026-10-15 | **Spec**: [specs/001-join-qr-presence/spec.md](spec.md)

**Input**: Feature specification from `/specs/001-join-qr-presence/spec.md`

## Summary

F2 adds presentation-session joining to the F1 mission-controller baseline: a join page (display name or anonymous, no accounts), a QR code that always encodes the current reachable LAN join URL, and a live connected-participant count that decrements on leave/timeout. Approach mirrors proven F1 patterns — a new in-memory `participants` domain module (models + controller) with Pydantic validation, thin FastAPI routes, join/leave events on the existing event store and SSE stream, server-side enforcement of the clarified Balanced-30 name rule, and plain-text rendering of all participant-supplied content. QR generation reuses the already-declared `qrcode[pil]` dependency, so no new dependencies are needed.

## Technical Context

**Language/Version**: Python 3.12 (`requires-python = ">=3.12"`)

**Primary Dependencies**: FastAPI 0.143.1, uvicorn 0.54.0, Pydantic 2.14.1, `qrcode[pil]` 8.2 (already declared — QR generation), httpx 0.28.1 (tests), aiosqlite 0.22.1 (declared; not used by F2)

**Storage**: In-memory session roster (no persistence). Consistent with the F1 in-memory event store and the PRD P2 exclusion of long-term storage; presence is session-scoped per spec Assumptions.

**Testing**: pytest 9.1.1, ruff 0.17.0. Commands (tester runs): `uv sync --group dev`, `uv run ruff check .`, `uv run pytest -q`.

**Target Platform**: Local-network server (`uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`) plus audience phones/desktop browsers over hotspot/Wi-Fi.

**Project Type**: Web application (FastAPI backend + dependency-free vanilla HTML/JS frontend in `frontend/static/`).

**Performance Goals**: Join completes in under 1 minute (SC-002); QR scan to join page under 30s on LAN (SC-001); displayed count converges within seconds of join/leave (FR-009); 10 near-simultaneous joins counted correctly (SC-003).

**Constraints**: Every join input validated server-side (FR-006); participant names treated as untrusted and rendered as plain text (FR-012); no accounts, credentials, or unnecessary PII (FR-013); no management/debugging exposure to participants (FR-016); advertised join target must never be loopback-only (FR-014); QR must always reflect the current reachable address (FR-002).

**Scale/Scope**: One room, tens of devices. Roughly: 1 new domain module (`participants`), 1 new API router (+ join-info endpoint), frontend join view + presence count + QR element, 2 new SSE event types, 1 new test module.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is an unratified placeholder template with no enforceable principles, so there are no constitution-derived gates to violate. Evaluated against standing project rules from `AGENTS.md` / PRD instead:

- [x] Hermes stays the agent executor; F2 adds no agent code and the mission controller remains a thin coordinator — PASS.
- [x] Dashboard/presence shows only real execution events; `participant_joined` / `participant_left` are emitted only on actual joins/leaves — PASS.
- [x] Audience input affects real state (roster) and every input is validated server-side; names rendered as plain text — PASS.
- [x] API keys server-side only; no participant access to host, credentials, or browser control — PASS (F2 adds no such surface).
- [x] Main workflow never depends on Telegram; F2 is web-only — PASS.

No violations. No Complexity Tracking entry required.

*Post-design re-check (after Phase 1): still PASS — design below introduces no agent framework, no mocked events, no new privileged surface, and session-scoped in-memory storage only.*

## Project Structure

### Documentation (this feature)

```text
specs/001-join-qr-presence/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   └── participants-api.md
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── api/
│   │   ├── events.py          # existing SSE/history (subscribe new types)
│   │   ├── missions.py        # existing (unchanged)
│   │   └── participants.py    # NEW: join/leave/heartbeat/roster/join-info routes
│   ├── events/
│   │   ├── models.py          # EXTEND: participant_joined/participant_left types
│   │   └── store.py           # existing (unchanged API)
│   ├── missions/              # existing (unchanged)
│   ├── participants/          # NEW domain module (mirrors missions/events)
│   │   ├── __init__.py
│   │   ├── models.py          # Participant, JoinRequests, Roster views, name validation
│   │   └── controller.py      # in-memory roster: join/leave/heartbeat/timeout sweep
│   └── main.py                # EXTEND: include participants router
├── __init__.py
frontend/
└── static/
    ├── index.html             # EXTEND: presence count + QR element + setup notes
    ├── app.js                 # EXTEND: subscribe participant_* SSE types, render count
    └── join.html / join.js    # NEW (or join section): join form (name/anonymous), confirmation
tests/
├── test_events.py             # existing
├── test_health.py             # existing
├── test_missions.py           # existing
└── test_participants.py       # NEW: validation, duplicates, leave/timeout, QR URL freshness
```

**Structure Decision**: Web-application layout following the existing `backend/app/{api,missions,agents,events}` convention with a new `backend/app/participants/` domain module, thin routes in `backend/app/api/participants.py`, vanilla-JS frontend additions under `frontend/static/`, and contract/integration tests in `tests/`. No new top-level packages or frameworks.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — no violations.
