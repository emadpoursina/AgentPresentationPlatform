# Feature Specification: Presenter Dashboard Real-Events-Only (F4)

**Feature Branch**: `feat/003-presenter-dashboard`

**Created**: 2026-10-15

**Status**: Draft

**Input**: User description: "F4 presenter dashboard real-events-only per scratch/prd.md 5.5 (acceptance #8); do NOT redo F1-F3 (T001-T044) unless regression fails. path: feature"

## Clarifications

### Session 2026-10-15

- No open clarifications. All ambiguities resolved via documented assumptions below (frontend-only derivation from existing mission/poll/event APIs, no new backend domain; agent/tool sections render empty honest states until F5 emits real agent/tool events; progress stays workflow-position only).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See Mission State and Final Result (Priority: P1)

The presenter sees the current mission title, status, current workflow step, honest overall progress, and — once finished — the final result with its outcome. No simulated progress is ever shown.

**Why this priority**: This is the dashboard's backbone. PRD §5.5 lists mission title/status/step/progress and final result first, and acceptance #8 fails if the screen does not reflect real mission state.

**Independent Test**: Can be fully tested by creating/starting/pausing/completing/failing a mission and confirming the header shows each real transition, progress matches workflow position (never fabricated), and the final-result section shows summary/outcome/error distinctly (failure never renders as success) — with no agents or polls required.

**Acceptance Scenarios**:

1. **Given** no mission exists, **When** the presenter opens the dashboard, **Then** they see an honest empty state ("No mission yet") rather than placeholder mission data.
2. **Given** a mission is created/started/paused/resumed, **When** each transition occurs, **Then** the header shows the real title, status, current step (title + assigned profile), and progress derived only from workflow position within a few seconds without manual refresh.
3. **Given** a mission completes with summary "ok" and outcome "success"/"partial", **When** the presenter looks at the result section, **Then** they see the summary and outcome as the final result.
4. **Given** a mission fails with error "boom", **When** the presenter looks at the result section, **Then** they see the error with outcome "failed", visually distinct from success (acceptance #9 carried forward).
5. **Given** the dashboard is visible at any time, **When** no new events have occurred, **Then** progress and result never advance on their own (no timers, no fabricated activity).

---

### User Story 2 - Watch Agent, Tool, and Handoff Activity (Priority: P1)

The presenter sees agent status (waiting/running/completed/failed + current task), tool executions (name/action/status/safe summary), and agent-to-agent handoffs (from → to + reason). Before F5 emits real agent/tool events, these sections show honest empty states — never mock activity.

**Why this priority**: PRD §5.5 requires agent activity, tool activity, and collaboration sections. Acceptance #8 explicitly demands "real tool calls, handoffs, results, and failures" — a dashboard without these sections cannot pass.

**Independent Test**: Can be fully tested by loading the dashboard with only F1–F3 events present (empty agent/tool/handoff states shown), then injecting canonical `agent_started`/`tool_started`/`tool_completed`/`agent_handoff`/`agent_completed`/`agent_failed` events via the existing event store and confirming each section renders exactly what happened with timestamp + mission reference.

**Acceptance Scenarios**:

1. **Given** no agent events have occurred yet, **When** the presenter views the agent section, **Then** they see an honest empty state ("No agent activity yet — waiting for real execution events") and no agent rows.
2. **Given** real `agent_started` / `agent_completed` / `agent_failed` events arrive over SSE, **When** the presenter watches, **Then** the agent section lists each agent with name/role, status (waiting/running/completed/failed), and current task text within a few seconds.
3. **Given** real `tool_started` / `tool_completed` events arrive, **When** the presenter watches, **Then** the tool section lists tool name, action, execution status, and a safe summary of the result/error.
4. **Given** a real `agent_handoff` event arrives, **When** the presenter watches, **Then** the handoff section shows which agent handed work to which, a concise summary, and the reason from task/workflow metadata.
5. **Given** any agent/tool/handoff payload, **When** it is rendered, **Then** it appears as plain text (never HTML), with timestamp and mission reference, and only for events that actually occurred.

---

### User Story 3 - See Audience Influence and Trust Only Real Events (Priority: P1)

The presenter sees the current poll, vote counts/outcome, which workflow branch was selected because of that outcome, and a clearly disconnected state when the stream drops. Every section is labelled as real-events-only with explanatory UI text visually distinct from execution data.

**Why this priority**: PRD §5.5 requires the audience-influence block and mandates "must distinguish actual execution events from explanatory UI text" + "must not fabricate progress". PRD §10 requires a clear disconnected state instead of stale activity presented as current.

**Independent Test**: Can be fully tested by running a full F3 poll cycle (open → votes → close → decision applied) and confirming the influence section shows poll question/state/counts, outcome, and branch instruction from `branch_context`; then killing the SSE stream and confirming the disconnected banner plus stale marking appear and no section presents stale data as live.

**Acceptance Scenarios**:

1. **Given** a poll is open, **When** the presenter views the influence section, **Then** they see the poll question, state (open/closing/completed), reveal mode, live or hidden counts per mode, and remaining-time indication from the server deadline.
2. **Given** a poll completes with a winner, **When** the presenter views the influence section, **Then** they see vote counts, the selected outcome (`winning_option_id` + `decided_by`), and which workflow branch was selected (the applied `next_step` / `branch_context` instruction).
3. **Given** the SSE stream drops, **When** the presenter looks at the screen, **Then** they see "Disconnected — showing last known state, not live" and sections do not present stale standings/activity as current.
4. **Given** the stream reconnects, **When** missed events replay via `Last-Event-ID`, **Then** all sections converge to the true state without duplicates and the banner returns to "Connected — live".
5. **Given** the full event history, **When** spot-checked against the dashboard, **Then** every displayed activity row corresponds to exactly one real event (zero fabricated entries) and explanatory labels ("Real events only", "Explanatory text, not execution data") are visually distinct.

---

### User Story 4 - Safe Rendering and Rehearsal Robustness (Priority: P2)

All participant- and agent-supplied content renders as plain text, presenter controls stay server-authoritative, and the dashboard survives malformed events without breaking the stream.

**Why this priority**: PRD §10 security (sanitize rendering, untrusted tool outputs) and reliability (visible mission state, manual fallback) apply to every dashboard row. Less critical than the three P1 display stories but required for a demo-safe screen.

**Independent Test**: Can be fully tested by injecting events/polls whose text contains markup/scripts, submitting malformed SSE rows, and confirming the page structure never changes, no script executes, and the stream stays open.

**Acceptance Scenarios**:

1. **Given** poll/agent/tool text contains markup or scripts, **When** rendered, **Then** it appears as inert plain text and cannot alter page structure or execute behavior.
2. **Given** a malformed SSE row arrives, **When** the client parses it, **Then** the row is ignored and the stream stays open.
3. **Given** participant presence changes, **When** joins/leaves occur, **Then** the count updates within seconds without refresh (carried forward from F2, displayed alongside mission state).

---

### Edge Cases

- What happens when the mission list is empty on load? Dashboard shows "No mission yet" and creates nothing on its own (explicit "New mission" button only).
- What happens when the event history exceeds the display cap? Only the newest N rows show (existing 200-cap retained); history API remains the source of truth.
- What happens when agent/tool events reference an unknown mission? Rows still render with their own mission reference; the header only follows the selected mission.
- What happens when `branch_context` has multiple applied decisions? The influence section shows the latest branch plus a compact history of all applied decisions.
- What happens when the network flaps briefly? `EventSource` reconnects with `retry: 3000` and `Last-Event-ID` replay; the banner flaps disconnected → connected with no duplicate rows.
- What happens when the presenter opens the dashboard mid-mission? History loads first (`GET events?limit=100`), then the live tail continues from `lastEventId` — no gap, no overlap.
- What happens when tool output is very long? The dashboard shows a safe truncated summary (client-side truncation), full data stays in the event log.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Dashboard MUST show current mission title, status (`created|running|paused|completed|failed`), current workflow step (title + assigned profile), and honest progress derived only from workflow position (`current_step_index / steps`, 100% only when terminal).
- **FR-002**: Dashboard MUST show a final-result block with summary, outcome (`success|partial|failed`), and error when present; `failed` MUST render distinctly from `success`/`partial` (never as success).
- **FR-003**: Dashboard MUST show an agent-activity section listing, per agent seen in real events, name/role, status (`waiting|running|completed|failed`), and current task or concise description; with zero agent events it MUST show an honest empty state and zero agent rows.
- **FR-004**: Dashboard MUST show a tool-activity section listing, per real tool event, tool name, action, execution status, and a safe truncated summary of result/error.
- **FR-005**: Dashboard MUST show a handoff section listing, per real `agent_handoff`, source → destination, concise summary, and reason from task/workflow metadata.
- **FR-006**: Dashboard MUST show an audience-influence section with current poll (question/state/reveal/counts-or-hidden/deadline), latest outcome (`winning_option_id` + `decided_by`), and the selected workflow branch (`branch_context.current_branch_instruction` / `audience_decision_applied.next_step`); with zero polls it MUST show an honest empty state.
- **FR-007**: Dashboard MUST derive every activity row exclusively from real events fetched via `GET .../events` history + SSE tail; it MUST NOT fabricate progress, simulate tool activity, or advance any section on timers.
- **FR-008**: Dashboard MUST label real-execution sections ("Real events only") and keep explanatory UI text visually distinct from execution data.
- **FR-009**: Dashboard MUST show a connection banner with two states — "Connected — live" vs "Disconnected — showing last known state, not live" — and MUST NOT present stale standings/activity as current while disconnected; reconnect MUST replay via `Last-Event-ID` without duplicates.
- **FR-010**: Dashboard MUST subscribe to all canonical + extended event types (`mission_*`, `poll_*`, `vote_recorded`, `audience_decision_applied`, `agent_*`, `tool_*`, `participant_*`) so F5 agent/tool events render with no further client-protocol change.
- **FR-011**: Dashboard MUST render every server-supplied string (mission titles, step text, poll text, agent/tool content, errors) as plain text (`textContent`-only, never `innerHTML` for untrusted data); a malformed SSE row MUST be ignored with the stream left open.
- **FR-012**: Dashboard MUST reuse existing read APIs only (`GET /api/missions`, `GET /api/missions/{id}`, `GET /api/missions/{id}/events`, `GET /api/missions/{id}/polls/current`, `GET /api/participants`, SSE streams); no new backend endpoints or event types in F4.
- **FR-013**: Dashboard MUST cap the on-screen event log (existing 200-row cap retained, newest first) while keeping the history API as the source of truth; event rows MUST show id, type, timestamp, and mission reference.
- **FR-014**: Dependencies (not re-specified): mission lifecycle + event shape + SSE replay build on F1; presence count builds on F2; poll/outcome/branch data builds on F3 (`branch_context`, `audience_decision_applied`). This spec adds only the structured real-events-only presentation above.

### Key Entities

- **Dashboard Snapshot (client-derived, not stored)**: Mission header + agent map + tool list + handoff list + influence block + final result, all reduced from history + SSE tail; never persisted, rebuilt on load.
- **Agent Row**: `{agent_id/name, role/profile, status, current_task}` from the latest `agent_*` event per agent; status transitions only on real events.
- **Tool Row**: `{tool_name, action, status, safe_summary}` from `tool_started`/`tool_completed` pairs; summaries truncated client-side.
- **Handoff Row**: `{from_agent, to_agent, summary, reason}` from each `agent_handoff`.
- **Influence Block**: Current poll view + latest `audience_decision_applied` + `mission.branch_context` (applied decisions + current branch instruction).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With only F1–F3 events present, the dashboard shows mission header + influence + empty agent/tool/handoff states with zero fabricated rows (spot-check history vs screen: 0 mismatches).
- **SC-002**: After injecting one of each canonical agent/tool event, all three sections list exactly the injected events (each with timestamp + mission id) within 3 seconds without manual refresh.
- **SC-003**: A full mission lifecycle (create → start → pause → resume → complete, plus a separate fail case) reflects in header + result within 3 seconds per transition; failure renders distinctly from success 100% of the time.
- **SC-004**: A full F3 poll cycle reflected in the influence block (question/state/counts/outcome/branch) within 3 seconds per transition; disconnect → banner shows stale warning, reconnect → state converges with no duplicates.
- **SC-005**: Markup/script payloads in any rendered field execute nothing and alter no page structure 100% of the time; one malformed SSE row leaves the stream open.

## Assumptions

- Frontend-only slice: no new backend endpoints, models, or event types; all required fields already exist on `Mission`, poll audience view, and `ActivityEvent`.
- Agent/tool/handoff sections stay honestly empty until F5 emits those events; F4 makes the dashboard *ready* for them (subscriptions + renderers + empty states), it does not execute agents.
- One active mission at a time with serial workflow (prior decision); the dashboard follows the newest mission by default, as today.
- Vanilla HTML/JS + SSE transport reused as-is (`retry: 3000`, `Last-Event-ID` replay, 200-row cap, `textContent`-only rendering); no new dependencies.
- Small-room scale (tens of devices on LAN); 3-second update budget matches F1–F3 "few seconds without refresh" standard.
- Mission state machine, event streaming transport, join/presence, and poll/branch behavior are owned by F1/F2/F3 and reused here, not redefined.
