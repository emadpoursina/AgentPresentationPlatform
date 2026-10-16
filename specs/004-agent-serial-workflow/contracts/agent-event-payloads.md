# Contract: F5 Agent/Tool Event Payloads

**Feature**: [spec.md](../spec.md) | **Plan**: [plan.md](../plan.md) | **Date**: 2026-10-15

F5 emits **only** these six canonical types (FR-012) — all already in `EVENT_TYPES` and already rendered by F4's `frontend/static/app.js` with zero client changes. Every emission maps 1:1 to a real execution occurrence (FR-013). Key names are pinned against `app.js`'s `pick()` key families so the dashboard renders them without fallbacks.

All events: `mission_id` = owning mission, `timestamp` = emission UTC, `id` = store sequence (unchanged F1 envelope).

## `agent_started` — emitted immediately before the Hermes subprocess for a step is spawned

```json
{
  "agent_id": "research-1",
  "profile": "researcher",
  "step_id": "research",
  "task": "first 300 chars of the composed task text…"
}
```
`app.js` keys consumed: `agent_id` (row key), `profile`, `task`.

`agent_id` scheme: `<slug>-<attempt>`, where attempt counts starts of that step in this mission — first attempt `research-1` (ids exactly as exemplified in this contract: `research-1`, `critic-1`); a retried step's next start increments the numeric suffix (`research-2`, `critic-2`). Every attempt gets its own id, so the append-only log stays unambiguous and the dashboard renders each attempt as its own row (no overwrite).

## `tool_started` — one per real `tool_execution_start` in the Hermes stream

```json
{
  "agent_id": "research-1",
  "tool_name": "terminal",
  "action": "ls data/runs",
  "step_id": "research"
}
```
`action` = short, safe, truncated summary of the tool args (command text for `terminal`); never includes secrets/env dumps.

## `tool_completed` — one per real `tool_execution_end` (success or failure)

```json
{
  "agent_id": "research-1",
  "tool_name": "terminal",
  "status": "completed",
  "summary": "stdout excerpt truncated to 300 chars…",
  "exit_code": 0,
  "step_id": "research"
}
```
`status` ∈ `completed | failed`; on failure `summary` carries the error excerpt. Full output is never placed in events (untrusted + size).

## `agent_handoff` — emitted after a step's output is validated and composed into the next step's task input

```json
{
  "from_agent": "research-1",
  "to_agent": "critic-1",
  "from_profile": "researcher",
  "to_profile": "critic",
  "reason": "critique the findings per the predefined workflow",
  "summary": "first 300 chars of the handed-off output…",
  "step_id": "critique"
}
```
`app.js` keys consumed: `from_agent`, `to_agent`, `summary`, `reason`.

## `agent_completed` — emitted only after subprocess exit 0 + output validation + record stored

```json
{
  "agent_id": "research-1",
  "profile": "researcher",
  "step_id": "research",
  "summary": "first 300 chars of the real agent output…",
  "output_chars": 4821,
  "tool_calls": 2,
  "duration_seconds": 47.3,
  "session_id": "01a1…"
}
```
`app.js` keys consumed: `agent_id`, `profile`, `summary`.

## `agent_failed` — emitted exactly once per aborted step (timeout / tool / model / invalid output)

```json
{
  "agent_id": "critic-1",
  "profile": "critic",
  "step_id": "critique",
  "error": "step timeout after 300s (killed)",
  "failure_kind": "timeout"
}
```
`failure_kind` ∈ `timeout | tool | model | output_invalid | cancelled`. Followed (in order) by the existing `mission_failed` lifecycle event — never by `mission_completed` (FR-015/SC-007).

## Ordering invariants (asserted by tests)

1. Per step: `agent_started` → (`tool_started` `tool_completed`)* → `agent_completed` | `agent_failed`.
2. Between consecutive steps: `agent_completed(step i)` precedes `agent_handoff(i→i+1)` precedes `agent_started(step i+1)`.
3. A failed mission's log contains `agent_failed` and `mission_failed`, and no `mission_completed` after the failure.
4. Retry: `mission_resumed {resumed_step, retry_count}` precedes the resumed step's `agent_started`; **no** `agent_started` for previously completed steps (SC-010). The presence of `resumed_step`/`retry_count` **is** the discriminator for the shared `mission_resumed` type: F1's pause→resume keeps its key-less payload (`status`/`current_step` only, never these keys — F1 code frozen); F5 retry always carries both keys. Tests assert both sides: F1 `resume` emits no `resumed_step`/`retry_count`, F5 retry emits them.
5. Counts match reality: number of `tool_started` events == number of real `tool_execution_start` lines in the recorded Hermes stream (spot-checkable in the opt-in real run; SC-004).
