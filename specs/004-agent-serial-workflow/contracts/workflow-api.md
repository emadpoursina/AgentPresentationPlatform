# Contract: Workflow API + CLI + Mission Record Additions (F5)

**Feature**: [spec.md](../spec.md) | **Plan**: [plan.md](../plan.md) | **Date**: 2026-10-15

Two new routes on the existing `missions` router, additive `Mission` fields on existing routes, one new CLI entry. No new routers, no frontend change, no event-protocol change.

## New endpoints

### `POST /api/missions/{mission_id}/run` → `202` mission | `409` | `422`

Body (JSON, all optional):

```json
{ "objective": "optional operator topic override (≤500 chars)",
  "confirm_low_quota": false }
```

Behavior (pre-checks, in order — each failure is a distinct 409 detail string):

1. Mission exists and is startable by F5: status == `created` (normal path), **or** status == `running` with **no active F5 runner for that mission** (the F1-started poll window: `POST .../start` moved the mission to `running` so the F3 poll could open and `apply_decision` could populate `branch_context` *before* execution begins — the runner's module-level lock/registry from T074 records which mission, if any, is executing). Any other status (`paused`/`completed`/`failed`) → `409` ("mission not runnable: <reason>" — use resume / retry / a new mission). `409` "mission is already executing" if an F5 runner is active for this mission; `409` "another mission is already running" if any other mission is executing.
2. Model pin: `hermes config get model` must resolve to `muse-spark-1.3-contributor` @ `opencode-go` → else `409` ("resolved model changed (<value>); re-run the PRD §8 pre-flight before use", FR-011).
3. Quota gate: `hermes usage --json` monthly remaining ≥ 35% (configurable) → if below and `confirm_low_quota` is not `true`, `409` ("monthly quota below threshold (<pct>% remaining); pass confirm_low_quota to proceed", FR-024/SC-011). If usage is unavailable, proceed with a visible `quota_note` warning (fail-open, documented).

On success: if the mission was `created`, it transitions to `running` via the existing `start` transition (`mission_started` emitted); if it was already `running` (F1-started poll window), **no second `mission_started` is emitted** — F1 start remains its only source. Either way `objective`/`resolved_model`/`quota_note` are recorded, the serial workflow starts in a background worker (one runner per process), and the response returns the mission immediately. Progress is watched via the existing SSE stream (`agent_*` events) and `GET /api/missions/{id}` (new `agent_runs` fields).

**Branch-context sequencing (SC-003 race-free API path)**: the intended order is create → `POST .../start` (F1, mission `running`; polls only open while `running`) → open/vote/resolve the poll so `apply_decision` populates `branch_context` → `POST .../run`. Because `run` accepts an F1-started `running` mission with no active runner, the decision is guaranteed to exist before the runner composes the Researcher's task — no race. A poll opened *after* `run` may lose the race to composition and must not be relied on (resolving the poll before calling `run` is the operator's responsibility; stub tests inject `branch_context` directly — T069/T095). F1–F4 code is unchanged: `start`, poll lifecycle, and `apply_decision` behave exactly as frozen.

### `POST /api/missions/{mission_id}/retry` → `202` mission | `409`

Body: `{ "confirm_low_quota": false }`.

Behavior: status must be `failed` with `failed_step_id` set (else `409`); quota gate + model pin re-checked exactly as `run`; then the controller's narrow `retry` transition (research.md §4/§5) — the **sole owner of the `failed` → `running` status flip**, the only code that moves a mission off `failed`; it does `retry_count += 1` and emits `mission_resumed {…, resumed_step, retry_count}`. Neither the endpoint nor the runner mutates mission status. **Payload discriminator (I4)**: F1's pause→resume keeps its key-less `mission_resumed` payload (`status`/`current_step` only — never `resumed_step`/`retry_count`); F5 retry always carries both keys — consumers and tests key on the presence of `resumed_step`. Execution then resumes **at the failed step** with the preserved `agent_runs` outputs composed into its task input — completed agents are not re-executed and emit no events (FR-021/SC-010). A fresh full re-run remains "create a new mission".

### Existing endpoints — additive behavior only

- `GET /api/missions[/{id}]` — mission JSON now includes `objective`, `agent_runs`, `failed_step_id`, `retry_count`, `resolved_model`, `quota_note` (all default-valued; F1–F4 consumers unaffected).
- `POST /api/missions/{id}/reset` — additionally cancels any in-flight execution for that mission (kills the subprocess; runner aborts at the next 0.5s poll) before the existing reset transition, so reset-during-execution leaves no orphan run (spec edge case). The same F5 reset wiring also clears the F5 run-scoped fields — `agent_runs`, `failed_step_id`, `retry_count`, `resolved_model`, `objective`, `quota_note` — so no stale run state survives into the next `created` run (mirrors F1 reset clearing `result_summary`/`outcome`/`error`; keeps SC-002/SC-003 audits and the retry guard honest). F1 `controller.reset` itself is untouched. Response shape unchanged.
- All other routes (`complete`, `fail`, `pause`, `resume`, polls, participants, events/SSE): **unchanged**. Note: `fail`/`complete` remain manual F1 escape hatches; during a real run the runner owns them and concurrent manual calls race-guard via the mission lock (documented limitation: don't drive manual lifecycle calls during an active run).

## CLI (terminal-first acceptance path, FR-017)

```text
uv run python -m backend.app.cli run "topic" [--confirm-low-quota] [--mission-id ID]
uv run python -m backend.app.cli retry  <mission_id> [--confirm-low-quota]
uv run python -m backend.app.cli status [<mission_id>]
```

- `run` validates `topic` (must be ≤500 chars, else a clear message and exit 2 with no mission created), stores the full topic as `objective`, and creates the mission with `title` = topic truncated to 120 chars (the F1 `title` bound — a 121–500-char topic must never 422); then runs the *same* `SerialWorkflowRunner` synchronously in-process (no HTTP server required), and prints every emitted event line (`<seq> <type> <json data>`) to stdout as it happens; exits 0 on completion, 1 on failure — printing the failure reason, preserved step outputs summary, and the `retry`/`new-mission` options.
- Pre-flight-verification failures (model pin, quota gate) print the same messages and exit 2 without starting.
- Server mode works identically for observers: the dashboard at `/` renders the same events live.

## Error semantics summary

| Condition | HTTP | Meaning |
|---|---|---|
| unknown mission | 404 | existing F1 behavior |
| wrong status / concurrent run | 409 | single active mission per process; run from `created` or F1-started `running` (no active F5 runner), retry only from `failed` |
| model pin mismatch | 409 | refuse rather than silently switch models |
| low quota, unconfirmed | 409 | blocked until `confirm_low_quota: true` |
| step failure mid-run | (async) | `agent_failed` + `mission_failed`; mission ends FAILED with outputs preserved |

## Documented limitations (accepted)

- **Single-active-mission lock is per-process.** The runner lock is module-level (in-process), but the CLI (`python -m backend.app.cli`) and the uvicorn server are separate processes — a CLI `run` concurrent with a server `run` (or vice versa) bypasses the 409 and can double-burn quota. Accepted for this local single-operator demo; a cross-process file/flock guard is explicitly out of F5 scope (a new global mechanism; F1–F4 behavior stays frozen). Within one process the 409 guard holds (FR-009).

## Non-goals (this contract)

No pause-during-step control (F7), no browser tools (F6), no Q&A/Telegram (F8), no playground (F9), no new event types, no auth layer (local single-operator demo; keys stay inside Hermes).
