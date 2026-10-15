# Data Model: Polls, Voting, Decision-Applied Branch (F3)

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-15

Builds on F1 (`Mission`, `ActivityEvent`, `EventStore`) and F2 (`Participant` roster) without changing them, except additive event types and a `branch_context` addition to `Mission`.

## Entities

### Poll

One question posed during an active mission. Server-issued id (same short-hex `_new_id()` style as missions/participants).

| Field | Type | Rules |
|-------|------|-------|
| `id` | string (opaque) | Unique per poll; never reused |
| `mission_id` | string | Must reference an existing mission with status `running` (FR-010: opening outside an active mission rejected); at most one `open`/`closing` poll per mission at a time (FR-009) |
| `question` | string | 1–200 chars, trimmed, non-blank; untrusted, rendered as plain text |
| `options` | list of `{id, label, branch_instruction}` | 2–6 items (FR-001); ids presenter-defined unique short strings; labels 1–80 chars; `branch_instruction` = per-option next-step task text applied if this option wins (drives FR-014) |
| `deadline_at` | UTC timestamp | `opened_at + deadline_seconds`; `deadline_seconds` presenter-set, default 60 (FR-002), bounded (e.g. 10–600s) |
| `reveal_mode` | `live` \| `controlled` | Fixed at open, echoed to voters (FR-017); default `live` |
| `state` | `open` \| `closing` \| `completed` | Transitions below; shown to all viewers (FR-003) |
| `outcome` | null \| `{winning_option_id, decided_by, decided_at}` | Set once on completion; `decided_by ∈ {tally, presenter_tiebreak, presenter_fallback}` |
| `opened_at` / `closed_at` | UTC timestamps | `closed_at` set when voting stops |

**State transitions**:

```text
absent --open(valid mission running, no other open poll, 2-6 options)--> open
open --deadline passes (lazy sweep) or presenter close--> closing (voting stopped)
closing --outright winner--> completed (decided_by=tally)
closing --tie--> completed via presenter resolve among TIED options only (decided_by=presenter_tiebreak)
closing --zero valid votes--> completed via presenter resolve among options/default (decided_by=presenter_fallback)
```

Invalid opens (no active mission, second open poll, <2 or >6 options, blank question) create no record (spec edge cases).

### Vote

One participant's current choice in a poll. Not a separate stored row per submission — the counted state is a map.

| Field | Type | Rules |
|-------|------|-------|
| `poll_id` + `participant_id` | composite key | At most one counted entry per pair (FR-006); resubmission before close replaces |
| `option_id` | string | Must be on the poll's predefined list; write-ins impossible by validation (FR-001/FR-007) |
| `updated_at` | UTC timestamp | Last valid submission time; server arrival time decides close races |

Validation order on every submission (FR-007, all server-side, failures change nothing): poll exists → poll is `open` (FR-004) → voter `connected` on F2 roster (FR-005) → payload well-formed → `option_id` on list. Rejection = 4xx with clear message; prior vote (if any) unchanged.

### Audience Decision (applied)

The recorded outcome that selects the mission's next branch.

| Field | Type | Rules |
|-------|------|-------|
| `poll_id` | string | References the completed poll |
| `mission_id` | string | Owning mission |
| `winning_option_id` | string | Tally winner, or presenter-selected option for ties (from tied set only, FR-011) / zero votes (FR-012); never invented |
| `decided_by` | enum | `tally` \| `presenter_tiebreak` \| `presenter_fallback` |
| `applied_at` | UTC timestamp | When `audience_decision_applied` emitted |

Stored in `Mission.branch_context` (new field: `applied_decisions: list[AudienceDecision]` + `current_branch_instruction: str | None` patched from the winning option's `branch_instruction`). The mission's next step follows the patched instructions — a different winner yields observably different next-step content (FR-014, SC-006).

### Poll Activity Events (payloads, all with timestamp + mission_id)

- `poll_opened`: `{poll_id, question, options: [{id, label}], deadline_at, reveal_mode}` (branch instructions NOT broadcast to audience).
- `vote_recorded` (aggregate-safe): live mode `{poll_id, counts: {option_id: n}, total}`; controlled mode pre-close `{poll_id, total}` only (counts hidden until close).
- `poll_closed`: `{poll_id, final_counts, total, outcome_status}` (new EVENT_TYPES member; see research §5).
- `audience_decision_applied`: `{poll_id, winning_option_id, decided_by, next_step}` — the activity-history record of the applied decision (FR-013).

No event ever carries per-voter choices (FR-015). Only events for things that actually happened are emitted (FR-016).

## Relationships

- Mission 1→0..n Polls (serial: at most one non-completed poll per mission at a time).
- Poll 1→0..n Votes (keyed map, not FK rows); votes never outlive their poll's mission context.
- Poll 1→0..1 Audience Decision (exactly 1 once `completed`).
- Audience Decision → Mission.next-step branch (via `Mission.branch_context`), read by Hermes at F5 execution time.

## Validation summary

- Open: mission running, no other open/closing poll on mission, question non-blank ≤200 chars, 2–6 unique options with non-blank labels, deadline 10–600s (default 60), reveal mode valid.
- Vote: poll open, voter connected, option on list, well-formed JSON — else 4xx, tally untouched.
- Resolve: only in `closing`; tie-break choice must be among tied options; fallback choice among options or mission default; both presenter-routed (FR-020).
