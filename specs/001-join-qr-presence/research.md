# Research: Join with QR Code and Presence (F2)

**Feature**: `specs/001-join-qr-presence/spec.md` | **Date**: 2026-10-15

No `NEEDS CLARIFICATION` items remained in Technical Context (all values resolved from the repo: Python 3.12, FastAPI/Pydantic, in-memory storage, pytest/ruff, LAN web app). Research below resolves the technology and pattern choices the plan depends on.

## 1. QR code generation

- **Decision**: Generate the QR code server-side with the already-declared `qrcode[pil]` 8.2 dependency, rendered per request from the currently resolved join URL (served as an image/SVG from the join-info endpoint or embedded in the presentation page). Never cache a static QR image.
- **Rationale**: The dependency is already in `pyproject.toml`, so no new dependency or frontend library is needed; per-request generation guarantees FR-002 (code always matches the current reachable address); any phone camera can scan it with no app install.
- **Alternatives considered**: Client-side JS QR library — rejected (contradicts the dependency-free vanilla frontend and duplicates a capability the backend already has); static pre-generated QR image — rejected (goes stale when the hotspot address/port changes, violating FR-002).

## 2. Live presence mechanism

- **Decision**: Explicit join registry with server-issued participant ids, a lightweight heartbeat endpoint, and a timeout sweep. Explicit `leave` decrements immediately; silent drops decrement on timeout (proposed default: heartbeat ~15s, timeout ~45–60s; tasks phase finalizes). Rejoin presenting a known id restores the same record without double-counting.
- **Rationale**: Satisfies the clarified live-connected-count requirement with immediate updates for explicit leaves and eventual correctness for silent disconnects; rejoin-without-double-count falls out of id-keyed records; independent of SSE connection state, so join-page-only visitors are still counted.
- **Alternatives considered**: Counting SSE stream subscribers — rejected (couples presence to event-stream subscription; proxies/NATs drop idle streams; misses participants not currently streaming); cumulative-only counter — rejected (contradicts the clarify decision for live connected count and overstates presence after disconnects).

## 3. LAN join-URL discovery (what the QR encodes)

- **Decision**: Resolve the advertised base URL per request with precedence: explicit config/env override → inbound `Host` header on the join-info request → socket-based LAN IP detection. If the resolved target is loopback-only, report it as not-ready (with setup guidance) rather than encoding it in the QR.
- **Rationale**: Hotspot addresses change per session, so no hardcoded URL can satisfy FR-002/FR-014; `Host`-header reflection is correct behind the presenter's own network while the override covers port-forwarding edge cases; refusing to advertise loopback prevents the most common QR-points-nowhere failure.
- **Alternatives considered**: Hardcoded join URL — rejected (breaks across hotspots/ports); mDNS hostname — rejected (unreliable on phone hotspots with client isolation); always using the socket IP — rejected (wrong when bound to a specific interface or behind a relay; kept only as fallback).

## 4. Participant identity and duplicate names

- **Decision**: Opaque server-issued participant id (same style as mission ids, e.g. short random hex) returned at join and stored client-side for heartbeat/rejoin/leave. Roster and counts are keyed by id; display names are labels only, so duplicates are naturally distinguished (FR-011).
- **Rationale**: No accounts or PII (FR-013); id-keying makes duplicate names, rejoin-dedup, and per-participant leave all trivial; consistent with the existing `_new_id()` pattern in the mission controller.
- **Alternatives considered**: Name-keyed identity — rejected (collisions merge distinct people); IP-keyed identity — rejected (hotspot NAT shares addresses across devices).

## 5. Display-name validation (Balanced 30)

- **Decision**: Enforce server-side with Pydantic validators as the authority: trim surrounding whitespace, reject empty/whitespace-only, max 30 characters, allow letters, numbers, spaces, and `- _ ' . ,`; reject everything else (including markup and emoji) with a 400 + clear message. The client may mirror the rule for UX, but the server decision stands. All stored names are rendered via `textContent` only.
- **Rationale**: Implements the clarify decision exactly; Pydantic validators sit beside the existing event/mission models; `textContent`-only rendering (already the F1 client pattern) makes even allowed characters safe by construction.
- **Alternatives considered**: Allowing emoji/full-Unicode symbols — rejected (grapheme counting and rendering-width abuse in a demo setting; letters already cover non-English names); client-side-only validation — rejected (violates FR-006).

## 6. Presence events on the activity stream

- **Decision**: Add `participant_joined` and `participant_left` to the extended event-type list (same additive pattern F1 used for lifecycle events); emit them on the existing event store/SSE with session scope (see data-model for the `session` scope convention). The frontend subscribes to the two new types alongside the existing list. No EventStore API change.
- **Rationale**: Real events only — one event per actual join/leave, reusing the lossless replay/Last-Event-ID machinery; additive types keep the F1/F3/F5 contract intact.
- **Alternatives considered**: A separate presence channel — rejected (duplicates SSE infrastructure for two event types); stuffing presence into mission events — rejected (presence is presentation-level, not mission-level; missions are serial and replaceable).

## 7. Setup / reachability guidance

- **Decision**: Ship static setup notes (hotspot device-to-device permission, firewall, port binding — FR-015) plus a live self-check on the presentation page: show the resolved advertised URL and whether it is LAN-reachable or loopback (not-ready state), so the presenter verifies reachability with a second device before the audience scans.
- **Rationale**: Directly serves User Story 4 and the most common live-demo failure mode; the not-ready state prevents advertising an unreachable QR.
- **Alternatives considered**: Automated cross-device probing from the server — rejected (the server cannot observe the audience device's network path; a human check with a second device is the only honest signal).
