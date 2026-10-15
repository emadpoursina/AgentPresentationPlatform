# Feature Specification: Join with QR Code and Presence

**Feature Branch**: `chore/bootstrap-scaffold`

**Created**: 2026-10-15

**Status**: Draft

**Input**: User description: "F2 — Join + QR + presence (P0). Join page (display name or anonymous, no accounts), QR for actual join URL, participant count, local-bind + hotspot reachability notes. Validate every input server-side. PRD: 4B, 5.1, 10 local networking. Acceptance: PRD §13 #1."

## Clarifications

### Session 2026-10-15

- Q: When a participant disconnects or leaves, what should the presenter-visible participant count do? → A: Live connected count (decrements on leave/timeout).
- Q: What display-name length and character rules should joining enforce? → A: Balanced 30 (up to 30 chars, letters/numbers/spaces and - _ ' . , trimmed).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Join Presentation via QR Code (Priority: P1)

An audience member points their phone camera at the code shown on the presentation screen and lands directly on the join page without typing a URL or installing anything.

**Why this priority**: This is the entry gate for every audience interaction. Acceptance test §13 #1 fails without it, and all later slices (polls, Q&A, dashboard) assume participants can join.

**Independent Test**: Can be fully tested by displaying the join code on the presentation screen, scanning it with a phone on the same local network, and confirming the phone opens the join page. Delivers a working join entry point with no other features present.

**Acceptance Scenarios**:

1. **Given** the presentation is running and showing its join code, **When** a participant scans the code with their phone, **Then** the phone opens the join page for the actual network address participants must use.
2. **Given** the join code is displayed, **When** the underlying network address changes (for example a different hotspot or port), **Then** the displayed code encodes the updated address, not a stale or placeholder address.
3. **Given** a participant opens the join URL manually by typing it, **When** the address is correct and reachable, **Then** they reach the same join page as via the scan.

---

### User Story 2 - Join with Display Name or Anonymously (Priority: P1)

A participant enters a display name or joins anonymously. No account, registration, password, or prior setup is required.

**Why this priority**: PRD §5.1 requires frictionless joining. If joining requires an account, the family-audience demo fails on usability before any agent behavior is shown.

**Independent Test**: Can be fully tested by opening the join page, entering a name (or choosing anonymous), submitting, and confirming the participant is registered as joined. Delivers the complete join decision with no presence display required.

**Acceptance Scenarios**:

1. **Given** the join page is open, **When** a participant enters a display name and submits, **Then** they are marked as joined under that name.
2. **Given** the join page is open, **When** a participant chooses to join without entering a name, **Then** they are marked as joined anonymously.
3. **Given** the join page is open, **When** a participant submits an empty name, only whitespace, a name longer than 30 characters, or a name with disallowed characters, **Then** the submission is rejected with a clear message and the participant is not counted as joined.

---

### User Story 3 - See Who Has Joined (Priority: P2)

The presenter sees how many participants are connected, and each participant sees confirmation that they have joined.

**Why this priority**: The presenter needs live presence to pace the demo ("we have 8 people in"), and participants need confirmation they are in. Less critical than joining itself, but required for PRD §5.1 ("presentation screen shows the number of connected participants").

**Independent Test**: Can be fully tested by joining from two devices, then checking that the presentation screen count increases and each device shows a joined confirmation. Delivers visible presence without any poll or mission behavior.

**Acceptance Scenarios**:

1. **Given** no participants have joined, **When** the presenter views the presentation screen, **Then** the participant count shows zero.
2. **Given** one participant has joined, **When** a second participant joins, **Then** the displayed count increases by one within a few seconds without a manual refresh.
3. **Given** a participant has successfully joined, **When** they look at their own device, **Then** they see confirmation that they are joined.
4. **Given** two participants are connected, **When** one leaves or times out, **Then** the displayed count decreases by one within a few seconds without a manual refresh.

---

### User Story 4 - Verify Local Network Reachability (Priority: P3)

The presenter can confirm the application is reachable from audience devices on the local network and gets guidance when it is not (hotspot isolation, firewall, wrong bind address).

**Why this priority**: Local-network failures are the most common live-demo failure. Setup notes do not add audience value directly, but they determine whether Stories 1–3 work at all in a hotspot environment.

**Independent Test**: Can be fully tested by starting the application, following the setup guidance to check reachability from a second device, and confirming a clear reachable / not-reachable indication. Delivers setup confidence with no audience present.

**Acceptance Scenarios**:

1. **Given** the application is started, **When** the presenter checks the displayed join address, **Then** the address uses a local-network location reachable from audience devices, not a loopback-only location.
2. **Given** an audience device cannot reach the application, **When** the presenter follows the displayed setup notes, **Then** the notes cover hotspot device-to-device permission, firewall, and port binding checks.

---

### Edge Cases

- What happens when two participants choose the same display name? Both joins succeed; the system distinguishes them internally and never merges their presence.
- How does the system handle unsafe display-name content (markup, scripts, emoji, or names longer than 30 characters)? Input is trimmed and validated server-side against the 30-character, allowed-character rule, rejected when invalid, and rendered as plain text so it cannot alter the page or mislead others.
- What happens when a participant loses network and rejoins? Rejoining restores their joined state without double-counting them as two participants.
- What happens when the QR code is photographed and opened later after the network address changed? The old code leads to an unreachable address; the current on-screen code always reflects the current address.
- What happens when hotspot client isolation blocks device-to-device traffic? The join page is unreachable; setup notes direct the presenter to disable isolation or switch networks rather than showing a generic failure.
- What happens under a burst of near-simultaneous joins (whole room scanning at once)? All valid joins are recorded; the count converges to the correct total.
- What happens when a participant submits join input with missing fields or malformed data? The submission is rejected with a clear message and nothing is recorded.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST display a scannable join code on the presentation screen that encodes the actual join URL participants must open.
- **FR-002**: System MUST keep the displayed join code consistent with the current reachable join address; a stale or placeholder address MUST NOT be shown.
- **FR-003**: System MUST provide a join page reachable over the local network with no installation or account required.
- **FR-004**: Participants MUST be able to join by providing a display name.
- **FR-005**: Participants MUST be able to join anonymously without providing a name.
- **FR-006**: System MUST validate every join input on the server side: trim surrounding whitespace, reject empty or whitespace-only names, limit names to 30 characters, and allow only letters, numbers, spaces, and `- _ ' . ,`.
- **FR-007**: System MUST reject invalid join submissions with a clear, non-technical message and MUST NOT count rejected submissions toward presence.
- **FR-008**: System MUST display the current number of connected participants on the presentation screen, decrementing when a participant leaves or times out.
- **FR-009**: System MUST update the displayed participant count within a few seconds of a join, leave, or timeout without requiring a manual refresh.
- **FR-010**: System MUST show each participant a confirmation that they have successfully joined.
- **FR-011**: System MUST distinguish participants who chose the same display name so presence counts and identities are never merged.
- **FR-012**: System MUST treat participant-supplied names as untrusted data and render them as plain text so they cannot alter page structure or execute behavior.
- **FR-013**: System MUST avoid collecting or storing unnecessary personal information; joining MUST NOT require email, phone number, or any credential.
- **FR-014**: System MUST serve the audience-facing pages on a local-network address reachable from participant devices and MUST NOT serve them on a loopback-only address as the advertised join target.
- **FR-015**: System MUST provide setup guidance covering hotspot device-to-device permission, firewall, and port binding checks.
- **FR-016**: System MUST NOT expose management interfaces or debugging access to audience participants through the join or presence views.

### Key Entities

- **Participant**: A person who joined from a device; attributes include chosen display name or anonymous marker, join time, and a stable identity that survives display-name collisions.
- **Presence Roster**: The current set of connected participants and the derived live count shown on the presentation screen; it shrinks on leave or timeout.
- **Join Reference**: The advertised join URL and its encoded scannable form shown on the presentation screen; always reflects the currently reachable address.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A first-time participant can go from scanning the on-screen code to reaching the join page in under 30 seconds on the local network.
- **SC-002**: A participant can complete joining (named or anonymous) in under 1 minute without creating an account or installing anything.
- **SC-003**: When 10 participants join within 1 minute, the presenter-visible count matches the true number of currently connected participants.
- **SC-004**: 90% of first-time participants successfully join on their first attempt without presenter help during rehearsal with at least 3 devices.
- **SC-005**: Invalid join submissions (empty, whitespace-only, longer than 30 characters, or with disallowed characters) are rejected with a clear message 100% of the time and never inflate the participant count.

## Assumptions

- Participants have a phone or computer with a camera (or a browser capable of opening a typed local-network URL) and are connected to the same hotspot or Wi-Fi network as the presenter.
- The hotspot or Wi-Fi network can be configured to permit device-to-device communication; where isolation is enforced by default, the presenter can change the setting or switch networks.
- No participant accounts are desired; anonymity is acceptable and display names are for live facilitation only, not for long-term identity.
- Duplicate display names are allowed and do not need to be forced unique; internal distinction is sufficient.
- Participant presence is session-scoped for the live demonstration; long-term storage of participants is out of scope.
- Join traffic is a small room (tens of devices), not public-internet scale.
