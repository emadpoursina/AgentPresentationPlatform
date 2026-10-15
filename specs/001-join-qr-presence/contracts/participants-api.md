# API Contracts: Participants & Join Info (F2)

**Feature**: [../spec.md](../spec.md) | **Data model**: [../data-model.md](../data-model.md)

Base: same app as existing `/api/missions` and `/api/*/events` routes. JSON only. Errors use `{"detail": "..."}` (existing `HTTPException` style).

## GET /api/join-info

Returns what the presentation screen encodes and shows.

- **200**: `{ "join_url": "http://<lan-host>:<port>/join.html", "qr_url": "/api/join-info/qr", "ready": true }`
- When only a loopback address resolves: `200` with `"ready": false`, a non-advertised `join_url`, and the page shows setup guidance instead of a QR (FR-014/FR-015).
- `qr_url` serves a freshly generated code for the current `join_url` on every request (FR-002).

## GET /api/join-info/qr

- **200**: QR image encoding the current `join_url` (content type image/svg or image/png). Generated per request, never cached stale.
- Mirrors the not-ready rule above: no scannable code for an unreachable target.

## POST /api/participants/join

- **Body**: `{ "display_name": "Ada" }` or `{}` / `{"display_name": null}` for anonymous.
- **201**: `{ "id": "<opaque>", "display_name": "Ada" | null, "anonymous": true|false, "status": "connected", "joined_at": "<utc>" }`. Emits `participant_joined` (session scope).
- **400**: empty, whitespace-only, longer than 30 chars, or disallowed characters. Nothing recorded; roster and count unchanged (FR-007). Example: `{"detail": "Display name must be 1-30 characters: letters, numbers, spaces, - _ ' . ,"}`.

## POST /api/participants/{id}/heartbeat

- **200**: `{ "id": "<id>", "status": "connected", "last_seen_at": "<utc>" }`. Refreshes `last_seen_at`.
- **404**: `{"detail": "participant not found"}` for unknown ids.

## POST /api/participants/{id}/leave

- **200**: `{ "id": "<id>", "status": "left" }`. Idempotent (leaving twice still 200). Emits `participant_left` once per transition to non-connected.
- **404**: unknown id.

## POST /api/participants/{id}/rejoin

- **200**: same shape as join response with the original `id` and `joined_at` preserved, `status: "connected"`. No new record, no double count.
- **404**: unknown id.

## GET /api/participants

- **200**: `{ "count": <live-connected-int>, "participants": [ { "id", "display_name", "anonymous", "status": "connected", "joined_at" } ] }`. Lists current roster only (connected members). Names are plain data; clients must render with `textContent`.

## SSE event types (new, session scope)

- `participant_joined`: data `{ "participant_id": "<id>", "display_name": "<name>" | null, "anonymous": bool, "count": <live-int> }`.
- `participant_left`: data `{ "participant_id": "<id>", "reason": "left" | "timeout", "count": <live-int> }`.
- Both use `mission_id: "session"` and appear on the global stream/history (`GET /api/events/history`, `GET /api/events/stream`); the frontend adds both types to its SSE subscription list. Emitted exactly once per real transition (no fabricated presence).

## Validation & error conventions

- All name rules enforced server-side (Pydantic validators); client checks are UX-only.
- Unknown participant id → 404; invalid name → 400; both with `{"detail"}` bodies.
- No authentication (per spec: no accounts); presenter-only actions are out of scope for F2 (no privileged participant endpoints).
