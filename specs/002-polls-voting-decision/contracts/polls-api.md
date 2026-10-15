# Contracts: Polls & Voting API (F3)

Audience vote routes are callable by any joined participant (voter identity = F2 participant id). Presenter routes (`open`, `close`, `resolve`) require `X-Presenter-Token` only when `PLAYGROUND_PRESENTER_TOKEN` is set (research §7); otherwise same-trust open. All errors are JSON `{"detail": "..."}` with clear non-technical messages. All poll/vote strings render client-side via `textContent` only.

## POST /api/missions/{mission_id}/polls — open a poll (presenter)

Request:

```json
{
  "question": "Which direction next?",
  "options": [
    {"id": "deep", "label": "Go deeper", "branch_instruction": "Critic verifies cited sources."},
    {"id": "counter", "label": "Counterarguments", "branch_instruction": "Critic finds counterarguments."}
  ],
  "deadline_seconds": 60,
  "reveal_mode": "live"
}
```

- `question`: 1–200 chars. `options`: 2–6 items, unique ids, labels 1–80 chars. `deadline_seconds`: default 60, range 10–600. `reveal_mode`: `live` (default) | `controlled`.
- `201` → Poll view (below). `404` mission missing; `409` no active mission / another poll open (`{"detail": "..."}`); `400` validation failure; `403` bad/missing presenter token (when enforced).

## GET /api/missions/{mission_id}/polls/current — current poll state

- `200` → Poll view, or `{"poll": null}` when no open/closing poll. Joined participants poll this once then follow SSE.

## POST /api/missions/{mission_id}/polls/{poll_id}/vote — cast or change a vote

Request: `{"participant_id": "<F2 id>", "option_id": "deep"}`

- `200` → `{"poll_id": "...", "option_id": "deep", "tally": {...}, "state": "open"}`. Same-option retry returns the same shape with no new event (idempotent).
- `404` poll/participant unknown; `409` poll not open (closed/closing/completed); `403` voter not on joined roster / timed out; `400` unknown option or malformed payload. Failures never alter the tally.

## POST /api/missions/{mission_id}/polls/{poll_id}/close — early close (presenter)

- `200` → Poll view with `state: closing` (or `completed` when the tally already decides). `409` when already completed; `404` unknown poll.

## POST /api/missions/{mission_id}/polls/{poll_id}/resolve — tie-break / no-vote fallback (presenter)

Request: `{"winning_option_id": "deep"}` (must be among tied options for ties; any option or mission default for zero votes).

- `200` → completed Poll view + `audience_decision_applied` emitted; mission `branch_context` patched so the next step follows the winning option's `branch_instruction`.
- `409` when the poll is not awaiting resolution (outright winner auto-completes, no resolve needed); `400` when the choice is not eligible.

## Poll view (response shape)

```json
{
  "id": "...", "mission_id": "...", "question": "...",
  "options": [{"id": "deep", "label": "Go deeper"}],
  "state": "open", "reveal_mode": "live",
  "deadline_at": "2026-10-15T12:00:00Z",
  "tally": {"deep": 3, "counter": 1},
  "total_votes": 4,
  "outcome": null
}
```

- `tally` per-option counts appear only when `(reveal_mode == live)` or `state == completed`; otherwise only `total_votes`. `options` never include `branch_instruction` on audience-facing reads. `outcome`: null until completed, then `{"winning_option_id": "...", "decided_by": "tally|presenter_tiebreak|presenter_fallback"}`.

## SSE (existing stream, no protocol change)

`poll_opened`, `vote_recorded` (aggregate payloads per reveal mode), `poll_closed` (new type), `audience_decision_applied`. Frontend subscribes the new close type alongside the already-subscribed poll types. Reconnect/replay via `Last-Event-ID` unchanged from F1.
