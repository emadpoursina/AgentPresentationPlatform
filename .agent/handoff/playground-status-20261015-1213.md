---
task: Live Agent Playground P0 demo (F1-F2 done, F3 next)
status: in_progress
branch: chore/bootstrap-scaffold
worktree: /Users/emad/Projects/playground/agentPresentationPlatform
timestamp: 2026-10-15T12:13Z
next_agent: human
---

## Goal
Build Live Agent Playground per `scratch/prd.md`: audience-driven multi-agent demo (Researcher/Critic/Summarizer on Hermes) with real SSE events, no mocked activity.

## Current State
- F1 done (commit 900d2a0): mission state machine created/running/paused/completed/failed + reset, in-memory event store with replay-by-after_id, SSE per-mission + global, REST lifecycle, dashboard renders real events only.
- F2 done (commit 46b8f4a): join via QR + presence — `GET /api/join-info`, `GET /api/join-info/qr`, join/heartbeat/leave/rejoin, Balanced-30 validation, live count via `participant_joined/left`, loopback → `ready:false`.
- Tree clean on `chore/bootstrap-scaffold`. Gates verified 2026-10-15T12:13Z: `uv run pytest -q` 19 passed, `uv run ruff check .` clean.
- Spec dir `specs/001-join-qr-presence/` complete: all T001-T018 checked.

## Files Touched
- `backend/app/missions/controller.py` — F1 state machine + reset
- `backend/app/missions/models.py` — F1 mission model
- `backend/app/events/models.py` — F1 event types + F2 participant_joined/left
- `backend/app/events/store.py` — F1 in-memory store + replay
- `backend/app/api/missions.py` — F1 REST lifecycle
- `backend/app/api/events.py` — F1 SSE streams
- `backend/app/participants/controller.py` — F2 roster join/heartbeat/leave/timeout
- `backend/app/participants/models.py` — F2 Balanced-30 validation
- `backend/app/api/participants.py` — F2 join-info/QR + roster endpoints
- `backend/app/main.py` — router wiring F1+F2
- `frontend/static/index.html` + `frontend/static/app.js` — dashboard + presence count
- `frontend/static/join.html` + `frontend/static/join.js` — F2 join page
- `tests/test_missions.py`, `tests/test_events.py` — F1 acceptance #2, #9
- `tests/test_participants.py` — F2 SC-005 + presence/reachability
- `specs/001-join-qr-presence/` — spec/plan/tasks/contracts for F2
- (from `git diff --stat`: clean tree, no unstaged/staged changes)

## Decisions Made
- Serial workflow first, one active mission (PRD §6) — why: reliability over parallelism for demo.
- Web Q&A fallback before Telegram (plan F8) — why: main workflow must not depend on Telegram.
- Balanced-30 display-name rule, server-authoritative — why: prevent abuse without accounts.

## Assumptions
- Hermes harness + free-tier model + browser tool check deferred to F5/F6 — not yet verified.
- Unknown — assumed from context: presenter wants F3 polls next in F1→F8 order; no explicit skip.
- Quickstart phone rehearsal (T016) marked done but multi-device hotspot not re-verified here.

## Open TODOs
- [ ] F3 Polls + voting + decision-applied branch (PRD 5.2-5.4, acceptance #6) — open/close/deadline, 1 vote/participant (changeable), tie-break presenter, no-vote fallback, `audience_decision_applied` drives real branch
- [ ] F4 Presenter dashboard real-events-only (PRD 5.5, acceptance #8)
- [ ] F5 Agent profiles + serial Hermes wiring (acceptance #3, #4, #5, #12)
- [ ] F6 Real browser demo + fallback (acceptance #7, #13)
- [ ] F7 Presenter controls + safety/recovery (acceptance #11-13)
- [ ] F8 Q&A web fallback first, Telegram optional (acceptance #10)
- [ ] F9 Playground gated last (P1)

## Blockers / Flags
- None blocking F3. Flag: Day-1 Hermes model/browser compatibility still untested — risk to F5/F6.

## Next Prompt
```text
Resume from .agent/handoff/playground-status-20261015-1213.md. Run F3 via speckit-orchestrate `path: feature` for polls/voting/decision-applied branch per scratch/prd.md 5.2-5.4 (acceptance #6); do NOT redo F1/F2 or re-run T001-T018 unless regression fails.
```

## Validation
- [x] Output is self-contained
- [x] Next agent knows first action without asking
- [x] Blockers flagged
