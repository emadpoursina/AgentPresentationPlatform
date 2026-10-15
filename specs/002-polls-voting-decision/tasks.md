# Tasks: Polls, Voting, Decision-Applied Branch (F3)

**Input**: Design documents from `specs/002-polls-voting-decision/` (spec.md, plan.md, data-model.md, contracts/polls-api.md, research.md, quickstart.md)

**Prerequisites**: F1 (mission state machine, event store, SSE) and F2 (participant roster, presence) taken as done via T001–T018. Do NOT redo T001–T018 or re-run them unless a regression is suspected.

**Tests**: Included — spec.md acceptance scenarios and SC-001–SC-007 plus quickstart Flows 1–3 are explicit testable criteria, so each story phase leads with its test tasks.

**Organization**: Grouped by user story (US1–US4 from spec.md). Task IDs continue after T018 (T019+).

**Constraints honored**: controller stays thin (no agent execution, Hermes owns agents in F5); dashboard shows only real events; all poll content rendered `textContent`-only; presenter routes gated by `X-Presenter-Token` only when `PLAYGROUND_PRESENTER_TOKEN` is set; one open poll per mission; votes keyed `(poll_id, participant_id)`.

## Phase 1: Prior Work — T001–T018 (F1/F2, DONE — do not redo)

**Purpose**: Record the baseline this feature builds on. No action required.

- T001–T009 (F1): mission state machine, event store, SSE stream, history — DONE
- T010–T018 (F2): participant roster, join/presence, countdown/Balanced-30, QR — DONE

**Guard**: Only revisit via the regression tasks in Phase 7 (T041) if a failure is suspected. No new Setup work: stack (FastAPI 0.143.1, uvicorn, Pydantic, pytest, ruff) and layout (`backend/app/`, `frontend/static/`, `tests/`) already exist.

---

## Phase 2: Foundational — Poll Domain Blocking Prerequisites

**Purpose**: In-memory poll domain and additive model extensions that ALL user stories depend on. Must complete before story phases.

 - [x] T019 Create Poll/Option/Vote-map/AudienceDecision models with `open → closing → completed` state machine in backend/app/polls/models.py (constraints verbatim: question "1–200 chars, trimmed, non-blank"; options "2–6 items", ids unique short strings, labels "1–80 chars", `branch_instruction` per-option next-step text; `deadline_seconds` "default 60, bounded (e.g. 10–600s)"; `reveal_mode` "`live` | `controlled`, fixed at open, default `live`"; `outcome` null until completed then `{winning_option_id, decided_by, decided_at}` with `decided_by ∈ {tally, presenter_tiebreak, presenter_fallback}`; server-issued short-hex ids)
 - [x] T020 Implement in-memory polls controller with dict-keyed `(poll_id, participant_id) → option_id` vote replacement and lazy server-side deadline sweep on every poll read/write path in backend/app/polls/controller.py (server arrival time authoritative; invalid opens create no record; votes never outlive mission context)
 - [x] T021 [P] Extend canonical event types additively with `poll_closed` (plus optional `poll_closing`) carrying `{poll_id, mission_id}` + safe metadata in backend/app/events/models.py (no EventStore API change; payloads per data-model.md: `poll_opened` excludes `branch_instruction`, `vote_recorded` aggregate-only, `audience_decision_applied` carries `{poll_id, winning_option_id, decided_by, next_step}`)
 - [x] T022 [P] Add `Mission.branch_context` field (`applied_decisions: list[AudienceDecision]` + `current_branch_instruction: str | None`) in backend/app/missions/models.py (outcomes persist via event log + `branch_context`; poll state itself stays per-mission ephemeral in-memory)

**Checkpoint**: Foundation ready — `Poll` model, polls controller, new event types, and `branch_context` exist; story work can proceed.

---

## Phase 3: User Story 1 — Vote in an Open Poll (Priority: P1) 🎯 MVP

**Goal**: Joined participants cast exactly one counted vote per poll and may change it before close; non-joined, unknown-option, malformed, and after-close submissions are rejected without altering the tally.

**Independent Test**: Open a poll with 2–4 predefined options; vote from two joined devices (change one vote before close); confirm each voter's latest vote is the one counted, no duplicates tallied, and non-joined/invalid submissions rejected (quickstart Flow 1, SC-001/SC-002/SC-003).

### Tests for User Story 1

 - [x] T023 [P] [US1] Write vote contract/integration tests (cast, change-replaces, same-option idempotent retry, reject non-joined/unknown-option/malformed/after-close with tally unchanged, double-tap converges) in tests/test_polls.py

### Implementation for User Story 1

 - [x] T024 [US1] Implement `POST /api/missions/{mission_id}/polls/{poll_id}/vote` cast-or-change route with server-side validation order (poll exists → poll is `open` → voter `connected` on F2 roster → payload well-formed → `option_id` on predefined list; failures return 4xx with clear message and leave tally/prior vote untouched) in backend/app/api/polls.py
 - [x] T025 [US1] Enforce voter eligibility against F2 roster as-is (voter must satisfy `participants.get(id).status == "connected"` post-sweep; already-recorded votes stand, only new/changed submissions require connected status; per-voter choices never leave the server) in backend/app/polls/controller.py
 - [x] T026 [US1] Implement idempotent same-option retry (200 with current tally shape, no new `vote_recorded` event, no double count on retried/replayed submissions) in backend/app/polls/controller.py
 - [x] T027 [P] [US1] Build voter view for joined participants (question + options + state/deadline indication, vote/change interaction, rejection messages) with `textContent`-only rendering and link from join flow in frontend/static/poll.html and frontend/static/poll.js (or voter section in frontend/static/index.html + frontend/static/app.js if single-page; join logic in frontend/static/join.html + frontend/static/join.js unchanged)

**Checkpoint**: US1 independently testable — two joined voters, one vote-change, invalid submissions all rejected, tally exact.

---

## Phase 4: User Story 2 — Presenter Runs the Poll Lifecycle (Priority: P1)

**Goal**: Presenter opens polls (question + 2–6 options + deadline), watches `open → closing → completed`, closes early, and resolves ties / zero-vote polls via presenter selection; audience always sees current state.

**Independent Test**: Open a poll with short deadline; observe open state; close early from presenter view; confirm completed with exactly one recorded outcome visible on audience devices — no mission/agent workflow required (quickstart Flow 2, SC-004/SC-005).

### Tests for User Story 2

 - [x] T028 [P] [US2] Write lifecycle tests (open validation incl. second-open 409, no-mission 409, <2/>6-option 400; deadline auto-close; early close immediacy; tie-break only-among-tied; zero-vote fallback; outright winner auto-completes with no resolve needed) in tests/test_polls.py

### Implementation for User Story 2

 - [x] T029 [US2] Implement `POST /api/missions/{mission_id}/polls` open route (mission must be `running`; at most one `open`/`closing` poll per mission else 409; question non-blank ≤200 chars; 2–6 unique options; `deadline_seconds` default 60 range 10–600; `reveal_mode` fixed at open default `live`; presenter-token gate only when `PLAYGROUND_PRESENTER_TOKEN` set) in backend/app/api/polls.py
 - [x] T030 [US2] Implement `POST /api/missions/{mission_id}/polls/{poll_id}/close` early-close route (takes effect immediately, stops vote acceptance; outright winner auto-completes with `decided_by=tally`; otherwise moves to `closing` awaiting resolve; 409 when already completed) in backend/app/api/polls.py
 - [x] T031 [US2] Implement `POST /api/missions/{mission_id}/polls/{poll_id}/resolve` tie-break/no-vote route (only in `closing`; tie choice must be among tied options else 400; zero-vote choice among options or mission default; 409 when not awaiting resolution; presenter-routed per FR-020) in backend/app/api/polls.py
 - [x] T032 [P] [US2] Implement `GET /api/missions/{mission_id}/polls/current` current-poll route (200 Poll view or `{"poll": null}`; audience-facing reads exclude `branch_instruction`; `tally` only when `reveal_mode == live` or `state == completed`, else `total_votes` only) in backend/app/api/polls.py
 - [x] T033 [P] [US2] Build presenter poll panel (open form with question/options/deadline/reveal, early-close button, tie-break/no-vote resolve picker, countdown from server `deadline_at`, open/closing/completed state display) in frontend/static/index.html and frontend/static/app.js

**Checkpoint**: US2 independently testable — open → deadline/early close → tie and zero-vote resolution each yield one recorded outcome, visible state on all screens.

---

## Phase 5: User Story 3 — Winning Choice Drives a Real Workflow Branch (Priority: P1)

**Goal**: Completed polls record the winning choice as an applied audience decision in activity history and change the mission's actual next step (task instructions/branch), with the dashboard showing only real events.

**Independent Test**: Complete a poll; confirm winner appears in activity history as the applied decision; confirm the mission's next step reflects that choice — run the same mission with two different winners and observe two different next steps (quickstart Flow 3, SC-006/SC-007, acceptance #6).

### Tests for User Story 3

 - [x] T034 [P] [US3] Write decision-branch integration tests (resolve emits `audience_decision_applied`; `branch_context` patched from winning option's `branch_instruction`; same mission with W1 vs W2 yields observably different next-step instructions; event history contains `poll_opened → vote_recorded* → poll_closed → audience_decision_applied` with timestamps + mission ids, zero fabricated entries) in tests/test_polls.py

### Implementation for User Story 3

 - [x] T035 [US3] Implement narrow `MissionController.apply_decision(mission_id, poll_id, winning_option_id, branch_map)` hook (validate mission active + poll completed; append decision to `branch_context.applied_decisions`; patch `current_branch_instruction` from winning option's `branch_instruction`; emit `audience_decision_applied`; no agent execution — Hermes reads `branch_context` at F5) in backend/app/missions/controller.py
 - [x] T036 [US3] Wire polls router into app and SSE publishing for `poll_opened` / aggregate `vote_recorded` / `poll_closed` / `audience_decision_applied` (emitted only for actual transitions; no per-voter choices in payloads; `Last-Event-ID` replay unchanged) in backend/app/main.py and backend/app/api/polls.py
 - [x] T037 [US3] Subscribe new close type(s) alongside existing poll subscriptions and render dashboard activity from real events only (timestamp + mission reference per event; never fabricated progress or simulated tool activity as real) in frontend/static/app.js

**Checkpoint**: US3 independently testable — two winners produce two different next steps; history and dashboard match reality exactly.

---

## Phase 6: User Story 4 — Follow Poll Results Live with Controlled Reveal (Priority: P2)

**Goal**: Live-count polls show updated counts within seconds; controlled-reveal polls hide per-option counts until close; identical counting rules in both modes.

**Independent Test**: Open one live-mode and one controlled-mode poll; vote from two devices; confirm live counts update without refresh in the first and stay hidden until close in the second, with identical tallies after close (quickstart Flow 1 step 5).

### Tests for User Story 4

 - [x] T038 [P] [US4] Write reveal-mode tests (live `vote_recorded` carries `{counts, total}`; controlled pre-close carries `{total}` only; full counts + outcome appear at completion in both; mode fixed at open and echoed to voters) in tests/test_polls.py

### Implementation for User Story 4

 - [x] T039 [US4] Implement reveal-mode event payload shaping (live vs controlled pre-close vs completed) in backend/app/polls/controller.py
 - [x] T040 [US4] Implement frontend reveal handling (live count updates within seconds without refresh; controlled mode shows open/accepting state without per-option counts until close; final counts + outcome shown together; clear disconnected/stale banner instead of stale standings) in frontend/static/app.js (and frontend/static/poll.js if voter view is separate)

**Checkpoint**: US4 independently testable — both modes verified side by side with identical counting.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Security, validation, and regression guard. No F1/F2 re-implementation.

 - [x] T041 Audit all poll/vote rendering paths for `textContent`-only plain-text output (question, labels, tallies, error messages; no `innerHTML` for untrusted data) in frontend/static/app.js and frontend/static/poll.js (create-or-extend whichever voter file exists)
 - [x] T042 [P] Document `PLAYGROUND_PRESENTER_TOKEN` env var and presenter-header usage in specs/002-polls-voting-decision/quickstart.md (already drafted — verify accuracy against implemented header name `X-Presenter-Token` and 403 behavior)
 - [x] T043 Run lint + full suite (`uv sync --group dev`, `uv run ruff check .`, `uv run pytest -q`) and fix F3-attributable failures in tests/test_polls.py and backend/app/polls/controller.py (tester runs commands; do not claim pass without execution evidence)
 - [x] T044 Regression guard ONLY (no redo): verify mission start/pause/reset 200/409 behavior, presence convergence on join/leave, and SSE replay via `Last-Event-ID` still lossless using existing tests/test_missions.py, tests/test_participants.py, and tests/test_events.py — investigate only on failure, do not re-run T001–T018 wholesale

---

## Dependencies & Execution Order

```text
Phase 1 (T001–T018 DONE)
  └─▶ Phase 2 Foundational (T019 → T020; T021 + T022 parallel with each other, after T019)
        ├─▶ Phase 3 US1 votes (T023 test first; T024 + T025 + T026 on controller; T027 frontend) 🎯 MVP
        ├─▶ Phase 4 US2 lifecycle (T028 test first; T029 + T030 + T031 routes; T032 + T033 parallel frontend/route)
        ├─▶ Phase 5 US3 branch (T034 test first; T035 hook; T036 wiring; T037 dashboard)
        └─▶ Phase 6 US4 reveal P2 (T038 test first; T039 backend; T040 frontend)
              └─▶ Phase 7 Polish (T041 + T042 parallel; T043 validation; T044 regression guard)
```

- US1, US2, US3 can start in parallel once Phase 2 completes (independent routes/controller slices), but US3's end-to-end branch test (T034) needs US2's close/resolve paths working.
- US4 (P2) may be deferred after US1–US3 (all P1) for an MVP cut.
- Suggested MVP: Phase 2 → US1 (T023–T027) → US2 (T028–T033) → US3 (T034–T037); US4 and Polish follow.

## Parallel Execution Examples

- Foundational: `T021` (events model) + `T022` (mission model) in parallel — different files, no shared edits.
- US1: `T023` (tests/test_polls.py vote tests) can be drafted in parallel with `T027` (frontend voter view) — different files; `T024/T025/T026` converge in controller + router.
- US2: `T028` (lifecycle tests) + `T032` (current-poll route) + `T033` (presenter panel) in parallel — test file vs router vs frontend.
- US3: `T034` (branch tests) + `T037` (dashboard rendering) in parallel — test file vs frontend.
- Polish: `T041` (rendering audit) + `T042` (quickstart doc check) in parallel.

## Implementation Strategy

1. MVP first: poll domain (T019–T022) → votable/replaceable gated votes (US1) → open/close/resolve lifecycle (US2) → real branch hook + honest dashboard (US3). Each story independently testable per its checkpoint.
2. Then P2 reveal modes (US4) — payload shaping only, counting rules unchanged.
3. Validate with `uv run ruff check .` + `uv run pytest -q`, then quickstart Flows 1–3 end to end; F1/F2 regression only on suspicion (T044).
