# Data Model: Presenter Dashboard Real-Events-Only (F4)

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-15

F4 adds no stored entities. All sections are client-derived reductions over F1/F2/F3 state. This file pins the shapes the dashboard consumes so F5 can rely on them.

## Consumed shapes (existing, unchanged)

### Mission (F1 + F3 `branch_context`)

`GET /api/missions/{id}` → `{id, title, status, steps: [{id,title,description,agent_profile}], current_step_index, progress, result_summary, outcome, error, branch_context: {applied_decisions: [{poll_id,mission_id,winning_option_id,decided_by,applied_at}], current_branch_instruction}, created_at, updated_at}`

- `progress`: workflow position only (`current_step_index / len(steps)`, 1.0 iff terminal). Dashboard renders bar + pct + "Workflow position only" caption; never advances on timers.
- `branch_context`: influence block source (FR-006). Latest decision + full history shown.

### Poll audience view (F3)

`GET .../polls/current` → `{id, mission_id, question, options: [{id,label}], state, reveal_mode, deadline_at, tally | null, total_votes, outcome | null}` — `tally` present iff `reveal_mode == live` or `state == completed`. `branch_instruction` never exposed here (stays server-side; branch text arrives via `branch_context` / `audience_decision_applied.next_step`).

### ActivityEvent (F1 canonical + F2/F3 extensions)

`{id, type, mission_id, timestamp, data}`. Dashboard rows show `id, type, timestamp, mission_id` verbatim (FR-013). Per-type `data` usage:

- `mission_*`: header/result source (mirrors mission fetch; events are the activity proof).
- `poll_opened`: `{poll_id, question, options, deadline_at, reveal_mode}` → influence "last poll event".
- `vote_recorded`: `{poll_id, total}` (+ `counts` iff live) → influence counts.
- `poll_closing` / `poll_closed`: `{poll_id, total/final_counts, winning_option_id?, decided_by?}` → influence state/outcome.
- `audience_decision_applied`: `{poll_id, winning_option_id, decided_by, next_step}` → influence outcome + branch.
- `agent_started`: `{agent_id/name?, profile/role?, task?}` → upsert agent row `running`.
- `agent_completed` / `agent_failed`: `{agent_id/name?, summary/error?}` → agent row `completed`/`failed`.
- `tool_started`: `{tool_name/name?, action?, agent_id?}` → append tool row `running`.
- `tool_completed`: `{tool_name/name?, status?, summary/result?, error?}` → append/update tool row with safe truncated summary.
- `agent_handoff`: `{from_agent/from?, to_agent/to?, summary?, reason?}` → append handoff row (tolerate either key naming; prefer explicit, fall back to generic).
- `participant_joined` / `participant_left`: presence count (existing).

Unknown/future types: ignored by section reducers, still appended to the raw event log (forward-compatible).

## Derived snapshot (client-only, never persisted)

```text
Snapshot {
  mission: Mission | null
  agents: Map<key, {name, profile, status, task, updated_at, event_id}>
  tools: [{name, action, status, summary, event_id, timestamp}]
  handoffs: [{from, to, summary, reason, event_id, timestamp}]
  influence: {poll: PollView | null, outcome, branch_instruction, applied_decisions[]}
  result: {summary, outcome, error}  // straight from mission
  conn: connected: bool
  lastEventId: number
}
```

Reduction rules: history in id order → same `applyEvent(snapshot, ev)` as live tail; `ev.id <= lastEventId` skipped (replay dedup); sections re-render after each apply; empty maps/lists render honest empty states (FR-003/FR-006).

## Validation summary

- No F4 writes: dashboard never POSTs except existing presenter controls (mission lifecycle, poll open/close/resolve — owned by F1/F3).
- No fabrication: every row traces to one event id; progress/result trace to mission fetch which itself traces to lifecycle events.
- Truncation: tool summaries >300 chars shown truncated + "…"; full text remains in the event-log row.
- Sanitization: all strings via `textContent`; no stored HTML anywhere.
