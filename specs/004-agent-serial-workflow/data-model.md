# Data Model: Agent Profiles + Serial Hermes Workflow (F5)

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-15

F5 extends the F1 `Mission` record additively (all new fields have defaults → existing F1–F4 tests and API consumers stay valid) and adds in-memory-only agent execution state. No new persistence layer, no migrations. Event types are exactly the six F4-rendered canonical agent/tool types plus existing lifecycle types — no new event types.

## New entities

### AgentProfile (static, code-owned — `backend/app/agents/profiles.py`)

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | `researcher` \| `critic` \| `summarizer` — matches `MissionStep.agent_profile` (F1 default steps already use these ids) |
| `title` | `str` | Display name |
| `instructions` | `str` | Role framing (PRD §6 purpose + boundaries) |
| `toolsets` | `str` | Hermes `-t` value. Researcher: `terminal` (pre-flight-verified, FR-022). Critic/Summarizer: no-tools sentinel (tool-free). |
| `output_sections` | `list[str]` | Expected sections: Researcher `["findings","sources","uncertainties","handoff_note"]`; Critic `["issues","evidence","remaining_uncertainty","review"]`; Summarizer `["main_conclusion","key_findings","caveats","what_agents_did"]` |

Validation: exactly three profiles, ids unique, `terminal` appears in at most one profile's `toolsets` (least-privilege pin).

### AgentStepResult / AgentRunRecord (per executed step — stored on the mission)

| Field | Type | Notes |
|---|---|---|
| `step_id` | `str` | `MissionStep.id` (`research`/`critique`/`summarize`) |
| `profile` | `str` | Profile id |
| `agent_id` | `str` | Per-attempt id used as event `agent_id` — first attempt `research-1`; a retried step's next start increments the suffix (`research-2`), per contracts/agent-event-payloads.md |
| `task_input` | `str` | The exact composed task text handed to Hermes (audit trail for SC-002/SC-003) |
| `output` | `str` | Raw agent output, bounded ≤ 20,000 chars |
| `status` | `pending` \| `running` \| `completed` \| `failed` | |
| `error` | `str \| None` | Failure reason (timeout/tool/model/output-invalid) |
| `tool_calls` | `int` | Count of real `tool_execution_end` events observed |
| `started_at` / `completed_at` | `datetime \| None` | |
| `duration_seconds` | `float \| None` | |
| `session_id` | `str \| None` | Hermes session id from the stream, when present |

### QuotaSnapshot (ephemeral, cached 60s — `backend/app/agents/quota.py`)

`{fetched_at, monthly_remaining_pct: float | None, monthly_used_pct: str(raw), raw: dict, available: bool}` — parsed from `hermes usage --json`. `available=false` ⇒ start proceeds with a visible "quota unknown" warning (fail-open, research §7).

### RunLimits (config — `backend/app/agents/settings.py`)

| Field | Default | Source |
|---|---|---|
| `step_timeout_seconds` | 300 | env `F5_STEP_TIMEOUT_SECONDS` (outer kill) |
| `run_budget_seconds` | 240 | env `F5_RUN_BUDGET_SECONDS` (Hermes `--run-budget`) |
| `max_turns` | 8 | env `F5_MAX_TURNS` (Hermes `--max-turns`, request cap) |
| `max_output_chars` | 20000 | env `F5_MAX_OUTPUT_CHARS` (handoff bound) |
| `quota_warn_threshold_pct` | 50.0 | env `F5_QUOTA_WARN_THRESHOLD` |
| `quota_block_threshold_pct` | 35.0 | env `F5_QUOTA_BLOCK_THRESHOLD` (FR-024 default) |
| `usage_cache_seconds` | 60 | fixed |

## Extended `Mission` (F1 record, additive fields only)

| New field | Type | Notes |
|---|---|---|
| `objective` | `str \| None` | Operator topic override for the Researcher; falls back to `title` |
| `agent_runs` | `list[AgentRunRecord]` | Completed steps preserved across failure + retry (FR-020/FR-021) |
| `failed_step_id` | `str \| None` | Set on abort; cleared on successful resume past that step |
| `retry_count` | `int = 0` | Deliberate, recorded retries (SC-010 audit) |
| `resolved_model` | `str \| None` | `"{default} @ {provider} ({api_mode})"` from `hermes config get model` at run time (SC-009) |
| `quota_note` | `str \| None` | Warning/gate info shown before/with the run |

Existing fields (`status`, `steps`, `current_step_index`, `result_summary`, `outcome`, `error`, `branch_context`, timestamps) unchanged. `progress` semantics unchanged (workflow position only).

## State transitions (extended)

```text
created ──run (quota gate + model pin OK)──► running ──all steps ok──► completed
   ▲                                           │
   │                                           │ step failure (timeout/tool/model/output)
   │            mission_failed (reason, outputs preserved)
   │                                           ▼
   └──reset── failed ◄─────────────────────────┘
               │
               └──retry (confirm gate re-checked)──► running (resumes at failed_step_id;
                                                     no re-execution of completed steps)
```

- `run` allowed from `created` **or** from `running` when the mission was F1-started and has no active F5 runner (the poll window — race-free SC-003 sequencing, pinned in contracts/workflow-api.md); any other status, an already-executing mission, or a second mission → 409 (single active mission per process).
- `retry` allowed from `failed` only, via the controller's narrow `retry` transition — the controller owns the `failed` → `running` status flip and the `mission_resumed {resumed_step, retry_count}` emission (runner and endpoint never mutate status) — and only when `failed_step_id` is set (a failure outside a step — e.g. start-time model-pin failure — leaves nothing to resume; operator starts a new mission).
- `reset` from any state; during execution it also cancels the in-flight subprocess (runner cancel event) before resetting, so no orphan run survives (F1 behavior preserved, now with real cancellation). Reset also clears the F5 run-scoped fields — `agent_runs`, `failed_step_id`, `retry_count`, `resolved_model`, `objective`, `quota_note` — in the F5 reset wiring (F1 `controller.reset` untouched) so no stale run state survives into the next `created` run.
- Transitions reuse existing events: `mission_started`, `mission_completed`, `mission_failed`, `mission_resumed` (retry), `mission_reset`. F5 adds **no** event types.

## Event payloads (the six canonical types F5 emits)

Pinned in [contracts/agent-event-payloads.md](contracts/agent-event-payloads.md); each emission maps 1:1 to a real occurrence (FR-013):

| Event | Real occurrence it proves |
|---|---|
| `agent_started` | The Hermes subprocess for that step is about to be spawned (emitted immediately before spawn) |
| `tool_started` / `tool_completed` | A real `tool_execution_start` / `tool_execution_end` in the Hermes stream (success *or* failure) |
| `agent_handoff` | A completed step's output was validated and composed into the next step's `task_input` |
| `agent_completed` | The step's subprocess exited 0 with non-empty bounded output, stored on the mission |
| `agent_failed` | The step aborted (timeout kill, non-zero exit, tool failure, or invalid output) with the real reason |

## Relationships

```text
Mission 1─* AgentRunRecord (step_id → MissionStep)
Mission *─1 BranchContext (F3-owned, consumed read-only)
Mission 1─1 resolved_model (points at pre-flight-pinned model)
AgentRunRecord (summarizer) ─► Mission.result_summary (real output only)
```
