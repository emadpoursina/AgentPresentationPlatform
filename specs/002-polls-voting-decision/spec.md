# Feature Specification: Polls, Voting, Decision-Applied Branch

**Feature Branch**: `chore/bootstrap-scaffold`

**Created**: 2026-10-15

**Status**: Draft

**Input**: User description: "F3 polls/voting/decision-applied branch per scratch/prd.md 5.2-5.4 (acceptance #6); do NOT redo F1/F2 or re-run T001-T018 unless regression fails. path: feature"

## Clarifications

### Session 2026-10-15

- No open clarifications. All ambiguities resolved via documented assumptions below (live-count default with controlled-reveal option, 60-second default deadline, presenter tie-break/no-vote selection from the poll's predefined options or a safe mission default).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Vote in an Open Poll (Priority: P1)

A joined audience participant sees the current poll question with its predefined options on their device, casts one vote, and may change that vote any time before the poll closes. A participant who has not joined (F2 roster) cannot vote.

**Why this priority**: This is the core audience interaction. PRD acceptance §13 #6 ("a poll changes the next workflow action") fails without castable, countable votes, and every later story (close, tie-break, branch) assumes votes exist.

**Independent Test**: Can be fully tested by opening a poll with 2–4 predefined options, voting from two joined devices (including changing one vote before close), and confirming each participant's latest vote is the one counted and no duplicate votes are tallied.

**Acceptance Scenarios**:

1. **Given** a poll is open and the voter is on the joined roster, **When** the voter selects an option and submits, **Then** their vote is recorded exactly once for that poll.
2. **Given** a voter has already voted in an open poll, **When** they submit a different option before the deadline/close, **Then** their earlier vote is replaced (still exactly one counted vote for that voter).
3. **Given** a poll is open, **When** a device that never joined attempts to submit a vote, **Then** the submission is rejected with a clear message and nothing is recorded.
4. **Given** a poll is open, **When** a voter submits an option not on the predefined list, a blank submission, or malformed data, **Then** the submission is rejected with a clear message and the voter's prior vote (if any) is unchanged.
5. **Given** a poll has closed (deadline or early close), **When** a voter attempts to vote or change a vote, **Then** the submission is rejected and the recorded votes are unchanged.

---

### User Story 2 - Presenter Runs the Poll Lifecycle (Priority: P1)

The presenter opens a poll (question + predefined options + deadline), watches its state move through open → closing → completed, can close it early, and resolves ties or no-vote outcomes by choosing the next step. The audience always sees the current state.

**Why this priority**: Without a trustworthy lifecycle (deadline enforcement, early close, deterministic outcome even with ties or silence), the vote cannot produce a defensible decision for the workflow branch.

**Independent Test**: Can be fully tested by opening a poll with a short deadline, observing the open state, closing it early from the presenter view, and confirming the poll reaches completed with exactly one recorded outcome and a visible state on audience devices — with no mission/agent workflow required.

**Acceptance Scenarios**:

1. **Given** one mission is active and no other poll is open, **When** the presenter opens a poll with a question, 2+ predefined options, and a deadline, **Then** the poll becomes open and visible to joined participants with its question, options, state, and deadline/remaining indication.
2. **Given** a poll is open with a deadline, **When** the deadline passes, **Then** the poll stops accepting votes and moves to completed with one recorded outcome.
3. **Given** a poll is open, **When** the presenter closes it early, **Then** the poll stops accepting votes immediately and moves to completed with one recorded outcome.
4. **Given** a completed poll where two or more options tie for most votes, **When** the outcome is determined, **Then** the presenter's choice among the tied options is recorded as the winning choice (deterministic, no coin-flip or hidden rule).
5. **Given** a completed poll with zero valid votes, **When** the outcome is determined, **Then** the presenter's selected next step is recorded as the outcome instead of a fabricated winner.
6. **Given** a poll's state changes (opened, near deadline/closing, completed), **When** a joined participant or the presenter looks at their screen, **Then** they see the current state (open, closing, or completed) without a manual refresh within a few seconds.

---

### User Story 3 - Winning Choice Drives a Real Workflow Branch (Priority: P1)

When a poll completes, the winning choice is recorded in the activity history as an audience decision and changes what the mission actually does next (task instructions or permitted branch), not just what the screen shows. The dashboard shows only real events.

**Why this priority**: This is the PRD §5.3 thesis ("audience choices must affect actual task instructions or permitted workflow branches") and acceptance #6. A poll that only changes visuals is a demo failure.

**Independent Test**: Can be fully tested by completing a poll, confirming the winning choice appears in the activity history as the applied audience decision, and confirming the mission's next step reflects that choice (different task instructions or branch taken for different winners) — verified by running the same mission with two different winners and observing different next steps.

**Acceptance Scenarios**:

1. **Given** a poll has completed with a winning choice, **When** the decision is applied, **Then** the winning choice is recorded in the activity history as the applied audience decision with its poll reference.
2. **Given** an applied audience decision, **When** the mission advances, **Then** the next workflow step follows the branch or task instructions corresponding to the winning choice (a different winner produces a different next step where the mission defines distinct branches).
3. **Given** the dashboard is visible, **When** poll events occur (poll opened, vote recorded as aggregate-safe update, poll closed, decision applied), **Then** the dashboard shows only events that actually happened, each with timestamp and mission reference, and never shows fabricated progress or simulated tool activity as real.
4. **Given** the mission controller advances after a decision, **When** the next step starts, **Then** advancement depends on actual mission state and the recorded decision, and the controller remains a thin coordinator (no second agent framework, agent execution stays with the agent harness).

---

### User Story 4 - Follow Poll Results Live with Controlled Reveal (Priority: P2)

Participants and the presenter see live vote counts by default, while the presenter can switch to a controlled reveal (counts hidden until close) for polls where live standings would bias the outcome.

**Why this priority**: PRD §5.4 requires "live vote counts or a controlled reveal". Default-live keeps the room engaged; controlled reveal covers sensitive choices. Less critical than countable votes and branching, but required for the full voting-mechanics contract.

**Independent Test**: Can be fully tested by opening one poll in live-count mode and one in controlled-reveal mode, voting from two devices, and confirming counts are visible live in the first and hidden until close in the second, with identical counting rules in both.

**Acceptance Scenarios**:

1. **Given** a poll is open in live-count mode, **When** votes are recorded, **Then** joined participants and the presenter see updated counts within a few seconds without manual refresh.
2. **Given** a poll is open in controlled-reveal mode, **When** votes are recorded before close, **Then** per-option counts stay hidden while the poll still shows it is open (and that votes are being accepted); full counts and the outcome appear only after completion.
3. **Given** either reveal mode, **When** the poll completes, **Then** the final counts and the selected outcome are shown together.

---

### Edge Cases

- What happens when a voter submits twice in rapid succession (double-tap)? Only the latest valid choice counts; the per-poll tally never contains two votes from the same voter.
- What happens when the deadline passes while a vote submission is in flight? The server decides by arrival time: submissions arriving after close are rejected and do not alter the tally.
- What happens when the presenter tries to open a second poll while one is already open? The second open is rejected; the serial workflow permits at most one open poll per active mission.
- What happens when a poll has exactly one option or more options than the mission allows? Opening is rejected with a clear message; a poll requires at least two and at most a small bounded set of predefined options (assumption: 2–6).
- What happens when all votes go to one option? That option wins outright; no tie-break or presenter override is needed.
- What happens when a tied voter changes their vote at the last moment to break the tie? The final tally at close decides; if a tie remains, the presenter tie-break rule applies.
- What happens when the presenter disconnects mid-poll? The poll continues under its deadline; votes keep counting under server authority and the outcome is determined at close.
- What happens when vote text contains markup or scripts (if options ever echo participant content)? All rendered poll/vote content is treated as untrusted plain text and cannot alter page structure or execute behavior.
- What happens when the network drops briefly during voting? Reconnection restores the current poll state; already-recorded votes are preserved and never double-counted on retry.
- What happens when no mission is active? A poll cannot be opened; opening outside an active mission is rejected with a clear message.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST offer each poll as a question with a bounded predefined option list (2–6 options); write-in options MUST NOT be accepted.
- **FR-002**: System MUST support a configurable voting deadline per poll with a 60-second default when the presenter does not set one.
- **FR-003**: System MUST enforce poll states open, closing, and completed, and MUST show the current state to joined participants and the presenter.
- **FR-004**: System MUST accept votes only while the poll is open; votes before open or after close MUST be rejected with a clear message and MUST NOT alter the tally.
- **FR-005**: System MUST restrict voting to participants already on the joined roster; non-joined submissions MUST be rejected server-side.
- **FR-006**: System MUST count at most one vote per participant per poll; submitting again before close MUST replace the voter's previous vote.
- **FR-007**: System MUST validate every vote submission server-side (poll is open, voter is joined, option is on the predefined list, payload is well-formed) and MUST reject invalid submissions without changing the tally.
- **FR-008**: System MUST let the presenter close an open poll early; close MUST take effect immediately and stop further vote acceptance.
- **FR-009**: System MUST allow at most one open poll per active mission; opening a second poll while one is open MUST be rejected.
- **FR-010**: System MUST refuse to open a poll when no mission is active.
- **FR-011**: System MUST resolve a tie at close by presenter choice among the tied options; the system MUST NOT invent a winner by coin-flip, earliest-vote, or any hidden rule.
- **FR-012**: System MUST handle zero valid votes at close via presenter selection of the next step; the system MUST NOT fabricate votes or a winner.
- **FR-013**: System MUST record the final outcome (winning choice or presenter-selected fallback, with poll reference) in the activity history as the applied audience decision.
- **FR-014**: System MUST drive a real workflow branch from the applied decision: the mission's next step MUST follow the task instructions or permitted branch corresponding to the winning choice, not merely change visuals.
- **FR-015**: System MUST publish poll lifecycle events (`poll_opened`, `vote_recorded` as aggregate-safe updates, `poll_closed`, `audience_decision_applied`), each carrying a timestamp, mission identifier, and safe metadata; individual ballot secrecy is out of scope but per-voter choices MUST NOT be exposed beyond counts.
- **FR-016**: System MUST show only real events on the dashboard; fabricated progress or simulated tool activity presented as real execution is forbidden.
- **FR-017**: System MUST support two result-visibility modes per poll: live counts (default) and controlled reveal (per-option counts hidden until close); the mode MUST be fixed at poll open and shown to voters.
- **FR-018**: System MUST deliver poll state and count updates to joined devices and the presenter view within a few seconds without manual refresh, and MUST show a clear disconnected/stale state instead of presenting stale standings as current.
- **FR-019**: System MUST treat all participant-supplied and agent-supplied poll content as untrusted data and render it as plain text (sanitized) so it cannot alter page structure or execute behavior.
- **FR-020**: System MUST keep presenter controls (open, early close, tie-break selection, no-vote selection, reveal mode) under server-side authorization so audience participants cannot invoke them.
- **FR-021**: System MUST prevent duplicate counting on retried or replayed vote submissions (idempotent per voter per poll under server authority).
- **FR-022**: Dependencies (not re-specified here): mission lifecycle and real-time event delivery build on F1 (mission state machine, event stream); voter eligibility builds on the F2 joined roster. This spec adds only the poll/voting/decision-applied behavior above.

### Key Entities

- **Poll**: A single question posed during an active mission; attributes include predefined option list (2–6), deadline, reveal mode (live vs. controlled, fixed at open), state (open / closing / completed), and outcome once completed.
- **Vote**: One participant's current choice in a poll; at most one counted per participant per poll, replaceable before close, validated server-side against roster and option list.
- **Audience Decision**: The recorded outcome of a completed poll (winner or presenter-selected fallback with poll reference) stored in the activity history; the input that selects the mission's next branch.
- **Poll Activity Events**: The real-event record of the poll lifecycle (`poll_opened`, `vote_recorded`, `poll_closed`, `audience_decision_applied`), each with timestamp, mission identifier, and safe metadata, shown on the dashboard without fabrication.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A joined participant can view the open poll and cast a valid vote in under 30 seconds on the local network.
- **SC-002**: 100% of invalid vote submissions (non-joined voter, unknown option, malformed payload, vote after close) are rejected without changing the tally during rehearsal.
- **SC-003**: When 10 joined participants vote (including at least 2 vote changes before close), the final tally credits exactly one vote per voter matching each voter's latest valid choice.
- **SC-004**: A poll opened with a 60-second default deadline stops accepting votes at close, and an early-closed poll stops accepting votes within 5 seconds of the presenter action.
- **SC-005**: In rehearsal, a tied poll and a zero-vote poll each reach a completed state with a presenter-selected outcome recorded in the activity history, with no fabricated winner.
- **SC-006**: Running the same mission with two different winning choices produces two different next workflow steps (branch actually taken), verified end to end.
- **SC-007**: During a full poll cycle, the dashboard displays only events that actually occurred (spot-checked against the activity history with zero fabricated entries), and state/count updates appear within a few seconds without manual refresh.

## Assumptions

- One active mission at a time with serial workflow (prior decision); concurrent missions and parallel polls are out of scope — at most one open poll per mission.
- Poll options are presenter-defined and predefined (2–6 options); free-text write-ins and audience-proposed options are out of scope for this slice.
- Default voting deadline is 60 seconds when the presenter sets none; deadlines are short (tens of seconds to a few minutes) to fit a live demo pace.
- Default result visibility is live counts; controlled reveal is a per-poll presenter choice fixed at open, not changeable mid-poll.
- Tie-break and no-vote fallback are presenter selections from the poll's predefined options (or a safe mission-defined default next step); no automatic or random resolution.
- Voter eligibility reuses the F2 joined roster as-is (no new identity or credential system); ballot secrecy beyond hiding individual choices (counts only) is out of scope.
- Small-room scale (tens of voters on a local network); public-internet scale, persistent vote storage beyond the mission history, and rich analytics are out of scope.
- Mission state machine, event streaming transport, and join/presence UX are owned by F1/F2 and reused here, not redefined.
