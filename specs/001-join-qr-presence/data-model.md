# Data Model: Join with QR Code and Presence (F2)

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-15

## Entities

### Participant

One joined device/person in the presentation session. Keyed by server-issued id; display name is a label only.

| Field | Type | Rules |
|-------|------|-------|
| `id` | string (opaque, server-issued) | Unique per joiner; same style as mission ids (short random hex); never reused |
| `display_name` | string \| null | Null = anonymous. When present: trimmed, 1–30 chars, only letters, numbers, spaces, `- _ ' . ,`. Server-validated (FR-006); rendered as plain text (FR-012) |
| `anonymous` | boolean | Derived: true when `display_name` is null |
| `status` | `connected` \| `left` \| `timed_out` | Set by join / explicit leave / timeout sweep |
| `joined_at` | UTC timestamp | Set once at join; never changes on rejoin |
| `last_seen_at` | UTC timestamp | Updated by join, heartbeat, and rejoin; drives timeout |

**State transitions**:

```text
absent --join--> connected --leave--> left
              connected --timeout--> timed_out
              left/timed_out --rejoin (same id)--> connected  (no new record, no double count)
```

Invalid join submissions (empty, whitespace-only, >30 chars, disallowed characters) create no record and do not affect the roster (FR-007).

### Presence Roster

The live presence derived from participants. Not stored separately — computed.

- **Membership**: participants with `status == connected` and `last_seen_at` within the timeout window.
- **Live count**: size of membership; shown on the presentation screen (FR-008); updated within seconds of join/leave/timeout without manual refresh (FR-009).
- **Scope**: presentation-session global (not per-mission). Session-scoped, in-memory only; no persistence (spec Assumptions).
- **Duplicates**: two participants may share a display name; they remain distinct records and both count (FR-011).

### Join Reference

The advertised way in. Not stored — resolved per request (research §3).

| Field | Type | Rules |
|-------|------|-------|
| `join_url` | URL string | The actual LAN URL participants must open; never loopback-only as an advertised target (FR-014) |
| `qr_payload` | same URL | Byte-identical to `join_url`; regenerated per request, never cached stale (FR-002) |
| `ready` | boolean | False when only a loopback address can be resolved → page shows not-ready + setup guidance instead of a QR |

## Relationships

- Roster **aggregates** Participants (one-to-many, derived, not a foreign key).
- Join Reference is **independent** of both (no link to roster or missions).
- `participant_joined` / `participant_left` events **reference** a participant id in their event data and use the `session` scope convention below.

## Event scope note

`ActivityEvent.mission_id` currently reads "owning mission identifier". F2 uses the value `"session"` for `participant_joined` / `participant_left` to mark presentation-level events that belong to no mission. They appear on the global stream/history; per-mission histories are unaffected. (Doc-description update only; no validation change.)

## Validation summary (from spec + clarify)

- Trim → reject empty/whitespace-only → max 30 chars → charset `[letters, numbers, space, - _ ' . ,]` → else 400 with clear message, nothing recorded.
- Anonymous join (no name) is always valid and yields `display_name: null`.
- No email, phone, credential, or other PII is collected or stored (FR-013).
