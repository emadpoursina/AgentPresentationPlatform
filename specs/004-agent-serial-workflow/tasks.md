# Tasks: Agent Profiles + Serial Hermes Workflow (F5)

**Input**: Design documents from `specs/004-agent-serial-workflow/` (spec.md, plan.md, research.md, data-model.md, quickstart.md, contracts/hermes-executor.md, contracts/agent-event-payloads.md, contracts/workflow-api.md)

**Prerequisites**: plan.md + spec.md (required), research.md, data-model.md, quickstart.md, contracts/ — all fresh from the plan stage.

**Tests**: Included — explicitly requested: FR-023 (stub unit/integration tests + exactly one opt-in real E2E), plan.md's test plan (`tests/test_agent_profiles.py`, `tests/test_agent_runner.py`, `tests/test_quota_gate.py`, `tests/test_agent_e2e_real.py`), and quickstart's gate flows.

**Organization**: Grouped by user story (US1–US3 from spec.md). This project numbers task IDs CONTINUOUSLY across specs: F1/F2/F3 = T001–T044, F4 = T045–T058 (all checked/done). **F5 tasks continue at T059.**

**Constraints honored (settled facts — do not re-open)**: Hermes v0.21.7 sole executor via subprocess CLI adapter (no second agent framework); model pinned to pre-flight-verified `muse-spark-1.3-contributor` @ `opencode-go` with re-pre-flight on any change (FR-011); exactly six F4 event types emitted, zero frontend/protocol changes (FR-012); every event 1:1 with a real occurrence (FR-013); abort-to-failed-terminal + resume-at-failed-step retry (FR-020/FR-021); least-privilege tools — `terminal` → Researcher only (FR-022); stub tests + one opt-in real E2E (`real_e2e` marker + `F5_REAL_E2E=1`) (FR-023); 35% quota confirmation gate (FR-024); F5 only, F1–F4 frozen — gates `uv run pytest -q` (57 baseline) and `uv run ruff check .` must stay green (FR-019); terminal-runnable end-to-end first (FR-017). No new Python dependencies; no commits/pushes/branch switches from this artifact.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Prior Work — T001–T058 (F1–F4, DONE — do not redo)

**Purpose**: Record the baseline F5 builds on. No action required.

- T001–T009 (F1): mission state machine, event store, SSE, history — DONE
- T010–T018 (F2): participant roster, join/presence, QR — DONE
- T019–T044 (F3): poll domain, voting, decision-applied `branch_context` — DONE (consumed read-only by F5)
- T045–T058 (F4): dashboard snapshot reducer + agent/tool/handoff/influence renderers — DONE (renders F5's six events already; frontend is frozen)

**Guard**: Only revisit F1–F4 via the regression guard in Phase 7 if a failure is suspected. No new Setup work: stack (Python 3.12, FastAPI, uv, pytest, ruff) and layout (`backend/app/`, `frontend/static/`, `tests/`) already exist.

---

## Phase 2: Setup (F5 test/config scaffolding)

**Purpose**: Minimal F5-specific scaffolding; no app behavior yet.

- [X] T059 [P] Register the `real_e2e` pytest marker in `pyproject.toml` under `[tool.pytest.ini_options]` (`markers = ["real_e2e: opt-in real Hermes end-to-end mission; also requires F5_REAL_E2E=1"]`) so the default `uv run pytest -q` gate can exclude the one real test (FR-023)
- [X] T060 [P] Add `data/runs/` to `.gitignore` for per-mission executor workdirs (`data/runs/<mission_id>/`, gitignored per contracts/hermes-executor.md rule 3)

**Checkpoint**: Marker registered, workdir path ignored — F5 tests and executor runs leave no untracked residue.

---

## Phase 3: Foundational (Blocking Prerequisites)

**Purpose**: Shared definitions every user story depends on. **⚠️ No user story work can begin until this phase is complete.**

### Tests first (intentionally failing until T063–T068 land)

- [X] T061 [P] Write foundational tests for profiles + run limits in `tests/test_agent_profiles.py` (exactly three profiles with ids `researcher`/`critic`/`summarizer`, ids unique, `terminal` appears in at most one profile's `toolsets` (least-privilege pin); `output_sections` verbatim: Researcher `["findings","sources","uncertainties","handoff_note"]`, Critic `["issues","evidence","remaining_uncertainty","review"]`, Summarizer `["main_conclusion","key_findings","caveats","what_agents_did"]`; RunLimits defaults verbatim: `step_timeout_seconds=300`, `run_budget_seconds=240`, `max_turns=8`, `max_output_chars=20000`, `quota_warn_threshold_pct=50.0`, `quota_block_threshold_pct=35.0`, `usage_cache_seconds=60`, each overridable by its data-model.md env var `F5_*`)
- [X] T062 [P] Write quota gate tests in `tests/test_quota_gate.py` (block start when monthly remaining < 35.0 without confirmation, allow with `confirm_low_quota=true`, warn below 50.0%, `available=false` ⇒ fail-open with visible "quota unknown" note, 60s result cache) per research.md §7 — fails until T068

### Implementation

- [X] T063 [P] Implement `RunLimits` config with env overrides in `backend/app/agents/settings.py` (defaults exactly as pinned in T061; `usage_cache_seconds` fixed at 60)
- [X] T064 [P] Implement `AgentProfile` definitions (Researcher/Critic/Summarizer: `id`, `title`, `instructions`, `toolsets`, `output_sections`) in `backend/app/agents/profiles.py` with the data-model validation (exactly three, unique ids, `terminal` in at most one `toolsets`; Researcher `toolsets="terminal"`, Critic/Summarizer tool-free sentinel `toolsets="none"` — the profile value behind the pinned CLI literal **`-t none`**; omitting `-t` is forbidden (it would enable Hermes default toolsets), the benign `Warning: Unknown toolsets: none` must never surface as output or failure, and the zero-`tool_execution_*` confirmation is NOT this task's — it belongs to the bounded verification invocation in T072 (contracts/hermes-executor.md rule 6))
- [X] T065 [P] Extend `Mission` additively in `backend/app/missions/models.py` (all default-valued so F1–F4 tests stay valid): `objective: str | None`, `agent_runs: list[AgentRunRecord]`, `failed_step_id: str | None`, `retry_count: int = 0`, `resolved_model: str | None` (`"{default} @ {provider} ({api_mode})"`), `quota_note: str | None`; add `AgentRunRecord` per data-model.md (`step_id`, `profile`, `agent_id`, `task_input`, `output` bounded "≤ 20,000 chars", `status` ∈ `pending|running|completed|failed`, `error`, `tool_calls`, timestamps, `duration_seconds`, `session_id`)
- [X] T066 [P] Define the `AgentExecutor` protocol + `StepContext` + `AgentStepResult` + typed errors (`AgentStepTimeout`, `AgentToolError`, `AgentExitedError`, `AgentOutputError`) in `backend/app/agents/executor.py` per contracts/hermes-executor.md "Interface (protocol)" — protocol only, no subprocess yet (that is T071)
- [X] T067 [P] Implement `modelinfo.resolve()` pin guard in `backend/app/agents/modelinfo.py` (run `hermes config get model`; require `default == muse-spark-1.3-contributor` and `provider == opencode-go`, else raise a refusal instructing re-run of the PRD §8 pre-flight — no silent model switch, FR-011)
- [X] T068 [P] Implement `quota.check(overrides_confirm) -> QuotaDecision {allowed, needs_confirmation, remaining_pct, note}` in `backend/app/agents/quota.py` (`hermes usage --json`, 60s cache, fail-open on `available=false` with visible warning) per research.md §7

**Checkpoint**: Profiles, limits, Mission fields, executor protocol, model pin, and quota gate exist — all user stories can now proceed.

---

## Phase 4: User Story 1 — Run the Full Serial Mission End-to-End from the Terminal (Priority: P1) 🎯 MVP

**Goal**: `uv run python -m backend.app.cli run "topic"` executes Researcher → Critic → Summarizer through the real Hermes CLI with programmatic handoffs, F3 `branch_context` as a real Researcher input, real final result — terminal-runnable first (FR-017).

**Independent Test**: Quickstart Flow 2 + Flow 3 — start a mission from the terminal; from the persisted event log and mission record alone, verify three ordered agent executions, Critic's `task_input` contains the Researcher's output and Summarizer's contains both (SC-002), Researcher's `task_input` includes the branch instruction or an explicit no-decision note (SC-003), mission ends completed with a Summarizer-derived `result_summary` (SC-005, acceptance #4).

### Tests for User Story 1

- [X] T069 [P] [US1] Write stub serial-flow tests + `FakeExecutor` in `tests/test_agent_runner.py` (FakeExecutor: scripted outputs, scripted tool events, scripted failures/timeouts with 50ms test timeouts, zero subprocesses/quota per contracts/hermes-executor.md "Fake/stub contract"; assert three ordered executions SC-001, Critic `task_input` contains Researcher output verbatim and Summarizer's contains both SC-002, branch instruction present in Researcher `task_input` SC-003 and explicit "no audience decision applied" note when `branch_context` empty, `result_summary` equals the Summarizer's real output)
- [X] T070 [P] [US1] Write the single real end-to-end test in `tests/test_agent_e2e_real.py` (double-gated: `real_e2e` marker + `F5_REAL_E2E=1`, skips otherwise so the default gate never burns quota; tiny topic; asserts three ordered executions, real handoff contents, `resolved_model` recorded, mission completed — SC-001/SC-002/SC-004/SC-009; write it now per TDD, but EXECUTE the `F5_REAL_E2E=1` run only after T072's bounded envelope + `-t none` confirmation — contracts/hermes-executor.md pins that bounded invocation before T070 is executed)

  > Attempt-2 execution note (2026-10-16): the single `F5_REAL_E2E=1` run WAS started (mission workdir `data/runs/196c871608a2/`, real session `20261016_034744_56de69` on `muse-spark-1.3-contributor`) but the harness killed the orchestrator ~40s into step 1 of 3 (60-min timeout, exit 143) — no orphan process survived, no mission completed. Per the one-run budget the E2E was NOT re-run in attempt 3; the partial run's envelope evidence (init/tool_use/tool_result lines in `stream.jsonl`) plus the earlier bounded probe (exit 0) confirm the parser contract. The opt-in test is green in the default gate (skips without `F5_REAL_E2E=1`).

  > Iteration-2 execution note (2026-10-16): the single operator-approved `F5_REAL_E2E=1` run for iteration 2 executed **exactly once, PASS** — `1 passed in 161.44s` (exit 0), fresh mission workdir `data/runs/94d530101b4c/` (hermes session `20261016_041423_ab2b7c`) — no retries, no probes; walkthrough record under T092.

- [X] T095 [P] [US1] Write the run-endpoint branch-context sequencing test in `tests/test_agent_runner.py` (FastAPI TestClient + stub executor: create → F1 `POST .../start` (mission `running`) → open/vote/resolve a poll so `apply_decision` populates `branch_context` → `POST .../run` accepted from F1-started `running` with no active F5 runner → Researcher's composed `task_input` contains the branch instruction, exactly one `mission_started` total (SC-003 API path); plus the distinct 409s: `paused`/`completed`/`failed` → 409, active F5 runner → "mission is already executing", another mission running → 409 — per contracts/workflow-api.md "Branch-context sequencing"; F1–F4 routes unchanged)

### Implementation for User Story 1

- [X] T071 [US1] Implement the `HermesCliExecutor.run` subprocess adapter in `backend/app/agents/executor.py` (exact argv per contracts/hermes-executor.md "Invocation": `hermes chat -Q --oneshot --query-file <tempfile> --format stream-json -t <toolsets> --max-turns <N> --run-budget <SECONDS> --in <workdir>`; task text only via `--query-file`, never `-q`, never a shell; argv-list `subprocess.Popen` on the calling thread — sync `run`, NO asyncio anywhere in F5 (single spelling pinned in contracts/hermes-executor.md "Interface (protocol)" + research.md §1); per-step wall timeout from `RunLimits` with subprocess in its own process group, SIGTERM → SIGKILL after 5s; cancel `threading.Event` polled every 0.5s; workdir `data/runs/<mission_id>/`; no credentials ever read by app code)
- [X] T072 [US1] Implement the isolated stream-json parser in `backend/app/agents/executor.py` (newline-delimited JSON from `--format stream-json`: capture `session` → `session_id`, final assistant text → step `output`, `agent_settled {aborted: true}` → step failure; unknown event types ignored, never fabricated into F5 events; tool-event mapping deliberately left to T080; envelope to be confirmed once via the bounded opt-in invocation per research.md §2 — schema drift changes only this parser)
- [X] T073 [US1] Implement task composition in `backend/app/agents/runner.py` (Researcher input = mission `objective`/title + `branch_context.current_branch_instruction` when present, else an explicit "no audience decision applied" note — never invented; Critic input = role instructions + Researcher's full output; Summarizer input = role instructions + both prior outputs; prior outputs truncated to `max_output_chars` = 20,000 before composition, per research.md §10)
- [X] T074 [US1] Implement the `SerialWorkflowRunner` core loop in `backend/app/agents/runner.py` (validate mission → compose step task → emit `agent_started` immediately before spawn with `agent_id` like `research-1` → execute via injected `AgentExecutor` → validate output non-empty and ≤ 20,000 chars → store `AgentRunRecord` → emit `agent_completed` → emit `agent_handoff {from_agent, to_agent, from_profile, to_profile, reason, summary, step_id}` → advance; one active mission via module-level lock; serial, one active agent)
- [X] T075 [US1] Add narrow state-machine transitions in `backend/app/missions/controller.py` (`advance_step` + start/complete hooks for the runner; **`retry()` transition — the SOLE owner of the `failed` → `running` status flip** (I2): it does `retry_count += 1` and emits `mission_resumed {resumed_step, retry_count}`, so neither the endpoint nor the runner ever mutates status off `failed`; controller remains owner of all status transitions and never touches subprocesses — no execution logic, per plan.md/PRD §4C and contracts/workflow-api.md `retry`)
- [X] T076 [US1] Implement `POST /api/missions/{mission_id}/run` in `backend/app/api/missions.py` per contracts/workflow-api.md (body `{"objective": ≤500 chars, "confirm_low_quota": false}`; pre-checks in order with distinct 409 details: startable = status==`created` **or** (status==`running` with NO active F5 runner — the F1-started poll window, which makes the pinned SC-003 order create → F1 `start` → open/vote/resolve poll → `run` race-free, contracts/workflow-api.md "Branch-context sequencing"; any other status, an already-executing mission, or another running mission → 409) → model pin → quota gate; on success: from `created` transition via the existing start (`mission_started`), from F1-started `running` emit **no** second `mission_started` (F1 start remains its only source); record `objective`/`resolved_model`/`quota_note`, start the runner in one daemon worker thread, return 202/mission immediately)
- [X] T077 [US1] Wire honest completion in `backend/app/agents/runner.py` + `backend/app/missions/controller.py` (mission reaches `completed` only when all three steps succeed — FR-008; `result_summary` = Summarizer's real output truncated to the model's 5000-char mission field, never synthesized by the coordinator; `resolved_model` populated from `modelinfo.resolve()` per SC-009)
- [X] T078 [US1] Implement the terminal-first CLI in `backend/app/cli.py` (`uv run python -m backend.app.cli run "topic" [--confirm-low-quota] [--mission-id ID]` and `status [<mission_id>]`; `run` validates topic ≤500 chars (else clear message, exit 2, no mission created), stores the full topic as `objective`, and derives `title` = topic truncated to 120 chars (the F1 title bound — a 121–500-char topic must never 422; long topics live in `objective`); `run` creates a mission and drives the SAME `SerialWorkflowRunner` synchronously in-process — one code path, no HTTP server; prints every event as `<seq> <type> <json data>` live; exit 0 completed / 1 failed (printing failure reason, preserved step outputs summary, retry/new-mission options) / 2 pre-flight gate failure (model pin, quota); `status` shows the three `agent_runs` with `task_input`/`output` and `resolved_model`)

**Checkpoint**: US1 fully functional and testable independently — terminal end-to-end mission works before any fancier surface (FR-017).

---

## Phase 5: User Story 2 — Watch Real Agent and Tool Activity as It Happens (Priority: P2)

**Goal**: Every agent start, real tool call, handoff, completion, and failure streams as one of the six canonical events with contract-exact keys — the existing F4 dashboard renders them with zero dashboard or protocol changes.

**Independent Test**: Quickstart Flow 4 — run a mission while subscribed to SSE; the exact sequence matches actual execution, every dashboard row maps 1:1 to an event in `GET /api/missions/{id}/events` (SC-004), no fabricated or duplicate progress, `git diff --stat frontend/` empty (FR-012).

### Tests for User Story 2

- [X] T079 [P] [US2] Write event-contract tests in `tests/test_agent_runner.py` per contracts/agent-event-payloads.md ordering invariants 1–5 (per-step `agent_started` → (`tool_started` `tool_completed`)* → `agent_completed|agent_failed`; `agent_completed(i)` precedes `agent_handoff(i→i+1)` precedes `agent_started(i+1)`; failed log has `agent_failed` + `mission_failed` and no later `mission_completed`; only the six F4 canonical agent/tool types emitted; `EVENT_TYPES` unchanged; zero `tool_started`/`tool_completed` for tool-free Critic/Summarizer steps; `tool_started` count == scripted real `tool_execution_start` count)

### Implementation for User Story 2

- [X] T080 [US2] Map real tool stream events to canonical emissions in `backend/app/agents/executor.py` (`tool_execution_start {toolName, args}` → `emit("tool_started", {agent_id, tool_name, action, step_id})` with `action` = short safe truncated summary of args, never secrets/env dumps; `tool_execution_end {toolName, result}` → `emit("tool_completed", {agent_id, tool_name, status: "completed"|"failed", summary ≤300 chars, exit_code?, step_id})` — one emission per real occurrence, success or failure, FR-013)
- [X] T081 [US2] Pin payload field shapes on runner-emitted events in `backend/app/agents/runner.py` to contracts/agent-event-payloads.md exactly (`agent_started {agent_id, profile, task: first 300 chars of composed task, step_id}`; `agent_completed {agent_id, profile, step_id, summary ≤300 chars, output_chars, tool_calls, duration_seconds, session_id}`; `agent_handoff` key families `from_agent/to_agent/summary/reason`; full untrusted output never placed in events)
- [X] T082 [US2] Verify zero frontend/protocol drift in `frontend/static/` and `backend/app/events/` (confirm `git diff --stat frontend/` is empty, `EVENT_TYPES`/`CANONICAL_EVENT_TYPES` unchanged, `app.js` `pick()` key families satisfied by T080/T081 payloads — record the evidence; no code changes expected, this is an audit task)

**Checkpoint**: US2 independently testable — dashboard agent/tool/handoff sections fill with real execution only, zero dashboard code touched (FR-012/FR-013, SC-004).

---

## Phase 6: User Story 3 — Recover Visibly When an Agent, Tool, or Model Fails (Priority: P3)

**Goal**: Any step failure (timeout, tool, model, invalid output) aborts immediately into a failed terminal state with completed outputs and reason preserved; a deliberate, recorded retry resumes at the failed step; reset during execution leaves no orphan run.

**Independent Test**: Quickstart Flow 5 + Flow 6 + Flow 7 — induce a timeout/model failure (stubbed in gates, `F5_STEP_TIMEOUT_SECONDS=5` opt-in for real): `agent_failed` with reason → `mission_failed`, remaining chain never runs, completed `agent_runs` queryable (SC-006), never a clean success (SC-007); retry emits `mission_resumed` then continues at the failed step with preserved outputs in its task input, no `agent_started` for completed steps, `retry_count` incremented (SC-010); low-quota start blocked until confirmation (SC-011); reset kills the in-flight subprocess with no orphan.

### Tests for User Story 3

- [X] T083 [P] [US3] Write abort tests in `tests/test_agent_runner.py` using `FakeExecutor` (timeout with 50ms test timeout, tool failure, model error `AgentExitedError`, empty/oversized output `AgentOutputError` → exactly one `agent_failed {failure_kind ∈ timeout|tool|model|output_invalid|cancelled}` then `mission_failed`; mission status `failed`; remaining steps never execute; completed `agent_runs` + failure reason preserved on the record; no `mission_completed` after failure — SC-006/SC-007/FR-015/FR-020)
- [X] T084 [P] [US3] Write retry-resume tests in `tests/test_agent_runner.py` (`mission_resumed {resumed_step, retry_count}` precedes the resumed step's `agent_started`; NO `agent_started` for previously completed steps; resumed step's `task_input` contains the preserved completed-agent outputs; `retry_count` increments by 1; retry 409s unless status==`failed` AND `failed_step_id` set; quota gate + model pin re-checked on retry; **payload discriminator, both sides (I4)**: F5 retry's `mission_resumed` always carries `resumed_step` + `retry_count`, while F1 pause→resume stays key-less (`status`/`current_step` only, never those keys — F1 frozen); tests assert both — SC-010/FR-021)
- [X] T085 [P] [US3] Write reset-during-execution test in `tests/test_agent_runner.py` (start a stubbed run, trigger reset mid-step → cancel event stops the step at the next 0.5s poll, no further agent events, mission returns to `created`, no orphan execution — spec edge case / quickstart Flow 7)

### Implementation for User Story 3

- [X] T086 [US3] Implement failure mapping + abort in `backend/app/agents/runner.py` (map each typed executor error to `agent_failed {agent_id, profile, step_id, error, failure_kind}` emitted exactly once, then `controller.fail(...)` → FAILED terminal immediately; set `failed_step_id`; never continue the chain, never auto-retry, never auto-skip; completed `AgentRunRecord`s and reason preserved on the mission — FR-014/FR-016/FR-020)
- [X] T087 [US3] Implement `POST /api/missions/{mission_id}/retry` in `backend/app/api/missions.py` per contracts/workflow-api.md (409 unless status==`failed` && `failed_step_id` set; re-check model pin + quota gate exactly like `run`; then invoke the controller's narrow `retry()` transition (T075) — the **sole owner** of the `failed` → `running` status flip, the `retry_count += 1`, and the `mission_resumed {resumed_step, retry_count}` emission (I2; the endpoint never mutates status or emits); return 202/mission; fresh full re-run remains "create a new mission" only)
- [X] T088 [US3] Implement retry-resume in `backend/app/agents/runner.py` (set `current_step_index` to the failed step, compose its task from the stored prior `agent_runs` outputs, re-enter the loop there; completed agents are not re-executed and emit no events; `failed_step_id` cleared only when execution advances past that step)
- [X] T089 [US3] Add the `retry <mission_id> [--confirm-low-quota]` subcommand to `backend/app/cli.py` (same runner/resume path, same exit codes as `run`: 0/1/2)
- [X] T090 [US3] Wire reset-during-execution cancellation in `backend/app/api/missions.py` + `backend/app/agents/runner.py` (reset sets the mission's runner cancel `threading.Event` and kills the in-flight subprocess before the existing reset transition; the same F5 reset wiring also clears the F5 run-scoped fields — `agent_runs`, `failed_step_id`, `retry_count`, `resolved_model`, `objective`, `quota_note` — so no stale run state survives into the next `created` run (mirrors F1 reset clearing `result_summary`/`outcome`/`error`; F1 `controller.reset` untouched — U1); response shape unchanged; no orphan `hermes` process survives — spec edge case / quickstart Flow 7)

**Checkpoint**: All user stories independently functional — happy path (US1), live real events (US2), visible failure + recovery (US3).

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Gates, validation walkthrough, regression guard. No F1–F4 re-implementation.

- [X] T091 Run both quality gates (`uv run ruff check .`, `uv run pytest -q`) and fix only F5-attributable failures in the new F5 files — the 57-test baseline must stay green untouched and the default run must never invoke the model (`real_e2e` test reports "skipped" without `F5_REAL_E2E=1`); do not edit F1–F4 tests to force a pass (FR-019/FR-023/SC-008; tester runs commands — no claimed pass without execution evidence)

  > Execution evidence (attempt 3, 2026-10-16): `uv run pytest -q` → **116 passed, 1 skipped** (the `real_e2e` test skips without `F5_REAL_E2E=1` — the default run invokes no model); `uv run ruff check .` → **All checks passed!**. F1–F4 baseline untouched and green (57 baseline tests included in the 116).
- [X] T092 [P] Walk quickstart Flows 1–7 end to end per `specs/004-agent-serial-workflow/quickstart.md` and record pass/fail per flow (Flow 1 step 2 — the single `F5_REAL_E2E=1` run — is the only quota-burning step; Flow 2 terminal acceptance is mandatory evidence; Flow 4 requires `git diff --stat frontend/` empty)

  > Status (attempt 3): OPEN — Flows 2/3/5/6/7 behavior is green through the stub/CLI/event-contract suites and Flow 4 is verified (`git diff --stat frontend/` empty, six event types unchanged), but the real-model walkthrough (Flow 1 step 2 = the T070 E2E) was consumed by attempt 2's harness-killed run and not repeated per the one-run budget; a future quota-approved pass is needed to close this.

  > Walkthrough record (implement iteration 2, attempt 1, 2026-10-16) — **all flows PASS, T092 closed**:
  > - **Flow 1 (quality gates)**: step 1 — `uv run pytest -q` → **116 passed, 1 skipped** (the double-gated `real_e2e` test skips by design without `F5_REAL_E2E=1`; zero model calls in the default gate), `uv run ruff check .` → **All checks passed!**. Step 2 — the single operator-approved real run: `F5_REAL_E2E=1 uv run pytest -q tests/test_agent_e2e_real.py` → **1 passed in 161.44s** (exit 0), executed exactly once with no retries, fresh mission workdir `data/runs/94d530101b4c/` (hermes session `20261016_041423_ab2b7c`, 283-line `stream.jsonl`; NOT a resume of attempt 2's `data/runs/196c871608a2`) — asserts SC-001 (three ordered executions researcher→critic→summarizer), SC-002 (real handoff contents embedded verbatim in the next step's `task_input`), SC-004 (agent/tool events 1:1 with real executions, tool events only on the Researcher step), SC-009 (`resolved_model` = `muse-spark-1.3-contributor`, `quota_note` set), mission `completed` with the Summarizer's real `result_summary` → **PASS**.
  > - **Quota note**: pre-flight `hermes usage --json` → Monthly 68% used / **32% remaining** (below the FR-024 35% gate; `F5_REAL_E2E=1` served as the operator's `confirm_low_quota`). Budget consumed: exactly 1 real run (3 Hermes steps, ~161s), 0 retries/probes.
  > - **Flow 2 (terminal end-to-end, FR-017)**: **PASS** — stubbed/CLI evidence (zero quota): `test_cli_run_and_status_stubbed_flow2`, `test_three_ordered_agent_executions_sc001`, `test_handoffs_pass_real_outputs_verbatim_sc002`, `test_objective_used_for_researcher_and_result_is_summarizer_output` (SC-005: `result_summary` = Summarizer's output, never coordinator-synthesized); the real-run corollary (3 ordered `agent_*` events → `mission_completed`, Summarizer-derived summary) is asserted by Flow 1 step 2. A real `cli run` was deliberately NOT re-executed (one-run budget).
  > - **Flow 3 (audience decision as real input, SC-003)**: **PASS** — `test_run_accepts_f1_started_running_after_decision_sc003` (create → F1 start → poll resolve → `run` 202 accepted, exactly one `mission_started`, branch instruction in Researcher `task_input`), `test_researcher_task_includes_branch_instruction_sc003`, `test_researcher_explicit_no_decision_note_when_branch_empty` (no-decision edge case, nothing invented), plus the T095 409 guards (paused/completed/failed → 409, active F5 runner, another mission running).
  > - **Flow 4 (live dashboard, real events only, US2)**: **PASS** — `git diff --stat frontend/` **empty** and `backend/app/events/` unchanged (F5 touched neither); `CANONICAL_EVENT_TYPES` in `backend/app/events/models.py` unchanged — the six F5 types (`agent_started`, `tool_started`, `tool_completed`, `agent_handoff`, `agent_completed`, `agent_failed`) present, zero protocol drift (T082 audit re-confirmed); F4 dashboard contract tests green in the gate. Audit-only, no code changes.
  > - **Flow 5 (failure, abort, retry-resume, US3)**: **PASS** via the gate-path stubbed suite — `test_abort_to_failed_terminal` (`agent_failed {failure_kind}` → `mission_failed`, remaining chain never runs, completed `agent_runs` preserved), `test_abort_on_empty_and_oversized_output`, `test_failed_log_has_no_mission_completed` (SC-007), `test_retry_resumes_at_failed_step_no_reexecution` (no `agent_started` for completed steps, preserved outputs in resumed task, `retry_count` +1 — SC-010), `test_retry_409_guards_and_gate_recheck`, `test_f1_resume_stays_keyless_discriminator` (I4 payload discriminator). Real failure/retry NOT induced on the model (would burn the one-run budget).
  > - **Flow 6 (quota gate + usage controls)**: **PASS** — live: pre-flight showed Monthly **32% remaining < 35%**, so the gate engaged for real and the run proceeded only via confirmation (Flow 1 step 2); `test_block_start_below_threshold_without_confirmation` / `test_allow_below_threshold_with_confirmation` / `test_run_preflight_blocks_on_low_quota` (SC-011); CLI blocks with exit 2 on `ModelPinError`/`LowQuotaError` (`backend/app/cli.py` run + retry paths, wired to the same pre-flight); concurrency second-`run` 409 via `test_run_409_when_another_mission_running`.
  > - **Flow 7 (reset during execution)**: **PASS** — `test_reset_during_execution_no_orphan` (reset mid-step cancels at the 0.5s poll, no further agent events, mission returns to `created`, no orphan execution); `pgrep -f hermes` clean before and after this iteration's real run.
  > - **Regression (F1–F4)**: no suspected failures → no targeted re-investigation needed; the full default gate is green (57 baseline tests included in the 116 passed) and `git diff --stat frontend/` stays empty.
- [X] T093 [P] Audit model-strategy honesty per FR-010/FR-011/SC-009 (pre-flight evidence path `.agent/pi/f5-preflight/2026-10-15T21-48-43-554Z_4af17e/report.json` referenced wherever the model strategy is recorded, free-tier deviation documented as a known caveat, `resolved_model` populated per mission from the runtime-resolved value, pin refusal path covered by a test)
- [X] T094 Regression guard ONLY (no redo): on any suspected F1–F4 failure, investigate via existing `tests/test_missions.py`, `tests/test_events.py`, `tests/test_health.py`, `tests/test_participants.py`, `tests/test_polls.py`, `tests/test_dashboard.py` — do NOT re-run T001–T058 wholesale; verify `frontend/` untouched by F5

---

## Dependencies & Execution Order

### Phase Dependencies

```text
Phase 1 (T001–T058 DONE — baseline, no work)
  └─▶ Phase 2 Setup (T059 marker + T060 gitignore — parallel, independent files)
        └─▶ Phase 3 Foundational (T061/T062 tests first, T063–T068 parallel-safe across distinct files)
              ├─▶ Phase 4 US1 / MVP (T069–T078 + T095): T069+T070+T095 tests ∥ → T071→T072 executor (T072's bounded confirmation strictly before any T070 real execution) → T073+T074 runner → T075 controller (incl. the retry() transition) → T076 endpoint (SC-003 run sequencing) → T077 completion → T078 CLI
              ├─▶ Phase 5 US2 (T079–T082): needs US1 runner/executor emitting events (T074, T080 extends T072's parser)
              └─▶ Phase 6 US3 (T083–T090): needs US1 runner + endpoint (T074, T076) and re-check gates (T067, T068)
                    └─▶ Phase 7 Polish (T091 validation → T092/T093 ∥ → T094 guard)
```

- **Setup (Phase 2)**: no dependencies.
- **Foundational (Phase 3)**: depends on Setup; BLOCKS all user stories.
- **US1 (Phase 4)**: after Foundational — no dependency on other stories. **MVP.**
- **US2 (Phase 5)**: after Foundational; practically needs US1's runner + stream parser (same files, `executor.py`/`runner.py`) — sequence after US1, not parallel with it.
- **US3 (Phase 6)**: after Foundational; builds on US1's runner and the run endpoint (same files) — sequence after US1.
- **Polish (Phase 7)**: after whichever stories are in scope (minimum: US1; full: all three).

### Within Each User Story

- Tests (T061/T062, T069/T070/T095, T079, T083–T085) are written FIRST and must FAIL before their implementation lands (TDD); T070's single real execution is deferred until after T072's bounded confirmation (see T070).
- Records/protocols before services; runner before endpoints; endpoint before CLI; story complete before the next priority phase.
- US2 and US3 both touch `executor.py`/`runner.py` — run them sequentially after US1, not against each other.

### Parallel Opportunities

- Phase 2: `T059 ∥ T060`.
- Phase 3: `T061 ∥ T062` (test files) ∥ `T063 ∥ T064 ∥ T065 ∥ T066 ∥ T067 ∥ T068` (six distinct modules).
- US1: `T069 ∥ T070` (two distinct test files) + T095 (same file as T069 — sequence within the file) before implementation; `T073 ∥ T074` cannot parallel (same file) — but `T071/T072` (executor.py) ∥ `T073/T074` (runner.py) can overlap once T066 exists.
- US2: `T079` (tests) ∥ `T080/T081` (executor/runner) by file; `T082` anytime after T081.
- US3: `T083 ∥ T084 ∥ T085` (one test file — sequence within the file or split commits; no cross-deps) then implementation `T086 → T087/T088 ∥ T089/T090`.
- Polish: `T092 ∥ T093`.

---

## Parallel Example: User Story 1

```bash
# Tests first (both fail until implementation):
Task T069: "Stub serial-flow tests + FakeExecutor in tests/test_agent_runner.py"
Task T070: "Real E2E test (marker + F5_REAL_E2E=1) in tests/test_agent_e2e_real.py"

# Then executor track ∥ runner track (different files):
Task T071: "HermesCliExecutor subprocess adapter in backend/app/agents/executor.py"
Task T073: "Task composition in backend/app/agents/runner.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 2 Setup (T059–T060) + Phase 3 Foundational (T061–T068).
2. Phase 4 US1 (T069–T078 + T095): tests → executor → runner → endpoint → CLI.
3. **STOP and VALIDATE**: `uv run ruff check .` + `uv run pytest -q` green; terminal `uv run python -m backend.app.cli run "topic"` completes a real serial mission (quickstart Flow 2); optional single `F5_REAL_E2E=1` run.
4. Demo: terminal end-to-end is the acceptance path (FR-017).

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. US1 → terminal end-to-end (MVP) → gates green.
3. US2 → live dashboard shows only real events, zero frontend diff → gates green.
4. US3 → abort/retry/reset recovery + quota-gate confirmation → gates green.
5. Polish: quickstart Flows 1–7 walkthrough + regression guard (T091–T094).

### Notes

- [P] tasks = different files, no dependencies; same-file tasks (`executor.py`, `runner.py`, `tests/test_agent_runner.py`) are sequenced, never parallel.
- Story labels map tasks to spec.md user stories for traceability; Setup/Foundational/Polish carry no story label.
- Nothing here re-opens settled facts: six event types only, abort-to-failed-terminal + resume-at-failed-step, `terminal` → Researcher only, stub + one opt-in real E2E, 35% quota gate, model pin with re-pre-flight on change, F1–F4 frozen at T001–T058.
- Commit after each task or logical group when implementation begins (this tasks-stage session makes no commits).
