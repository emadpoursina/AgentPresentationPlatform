# Quickstart: Agent Profiles + Serial Hermes Workflow (F5)

Validation guide for the terminal-first acceptance path. Uses `uv run` commands per AGENTS.md. F1–F4 (T001–T058) are taken as done — only the regression check below touches them. See [contracts/workflow-api.md](contracts/workflow-api.md), [contracts/hermes-executor.md](contracts/hermes-executor.md), [contracts/agent-event-payloads.md](contracts/agent-event-payloads.md), and [data-model.md](data-model.md) for exact shapes.

## Prerequisites

- `uv` + Python 3.12; Hermes v0.21.7 installed and logged in (`hermes --version`, `hermes auth status opencode-go` → logged in).
- Model pin intact: `hermes config get model` → `default: muse-spark-1.3-contributor`, `provider: opencode-go` (pre-flight evidence: `.agent/pi/f5-preflight/2026-10-15T21-48-43-554Z_4af17e/report.json`).
- Quota awareness: `hermes usage --json` (monthly window was 34% remaining at pre-flight → expect the FR-024 confirmation gate to engage below 35%).
- Gates: `uv sync --group dev`, `uv run ruff check .`, `uv run pytest -q` (57-test baseline + new F5 tests, all stubbed).

## Flow 1 — Quality gates (default, quota-free)

1. `uv sync --group dev && uv run ruff check . && uv run pytest -q` → all green; the run count is 57 + the new stubbed F5 tests; no subprocess ever calls the model (`real_e2e` test reports "skipped" without `F5_REAL_E2E=1`).
2. `F5_REAL_E2E=1 uv run pytest -q tests/test_agent_e2e_real.py` → exactly one real serial mission; asserts three ordered `agent_*` executions, real handoff contents, resolved model recorded, mission completed (SC-001/SC-002/SC-004/SC-009).

## Flow 2 — Terminal end-to-end (primary acceptance, FR-017)

1. `uv run python -m backend.app.cli run "What should a small team know before adopting coding agents?"`
2. Expect, in order on stdout: `mission_created`/`mission_started` → `agent_started` (researcher) → optional real `tool_started`/`tool_completed` pairs → `agent_completed` → `agent_handoff` → Critic step (no tool events) → handoff → Summarizer step → `mission_completed`; exit code 0.
3. The final summary printed is the Summarizer's real output (main conclusion / key findings / caveats / what the agents did) — never coordinator-synthesized (acceptance #4, SC-005).
4. `uv run python -m backend.app.cli status <mission_id>` → three `agent_runs`, each with real `task_input`/`output`; Critic's `task_input` contains the Researcher's output verbatim, Summarizer's contains both (SC-002); `resolved_model` populated (SC-009).

## Flow 3 — Audience decision as a real input (acceptance #6, SC-003)

Sequencing is pinned in [contracts/workflow-api.md](contracts/workflow-api.md): `run` accepts an F1-started `running` mission that has no active F5 runner, so the poll resolves **before** execution starts — no race, and no F1–F4 code change.

1. With the server running: `POST /api/missions` (create) → `POST /api/missions/{id}/start` (F1 start → `running`; polls only open while `running`).
2. While the mission is `running` but **before** calling `run`: open/vote/resolve a poll via the existing F3 routes so `apply_decision` populates `branch_context`.
3. `POST /api/missions/{id}/run` → 202 (accepted from F1-started `running`; no second `mission_started`). Inspect the Researcher's `agent_runs.task_input` → it contains the branch instruction text, and the Researcher's output visibly reflects it (e.g. different focus than Flow 2 on the same topic). With no decision applied, the task input explicitly says no audience direction was given — nothing invented (edge case).
4. Stub alternatives (no server/quota): inject `branch_context.current_branch_instruction` in a test (T069), or run the API sequencing test covering the create → start → poll → run order (T095).

## Flow 4 — Live dashboard, real events only (US2)

1. `uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`, open `http://<host>:8000/`.
2. `POST /api/missions` then `POST /api/missions/{id}/run` (curl); the agent/tool/handoff sections fill in live within ~2s of each real occurrence — no dashboard code changed (FR-012).
3. Spot-check: every dashboard agent/tool row has a matching event in `GET /api/missions/{id}/events` and a matching Hermes turn in the recorded session — 1:1, zero fabricated rows (SC-004).

## Flow 5 — Failure, abort, retry-resume (US3, SC-006/SC-007/SC-010)

1. Induce a failure in a stubbed run (gate path) and, for a real run, one of: set `F5_STEP_TIMEOUT_SECONDS=5` (timeout), or temporarily break Hermes config (model error).
2. Expect: `agent_failed` with the real reason → `mission_failed`; mission status `failed`; remaining chain never runs; completed `agent_runs` still queryable (SC-006); the mission can never show a clean success (SC-007).
3. `POST /api/missions/{id}/retry` (or `uv run python -m backend.app.cli retry <id>`) → `mission_resumed` → execution continues **at the failed step**; no `agent_started` for completed steps; the resumed task input contains the preserved prior outputs; `retry_count` incremented (SC-010).
4. Fresh full re-run: create a **new** mission (never a retry).

## Flow 6 — Quota gate + usage controls (FR-024, SC-011, FR-009)

1. With monthly remaining below 35% (true at time of writing): `POST .../run` without `confirm_low_quota` → 409 with the quota message and no execution; with `"confirm_low_quota": true` → run proceeds (SC-011).
2. Block at the CLI too: `cli run "topic"` without `--confirm-low-quota` exits 2 with the same message.
3. Concurrency: attempt a second `run` while one is active → 409 (one mission at a time).

## Flow 7 — Reset during execution (edge case)

1. Start a run; while the Researcher executes, `POST /api/missions/{id}/reset` → the in-flight subprocess is killed within ~1s, no further agent events appear, mission returns to `created`, no orphan `hermes` process remains (`pgrep -f hermes`).

## Regression (F1–F4, only if suspected)

- Re-run the full gate: all 57 baseline tests green (mission state machine, SSE replay, presence, polls/branch, dashboard contract). Do not re-run T001–T058 wholesale; investigate only on failure. Frontend files are untouched by F5 — `git diff --stat frontend/` must be empty.

## Expected outcomes summary

| Flow | Proves |
|---|---|
| 1 | FR-019, FR-023, SC-008 |
| 2 | FR-003/004/006/017, SC-001/002/005/009 |
| 3 | FR-005, SC-003 |
| 4 | FR-012/013, SC-004 |
| 5 | FR-014/015/016/020/021, SC-006/007/010 |
| 6 | FR-009/018/024, SC-011 |
| 7 | reset-during-execution edge case, no orphans |
