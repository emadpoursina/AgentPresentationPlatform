# Research: Polls, Voting, Decision-Applied Branch (F3)

**Feature**: `specs/002-polls-voting-decision/spec.md` | **Date**: 2026-10-15

No `NEEDS CLARIFICATION` items remain in Technical Context (spec Assumptions fix the 60s default deadline, 2–6 options, live-count default, presenter tie-break/no-vote selection; stack and F1/F2 reuse points resolve the rest from the repo). Research below resolves the design choices the plan depends on.

## 1. Poll state machine (open → closing → completed)

- **Decision**: Three states exactly per FR-003. `open` accepts votes; `closing` is the transient window after deadline passes or early close is signalled during which voting is already stopped and the outcome is being determined (outright winner → immediate; tie or zero votes → awaiting presenter selection); `completed` means exactly one outcome is recorded and `audience_decision_applied` has been emitted.
- **Rationale**: Matches spec Story 2 acceptance (open state, early close, completed with one outcome, visible state) and gives the dashboard something honest to show during tie-break/no-vote resolution instead of jumping open → completed or stalling.
- **Alternatives considered**: Two-state open/completed — rejected (no place to represent "voting stopped, presenter must pick" without either fabricating a winner or leaving the poll visibly open while rejecting votes).

## 2. Deadline enforcement without background threads

- **Decision**: Lazy server-side enforcement on every poll read/write path (same pattern as the F2 participant timeout sweep): each access first rolls any `open` poll whose `deadline_at` has passed into `closing`/completed. Arrival time at the server is authoritative — an in-flight vote that arrives after close is rejected and never alters the tally. Frontend shows a countdown from the server-issued `deadline_at` for UX only.
- **Rationale**: Zero timer/thread infrastructure in the single-process demo; identical to the proven F1/F2 in-memory + sweep approach; eliminates the race the spec edge case calls out (server arrival decides).
- **Alternatives considered**: `asyncio` background task per poll — rejected (lifetime/cancellation complexity across reset paths, no benefit at small-room scale); client-enforced deadline — rejected (untrusted client, violates FR-007 server-side validation).

## 3. Vote identity, replacement, and idempotent retry

- **Decision**: Votes keyed `(poll_id, participant_id) → option_id` in a dict; resubmission before close replaces the previous choice (still exactly one counted vote); resubmitting the *same* option is a 200 no-op that returns the current tally without emitting a duplicate `vote_recorded` event. Double-tap/rapid retry therefore converges to the latest valid choice with no double count (FR-006, FR-021).
- **Rationale**: Dict-keying makes "at most one per voter" structural rather than checked; no-op-on-identical-retry keeps the dashboard free of spam events while remaining honest (state genuinely unchanged).
- **Alternatives considered**: Append-only ballot log with tally-on-read — rejected (replacement and double-tap dedup become query-time concerns; harder to make idempotent).

## 4. Voter eligibility reuses the F2 roster as-is

- **Decision**: At vote arrival, the voter must satisfy `participants.get(id).status == "connected"` (post-sweep). No new identity, credential, or ballot-secrecy system; per-voter choices never leave the server — `vote_recorded` carries aggregate counts only.
- **Rationale**: Spec Assumptions and FR-022 explicitly reuse F2; aggregate-only payloads satisfy FR-015 ("individual ballot secrecy out of scope, per-voter choices MUST NOT be exposed beyond counts").
- **Alternatives considered**: Snapshot roster at poll open — rejected (a participant who times out mid-poll should arguably still have their earlier vote count; decision: votes already recorded stand, only *new/changed* submissions require connected status — simpler and matches "latest valid choice at close decides").

## 5. New event type `poll_closed` (+ optional `poll_closing`)

- **Decision**: Extend `EVENT_TYPES` additively with `poll_closed` (required by FR-015; the F1 canonical list has `poll_opened`/`vote_recorded`/`audience_decision_applied` but no close event). Optionally emit `poll_closing` when entering the transient state so the dashboard can render it; both carry `{poll_id, mission_id}` + safe metadata. No EventStore API change; `frontend/static/app.js` already subscribes to `poll_opened`/`vote_recorded`/`audience_decision_applied` — only the new close type(s) need subscribing.
- **Rationale**: Same additive-extension pattern F1 used for lifecycle events and F2 used for presence; keeps the canonical contract intact.
- **Alternatives considered**: Reusing `audience_decision_applied` as the close signal — rejected (close and decision are distinct moments when a tie/no-vote needs presenter input).

## 6. Decision-applied branch stays in the thin controller

- **Decision**: `MissionController` gains a narrow `apply_decision(mission_id, poll_id, winning_option_id, branch_map)` hook: it validates the mission is active and the poll completed, appends the winning choice to a new `Mission.branch_context` record, patches the next step's task instructions from the presenter-supplied per-option branch map given at poll open, and emits `audience_decision_applied`. No agent execution, no new framework — Hermes (F5) reads `branch_context` when running the next step.
- **Rationale**: Satisfies FR-014 ("next step follows task instructions/branch of the winning choice") while keeping the controller a coordinator per PRD 4C and the task constraint ("mission controller stays thin, Hermes owns agent execution"). Different winners → different stored instructions → observably different next steps (SC-006 testable without agents by inspecting step instructions).
- **Alternatives considered**: Branch logic in the polls controller mutating missions directly — rejected (crosses module ownership; missions must own their state machine); executable branching in-controller — rejected (that would be the second agent framework the PRD forbids).

## 7. Presenter controls and FR-020 authorization

- **Decision**: Presenter-only routes (`open`, `close`, `resolve` tie-break / no-vote selection) live under a separate router and require an `X-Presenter-Token` header **only when** `PLAYGROUND_PRESENTER_TOKEN` is configured; when unset (default LAN rehearsal), they remain same-trust open like the existing F1/F2 routes. Document the env var in quickstart; note full auth as out of scope (P2 excludes accounts).
- **Rationale**: The repo currently has no auth surface at all; a mandatory token would break F1/F2-style frictionless rehearsal, while an optional shared token satisfies FR-020's "server-side authorization" for deployments that need it with ~5 lines of code.
- **Alternatives considered**: Full presenter accounts/sessions — rejected (P2 out of scope, contradicts no-accounts principle); no authorization at all — rejected (explicitly required by FR-020).

## 8. Reveal modes and sanitized rendering

- **Decision**: `reveal_mode: live | controlled` fixed at poll open and echoed to voters. Live mode: SSE `vote_recorded` carries per-option counts; controlled mode: pre-close events carry only `{total_votes, state}` (counts hidden), full counts appear in `poll_closed`. All question/option/tally strings render via `textContent` only (existing F1/F2 client pattern), satisfying FR-019 with no sanitizer library.
- **Rationale**: Spec Story 4 acceptance is testable both ways with identical counting rules; `textContent`-only is safe by construction for the demo's threat model (same as participant names in F2).
- **Alternatives considered**: HTML-sanitizer dependency (bleach etc.) — rejected (new dependency for no gain while all rendering is text-only).
