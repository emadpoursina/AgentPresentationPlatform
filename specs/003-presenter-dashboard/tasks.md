# Tasks: Presenter Dashboard Real-Events-Only (F4)

**Input**: Design documents from `specs/003-presenter-dashboard/` (spec.md, plan.md, data-model.md, contracts/dashboard-api.md, research.md, quickstart.md)

**Prerequisites**: F1 (mission state machine, event store, SSE), F2 (participant roster, presence), F3 (polls/branch) taken as done via T001–T044. Do NOT redo T001–T044 or re-run them unless a regression is suspected.

**Tests**: Included — spec.md SC-001–SC-005 and quickstart Flows 1–3 are explicit testable criteria; static file + API-shape tests pin the F5 contract.

**Organization**: Grouped by user story (US1–US4 from spec.md). Task IDs continue after T044 (T045+).

**Constraints honored**: frontend-only (no new backend/models/events); every row traces to one real event; progress workflow-position-only; failure distinct from success; `textContent`-only; exact banner copy; all-type subscription; existing read APIs only.

## Phase 1: Prior Work — T001–T044 (F1/F2/F3, DONE — do not redo)

**Purpose**: Record the baseline this feature builds on. No action required.

- T001–T009 (F1): mission state machine, event store, SSE stream, history — DONE
- T010–T018 (F2): participant roster, join/presence, Balanced-30, QR — DONE
- T019–T044 (F3): poll domain, voting, lifecycle, decision-applied branch, reveal — DONE

**Guard**: Only revisit via the regression task in Phase 6 (T058) if a failure is suspected. No new Setup work: stack (FastAPI 0.143.1, uvicorn, Pydantic, pytest, ruff) and layout (`backend/app/`, `frontend/static/`, `tests/`) already exist.

---

## Phase 2: Foundational — Dashboard Snapshot Reducer (blocking)

**Purpose**: Single client-side reduction all story phases depend on. Must complete before section work.

- [x] T045 Implement dashboard snapshot reducer in `frontend/static/app.js` (`snapshot = {agents: Map, tools: [], handoffs: [], influence, lastEventId}`, `applyEvent(snapshot, ev)` handling every type in `EVENT_TYPES` per data-model.md, `ev.id <= lastEventId` replay-dedup guard, one code path for history seed + live tail)
- [x] T046 [P] Restructure `frontend/static/index.html` skeleton into six labelled sections (`#mission`, `#agents`, `#tools`, `#handoffs`, `#influence`, `#result` + `#events` log) each with a "Real events only" caption, honest empty-state placeholder, and explanatory-text-vs-data styling hook (no behavior change yet — renderers land in story phases)

**Checkpoint**: Foundation ready — reducer + section skeleton exist; story work can proceed.

---

## Phase 3: User Story 1 — Mission State and Final Result (Priority: P1)

**Goal**: Header shows real title/status/step/progress; result block shows summary/outcome/error with failure distinct; nothing advances without events.

**Independent Test**: Quickstart Flow 1 (empty → lifecycle → complete vs fail → 30s idle with zero drift; SC-001/SC-003).

### Tests for User Story 1

- [x] T047 [P] [US1] Write dashboard tests for header/result contract in `tests/test_dashboard.py` (sections `#mission`/`#result` + progress/result labels present; `GET /api/missions/{id}` exposes `title/status/steps/current_step_index/progress/result_summary/outcome/error`; complete vs fail render distinctly via API `outcome` values)

### Implementation for User Story 1

- [x] T048 [US1] Implement `renderMission` + `renderResult` from live `Mission` fetch in `frontend/static/app.js` (progress bar + pct + "Workflow position only — never simulated" caption; result block with `Result:/Outcome:/Error:` lines and `failed` vs `success/partial` styling; "No mission yet" empty state; refresh on every mission-type SSE event)

**Checkpoint**: US1 independently testable — full lifecycle reflects within ~3s per transition, failure distinct, idle drift zero.

---

## Phase 4: User Story 2 — Agent, Tool, Handoff Activity (Priority: P1)

**Goal**: Agent/tool/handoff sections list exactly the real canonical events (with timestamp + mission ref) or honest empty states when none exist yet.

**Independent Test**: Quickstart Flow 2 (empty states with F1–F3 only; inject one of each canonical agent/tool event → exact rows within ~3s; SC-002).

### Tests for User Story 2

- [x] T049 [P] [US2] Write dashboard tests for agent/tool readiness in `tests/test_dashboard.py` (sections `#agents`/`#tools`/`#handoffs` + empty-state copy present; `app.js` subscribes to `agent_started/tool_started/tool_completed/agent_handoff/agent_completed/agent_failed`; `EVENT_TYPES` contains all six; no `innerHTML` for untrusted data in `app.js`)

### Implementation for User Story 2

- [x] T050 [US2] Implement `renderAgents`/`renderTools`/`renderHandoffs` reducers + renderers in `frontend/static/app.js` (agent map upsert on `agent_started/completed/failed` with `waiting|running|completed|failed` + task; tool rows on `tool_started/completed` with name/action/status + 300-char truncated safe summary; handoff rows on `agent_handoff` with from→to + summary + reason; `textContent`-only; timestamp + mission ref per row)
- [x] T051 [US2] Seed agent/tool/handoff state from history load (`GET events?limit=100` reduced in id order through `applyEvent`) in `frontend/static/app.js` so mid-mission opens show current state with no gap

**Checkpoint**: US2 independently testable — empty until F5, exact once events exist, markup-inert.

---

## Phase 5: User Story 3 — Audience Influence + Disconnect Trust (Priority: P1)

**Goal**: Influence block shows poll + counts/outcome + selected branch; banner + replay keep stale-never-as-live.

**Independent Test**: Quickstart Flow 3 (full F3 cycle reflected within ~3s; controlled hiding; disconnect banner + lossless replay; SC-004; history-vs-screen 1:1, SC-001).

### Tests for User Story 3

- [x] T052 [P] [US3] Write dashboard tests for influence + stream trust in `tests/test_dashboard.py` (section `#influence` + branch/outcome labels present; `GET .../polls/current` + `branch_context` fields consumed exist; `app.js` handles `poll_opened/vote_recorded/poll_closing/poll_closed/audience_decision_applied` + exact banner copy both states + `Last-Event-ID`/`lastEventId` replay wiring present)

### Implementation for User Story 3

- [x] T053 [US3] Implement `renderInfluence` in `frontend/static/app.js` (`polls/current` + latest `audience_decision_applied` + `mission.branch_context`: question/state/reveal/counts-or-hidden/deadline countdown, outcome `winning_option_id + decided_by`, branch instruction + applied-decision history; honest "No polls yet" empty state; refresh on every poll/decision event + mission refresh)
- [x] T054 [US3] Harden stream trust in `frontend/static/app.js` (exact banner copy, `onopen→connected/onerror→disconnected`, sections frozen while disconnected except banner, `lastEventId` dedup on history + live, malformed-row `try/catch` keeps stream open, raw `#events` log newest-first capped at 200 with id/type/timestamp/mission ref)

**Checkpoint**: US3 independently testable — influence 1:1 with history, disconnect honest, replay lossless.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Security audit, docs, and regression guard. No F1–F3 re-implementation.

- [x] T055 Audit all dashboard rendering paths for `textContent`-only plain-text output (mission/step/poll/agent/tool/handoff/error strings; no `innerHTML` for untrusted data; overly long summaries truncated) in `frontend/static/app.js` + `frontend/static/index.html`
- [x] T056 [P] Verify quickstart Flows 1–3 end to end against a local server per `specs/003-presenter-dashboard/quickstart.md` (manual walkthrough; record pass/fail per flow in the F4 handoff)
- [x] T057 Run lint + full suite (`uv run ruff check .`, `uv run pytest -q`) and fix F4-attributable failures in `tests/test_dashboard.py` and `frontend/static/app.js` (tester runs commands; do not claim pass without execution evidence)
- [x] T058 Regression guard ONLY (no redo): verify mission start/pause/reset 200/409 behavior, presence convergence on join/leave, SSE replay lossless, and vote/tally/branch rules unchanged using existing `tests/test_missions.py`, `tests/test_participants.py`, `tests/test_events.py`, `tests/test_polls.py` — investigate only on failure, do not re-run T001–T044 wholesale

---

## Dependencies & Execution Order

```text
Phase 1 (T001–T044 DONE)
  └─▶ Phase 2 Foundational (T045 reducer → T046 skeleton, parallel-safe: different concerns same files — sequence to avoid conflicts)
        ├─▶ Phase 3 US1 header/result (T047 test + T048 renderers, parallel: test file vs frontend)
        ├─▶ Phase 4 US2 agents/tools/handoffs (T049 test + T050/T051 renderers+seed, needs T045 reducer)
        └─▶ Phase 5 US3 influence/trust (T052 test + T053/T054 renderers+harden, needs T045 + F3 APIs)
              └─▶ Phase 6 Polish (T055 + T056 parallel; T057 validation; T058 regression guard)
```

- US1, US2, US3 can start in parallel once Phase 2 completes (independent sections), but US3's branch display needs F3 `branch_context` reads working (already done).
- Suggested MVP: Phase 2 → US1 (T047–T048) → US2 (T049–T051) → US3 (T052–T054); Polish follows.

## Parallel Execution Examples

- Foundational: `T045` then `T046` (same frontend files — sequence, not parallel).
- US1: `T047` (tests/test_dashboard.py header asserts) + `T048` (app.js header renderers) in parallel — test file vs frontend.
- US2: `T049` (dashboard agent/tool asserts) + `T050/T051` (renderers) in parallel — test file vs frontend.
- US3: `T052` (influence/stream asserts) + `T053/T054` (influence render + harden) in parallel.
- Polish: `T055` (rendering audit) + `T056` (quickstart walkthrough) in parallel.

## Implementation Strategy

1. MVP first: reducer + skeleton (T045–T046) → header/result (US1) → agents/tools/handoffs (US2) → influence/trust (US3). Each story independently testable per its checkpoint.
2. Then polish: audit + walkthrough + lint/suite + regression guard.
3. Validate with `uv run ruff check .` + `uv run pytest -q`, then quickstart Flows 1–3 end to end; F1–F3 regression only on suspicion (T058).
