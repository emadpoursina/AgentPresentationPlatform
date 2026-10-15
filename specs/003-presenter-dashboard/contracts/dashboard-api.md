# Contracts: Presenter Dashboard (F4)

No new backend endpoints or event types. The dashboard reuses existing read APIs; this file pins the fields each section consumes (all already served today).

## GET /api/missions → list (header bootstrap)

- `200` → newest entry selected by default. Empty list → header shows "No mission yet".

## GET /api/missions/{id} → header + result + influence branch

```json
{
  "id": "...", "title": "...", "status": "running",
  "steps": [{"id": "research", "title": "Research", "agent_profile": "researcher"}],
  "current_step_index": 0, "progress": 0.0,
  "result_summary": null, "outcome": null, "error": null,
  "branch_context": {"applied_decisions": [], "current_branch_instruction": null}
}
```

- Header: `title/status/steps[current_step_index]` + `progress` derived client-side as `terminal ? 1.0 : current_step_index / len(steps)` (mirrors `Mission.progress`; the property is not serialized today). Result block: `result_summary/outcome/error`.

## GET /api/missions/{id}/polls/current → influence poll

- `200` → `{"poll": {...} | null}` per F3 audience view (counts only when live/completed). Dashboard shows countdown from `deadline_at` for UX only; server arrival stays authoritative.

## GET /api/missions/{id}/events?limit=100 → history + snapshot seed

- `200` → `{"mission_id": "...", "events": [{id, type, mission_id, timestamp, data}], "last_id": n}`. Reduced in id order into the snapshot; sets `lastEventId`.

## SSE GET /api/missions/{id}/events/stream[?lastEventId=] → live tail

- `text/event-stream` with `retry: 3000`, `id:/event:/data:` per row, `: ping` heartbeat. Client subscribes to every type in `EVENT_TYPES` (canonical 11 + `mission_created/paused/resumed/failed/reset` + `participant_joined/left` + `poll_closed/poll_closing`) so F5 agent/tool rows stream with no protocol change. Malformed rows ignored.

## GET /api/participants → presence count

- `200` → `{"count": n, ...}`. Shown next to the header; updates on `participant_joined/left` events.

## Error contract (unchanged)

- Unknown mission → `404 {"detail": "mission not found"}`. Dashboard keeps last-known state + disconnected banner; never renders placeholder mission data as real.
