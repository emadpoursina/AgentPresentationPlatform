# Feature Specification: Agent Profiles + Serial Hermes Workflow (F5)

**Feature Branch**: `serial-agent-handoffs`

**Created**: 2026-10-15

**Status**: Draft

**Input**: User description: "Resume from .agent/handoff/f5-agent-wiring-20261015-1848.md. Run F5 (agent profiles + serial Hermes workflow) per scratch/prd.md §6 and docs/implementation-plan.md L62-67, acceptance §13 #3/#4/#5/#12: FIRST run the PRD §8 model pre-flight against the installed Hermes (free-tier API model: access, quota, tool-calling, latency) and report results before coding; then build Researcher→Critic→Summarizer serial handoffs consuming F3 branch_context as a real task input, emitting the canonical agent/tool events F4 already renders, with timeouts and visible error recovery — terminal-runnable end-to-end first. Do NOT redo F1-F4 (T001-T058) unless regression fails; gates: `uv run pytest -q` (57 baseline) + `uv run ruff check .` must stay green."

## Clarifications

### Session 2026-10-15

- Q: When a step fails mid-mission (timeout, tool failure, or model error), what should happen to the remaining Researcher→Critic→Summarizer chain? → A: Abort immediately into a failed terminal state (option B); completed agents' outputs are preserved. Any fresh full re-run is a new mission (see Assumptions for the retry reconciliation).
- Q: When the operator chooses "retry" after a failure, what exactly should the retry do? → A: Option A — resume from the failed step, reusing the completed agents' outputs as inputs (FR-021).
- Q: Which Hermes tools may each agent profile use in F5? → A: Option B — least privilege: only the Researcher gets the pre-flight-verified `terminal` tool; Critic and Summarizer run tool-free on handed-off text (FR-022).
- Q: How should F5's tests exercise agent execution without burning model quota or slowing every gate run? → A: Option A — stub Hermes in unit/integration tests, plus one real end-to-end test behind an opt-in pytest marker/env flag (FR-023).
- Q: With the monthly model window ~66% consumed, should low quota do anything beyond FR-018's visible warning at mission start? → A: Option B — require an explicit operator confirmation/flag when remaining quota is below a configured threshold (default 35%) (FR-024, SC-011).

Settled earlier (not re-opened): the PRD §8 model pre-flight is **already complete and PASSED** (evidence: `.agent/pi/f5-preflight/2026-10-15T21-48-43-554Z_4af17e/report.json` — real Hermes 0.21.7 call + real tool-call round trip, 15s/12s wall, live rate windows), so F5 proceeds with the operator-confirmed model `muse-spark-1.3-contributor` on provider `opencode-go` and does **not** re-run the pre-flight. The free-tier deviation is documented as a known caveat (Assumptions + FR-010/FR-011).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run the Full Serial Mission End-to-End from the Terminal (Priority: P1)

The presenter (or operator) starts a mission from the command line. The system runs the three predefined agent roles in order — Researcher, then Critic, then Summarizer — passing each agent's output programmatically to the next (no manual copy-paste). Each agent executes through the real Hermes harness against the real configured model. When the mission finishes, a real final result exists and every step was actually executed.

**Why this priority**: This is F5's core deliverable and the backbone of acceptance #3/#4/#5 (real findings, real handoff, real final result). PRD §6 requires serial handoffs that pass outputs, and the implementation plan mandates terminal-runnable end-to-end before anything fancier. Without this, the dashboard has nothing real to show and later features (browser demo, presenter controls) have nothing to control.

**Independent Test**: Can be fully tested by starting a mission with a topic from the terminal and verifying, from the persisted event log and mission record alone, that three distinct agent executions occurred in Researcher→Critic→Summarizer order, that the Critic's task input contained the Researcher's findings and the Summarizer's input contained both prior outputs, and that the mission ended in a real terminal status with a final result derived from actual agent output.

**Acceptance Scenarios**:

1. **Given** no mission is running, **When** the operator starts a mission with a topic from the terminal, **Then** the Researcher agent begins executing via Hermes and its start is recorded as a real event within a few seconds.
2. **Given** the Researcher has finished, **When** the workflow advances, **Then** the Critic receives the Researcher's findings as its task input (programmatic handoff, not manual copy-paste) and performs its separate critique task.
3. **Given** the Critic has finished, **When** the workflow advances, **Then** the Summarizer receives both prior outputs and produces a final result containing a main conclusion, key findings, and caveats.
4. **Given** the mission has run all three agents, **When** the Summarizer completes, **Then** the mission reaches a completed status and the final result is derived from real agent output — never synthesized by the coordinator.
5. **Given** the audience had previously applied a decision (F3), **When** the Researcher's task is composed, **Then** the applied branch instruction from `branch_context` is included as a real input that changes what the Researcher is asked to do.

---

### User Story 2 - Watch Real Agent and Tool Activity as It Happens (Priority: P2)

While the serial mission runs, every agent start, tool call, handoff, completion, and failure is emitted as a canonical activity event that the existing F4 dashboard already renders. No F4 protocol change is needed; the dashboard simply stops showing empty agent/tool sections and starts showing real execution.

**Why this priority**: PRD §5.5/§6 and acceptance #8 require the audience/presenter to see real tool calls and handoffs. It is only valuable once P1 exists, and it requires zero dashboard changes — F5 only emits events F4 already understands.

**Independent Test**: Can be fully tested by running a mission while subscribed to the event stream and confirming the exact sequence of agent/tool/handoff/completed/failed events matches actual execution, with no fabricated or duplicate progress.

**Acceptance Scenarios**:

1. **Given** a serial mission is running, **When** each agent starts and finishes, **Then** the corresponding `agent_started`, `agent_completed` (or `agent_failed`) events appear in the event stream with the correct agent profile and step.
2. **Given** an agent invokes a tool through Hermes, **When** the tool begins and ends, **Then** `tool_started` and `tool_completed` events appear reflecting the real tool invocation and its real outcome (success or failure).
3. **Given** one agent hands off to the next, **When** the handoff occurs, **Then** an `agent_handoff` event records who handed off to whom and why.
4. **Given** the F4 dashboard is open, **When** these events arrive, **Then** the existing dashboard renders them with no dashboard code or event-protocol changes.

---

### User Story 3 - Recover Visibly When an Agent, Tool, or Model Fails (Priority: P3)

If an agent step times out, a tool call fails, or the model becomes unavailable, the mission does not hang or silently pretend success. The failure is recorded as a real event, the mission aborts immediately into a failed terminal state (completed agents' outputs preserved), the presenter is informed, and a deliberate retry-or-cancel path exists.

**Why this priority**: PRD §6 (errors and timeouts recorded and visible), §8 failure behavior, and acceptance #9/#12 require visible failure and recovery. A live demo without this is a liability, but it only matters once the happy path (P1/P2) exists.

**Independent Test**: Can be fully tested by forcing a step to exceed its timeout (or by making the model endpoint fail) and verifying the mission records the error, emits a failure event, aborts into a failed terminal state instead of hanging, and can be retried (resuming at the failed step) or cancelled by the operator.

**Acceptance Scenarios**:

1. **Given** an agent step exceeds its configured timeout, **When** the timeout fires, **Then** the step is stopped safely, an `agent_failed` event with the timeout reason is recorded, and the mission does not remain stuck in a running state.
2. **Given** a tool call fails during an agent's execution, **When** the failure reaches the workflow, **Then** the failure is recorded as a real unsuccessful event and the mission outcome is not reported as a clean success (acceptance #9).
3. **Given** the model is unavailable mid-mission, **When** the next step attempts to execute, **Then** the error is recorded, the mission aborts into a failed terminal state (remaining steps do not run, prior outputs preserved), and the operator can retry or cancel — with no silent model switching.
4. **Given** a failed mission with one or more completed agents, **When** the operator retries, **Then** the retry is a deliberate, recorded action that resumes from the failed step, reusing the preserved completed agents' outputs as inputs — completed agents are not re-executed, and it is never an automatic loop.

---

### Edge Cases

- **Empty or missing branch_context**: If no audience decision was applied before the Researcher runs, the workflow proceeds with the mission's default objective and records that no branch instruction was applied (it must not invent one).
- **Mid-mission quota exhaustion**: If the provider rate-limits or quota-blocks a call, the affected step fails visibly per the model-failure scenario above; the mission must not retry indefinitely.
- **Agent output too large or malformed**: Handoff payloads are bounded; if an agent returns unusable output (empty/oversized), the consuming step fails with a recorded reason rather than passing garbage downstream.
- **Concurrent mission attempts**: Only one mission executes at a time (PRD §6: one active mission); a second start attempt is rejected with a clear message while one is running.
- **Hermes unreachable or misconfigured**: Mission start fails fast with a recorded, visible error — never a silently no-op run.
- **Reset during execution**: The existing mission reset path must safely stop or abandon an in-flight run without leaving orphan executions.
- **Model differs from config file default**: Execution must use the model Hermes actually resolves at runtime, not any static default in a config file (see Assumptions).

## Requirements *(mandatory)*

### Functional Requirements

**Model pre-flight (completed; gate for coding)**

- **FR-001**: The PRD §8 primary-model pre-flight (API access, quota, tool-calling compatibility, latency under realistic conditions, rate limits, Hermes support for the model) MUST be completed and reported **before** any workflow code is written.
- **FR-002**: The completed pre-flight MUST leave durable evidence (a report artifact) that future sessions can reference, and its result MUST be reflected in this spec's status/assumptions.
- **FR-010**: Because the operator has confirmed the pre-flight PASSED using `muse-spark-1.3-contributor` on provider `opencode-go`, implementation proceeds on that verified model without re-running the pre-flight; the deviation from PRD §8's "free-tier API first" (opencode-go is a subscription/paid tier per provider notes) MUST be documented as a known caveat wherever the model strategy is recorded.
- **FR-011**: If the configured/resolved model EVER changes, the full PRD §8 pre-flight MUST be re-run and re-reported before that model is used in a mission.

**Serial agent workflow**

- **FR-003**: The system MUST execute a predefined, bounded, serial workflow of exactly three roles in order — Researcher → Critic → Summarizer — with one role active at a time, each executed by the real Hermes harness (no second agent framework, no simulated agent output).
- **FR-004**: Each handoff MUST pass the producing agent's output to the consuming agent programmatically as part of its task input — never via manual copy-paste.
- **FR-005**: The Researcher's task input MUST include the mission objective and, when present, the audience-applied branch instruction from F3's `branch_context` as a real input that demonstrably changes the task (acceptance #6/#12 wiring; F3 must not be re-implemented, only consumed).
- **FR-006**: Each role MUST have defined input/output expectations per PRD §6: Researcher returns findings + sources + uncertainties + handoff note; Critic returns issues + evidence + remaining uncertainty + review; Summarizer returns main conclusion + key findings + caveats + a short explanation of what the agents actually did.
- **FR-007**: Agents MUST NOT be able to redefine the workflow, grant themselves additional tools, or take actions outside the mission's predefined, allowed boundaries (no self-granted tools).
- **FR-008**: Mission completion status MUST depend on actual execution results only; progress must never be fabricated.
- **FR-022**: Tool access MUST follow least privilege per profile: only the Researcher profile is granted the pre-flight-verified `terminal` tool; the Critic and Summarizer profiles run tool-free on the text handed to them. No profile can invoke tools outside its grant (FR-007).

**Events and visibility (F4 contract)**

- **FR-012**: The workflow MUST emit only the canonical event types F4 already renders — `agent_started`, `tool_started`, `tool_completed`, `agent_handoff`, `agent_completed`, `agent_failed` — with F5 never changing the F4 event protocol, dashboard contract, or frontend rendering code.
- **FR-013**: Every emitted agent/tool event MUST correspond 1:1 to a real execution occurrence (a real Hermes run, a real tool invocation and its real outcome); no synthetic "heartbeat" or decorative events.

**Timeouts, errors, and recovery**

- **FR-014**: Every agent step MUST have a configured timeout; on expiry the step is stopped safely, the failure is recorded with its reason, and the mission does not remain stuck running.
- **FR-015**: Tool failures and agent failures MUST be recorded as real unsuccessful events; a mission with a failed step MUST NOT be reported as a clean success (acceptance #9).
- **FR-016**: On model unavailability or persistent failure, the system MUST record the error and abort into a failed terminal state (FR-020), and expose a deliberate retry-or-cancel path to the operator — never automatic unbounded retries and never a silent model switch that misrepresents what ran (PRD §8 failure behavior).
- **FR-017**: F5 MUST be runnable end-to-end from the terminal as the primary acceptance path, before any later UI controls (F7) exist.
- **FR-020**: On any mid-mission step failure (timeout, tool failure, or model error), the workflow MUST abort immediately into a failed terminal state: the remaining chain does not run, no agent step is auto-skipped or auto-continued, and the completed agents' outputs and the failure reason are preserved with the mission record.
- **FR-021**: An operator-initiated retry of a failed mission MUST resume from the failed step, reusing the preserved outputs of completed agents as inputs to that step — completed agents MUST NOT be re-executed. The retry MUST be a deliberate, recorded action; a fresh full re-run, when desired, is started as a new mission.

**Model usage controls (PRD §8)**

- **FR-009**: The system MUST enforce PRD §8 usage controls for agent execution: configurable per-run request/token limits, a cap on simultaneous agent tasks (initially one mission, one active agent), a presenter/operator-controlled shutdown that halts execution promptly, and a visible warning when quota or resource usage approaches configured limits.
- **FR-018**: Quota risk MUST be surfaced honestly: at pre-flight time the monthly window was ~66% consumed (34% remaining), and this constraint must be visible to the operator before starting a mission.
- **FR-024**: When the remaining model quota is below a configured threshold (default: 35% remaining), starting a mission MUST require an explicit operator confirmation/flag in addition to FR-018's visible warning; mission start is blocked until that confirmation is provided.

**Regression safety**

- **FR-019**: F1–F4 behavior (T001–T058) MUST NOT regress: the existing test suite stays green at its 57-test baseline (new F5 tests may only add to it) and the lint gate stays clean. F1–F4 are not re-scoped or re-implemented.
- **FR-023**: F5's tests MUST exercise agent execution without consuming model quota in default gate runs: unit and integration tests stub the Hermes executor, and exactly one real end-to-end mission test is opt-in via a pytest marker and environment flag, excluded from the default `uv run pytest -q` gate run.

### Key Entities

- **Agent Profile**: A named role (Researcher, Critic, Summarizer) with instructions, allowed tools/constraints, defined input expectations, and defined output expectations. Executed by Hermes.
- **Serial Handoff**: The recorded passing of one agent's output into the next agent's task input, including who→whom and reason.
- **Branch Context (consumed, F3-owned)**: The audience-applied decision state (`applied_decisions` + `current_branch_instruction`) that F5 reads as a real task input; F5 must not modify how it is produced.
- **Agent/Tool Event**: Canonical activity records (`agent_started`, `tool_started`, `tool_completed`, `agent_handoff`, `agent_completed`, `agent_failed`) describing real execution only.
- **Run Limits**: Configured usage controls (request/token caps, task cap, shutdown switch, warning threshold) applied to model execution.
- **Model Resolution**: The model/provider Hermes actually resolves at runtime, which may differ from static config defaults; the workflow must read the resolved value and record it with mission results.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of completed missions show three distinct, ordered agent executions (Researcher, Critic, Summarizer) in the persisted event log, each with real inputs and outputs (acceptance #3/#4/#5).
- **SC-002**: In 100% of runs, the Critic's recorded task input contains the Researcher's actual findings output, and the Summarizer's input contains both prior outputs — verified from logs, with zero manual copy-paste steps.
- **SC-003**: When an audience decision was applied before a run, 100% of Researcher task inputs visibly include the applied branch instruction, and mission records show the instruction actually used (acceptance #6 wiring).
- **SC-004**: Every agent/tool event in the log maps 1:1 to a real execution occurrence; a reviewer comparing the event log to the Hermes execution record finds 0 fabricated or missing agent/tool events (acceptance #8).
- **SC-005**: An end-to-end mission (topic in → final result out) completes via the terminal path with no manual intervention between agent steps, and the run is reproducible on a second invocation with a fresh mission.
- **SC-006**: When a failure is induced (timeout or model error), 100% of affected missions record the failure with a reason, abort into a failed terminal state within the configured timeout + a small grace period (never hang, with completed agents' outputs preserved), and offer a working retry-or-cancel path (acceptance #12).
- **SC-007**: 0 runs report a clean success mission outcome when any step or tool call actually failed (acceptance #9).
- **SC-008**: Existing quality gates remain fully green: the pre-F5 test suite's 57 tests all pass, plus new F5 tests; the lint gate reports 0 issues.
- **SC-009**: The active model is recorded per mission from the runtime-resolved value, and the documented pre-flight evidence exists and matches the model actually executed — any model change triggers a new pre-flight before use.
- **SC-010**: When the operator retries a failed mission, 100% of retries resume at the failed step with the preserved outputs of completed agents present in that step's task input, and 0 completed agents are re-executed on retry.
- **SC-011**: When remaining model quota is below the configured threshold (default 35%), 100% of mission start attempts are blocked until an explicit operator confirmation/flag is provided.

## Assumptions

- **Pre-flight already done**: The PRD §8 pre-flight PASSED before this spec (evidence: `.agent/pi/f5-preflight/2026-10-15T21-48-43-554Z_4af17e/report.json`: real Hermes 0.21.7 call + real tool-call round trip succeeded, ~15s/~12s wall including CLI bootstrap, live rate windows reported). F5 does not re-run it.
- **Model strategy (operator-confirmed, binding)**: Proceed with `muse-spark-1.3-contributor` on provider `opencode-go` (Hermes' resolved model). This deviates from PRD §8's "free-tier API first" — opencode-go is a subscription/paid tier per provider notes — accepted as a known caveat with the PRD §8 usage controls enforced (FR-009) and quota risk surfaced (FR-018: monthly window was ~66% consumed at pre-flight time).
- **Resolved model, not static default**: The runtime model profile overrides the static config default (`anthropic/claude-opus-4.6`); all workflow code reads the RESOLVED model and records it. A profile change silently alters what runs, so re-verification is mandatory on any model change (FR-011).
- **Hermes is the sole executor**: No second agent framework, no custom agent loop; the mission controller remains a thin coordinator that composes tasks, passes outputs, enforces timeouts/limits, and publishes events (per project rules and PRD §4C).
- **F3/F4 are frozen contracts**: `branch_context` (produced by `MissionController.apply_decision`) is consumed as-is; the canonical event set and dashboard rendering are consumed as-is. No F1–F4 rework; the 57-test baseline + lint gates must stay green.
- **Terminal-first**: Terminal-runnable end-to-end is the acceptance path for F5; presenter-controls UI (F7), browser demo (F6), Telegram (F8), and playground (F9) are explicitly out of scope.
- **One mission at a time**: Serial execution with a single active mission (PRD §6); parallelism is out of scope.
- **Timeouts/limits defaults**: Reasonable defaults (per-step timeout, per-run token/request caps, warning threshold, low-quota confirmation threshold defaulting to 35% remaining) will be chosen and documented during planning/implementation; they are configurable, and exact numbers are not spec-level concerns.
- **Failure/retry reconciliation (operator-confirmed, binding)**: The operator selected both "abort immediately into a failed terminal state" and "retry resumes from the failed step reusing completed outputs". These are reconciled unambiguously as: (1) a mid-mission step failure aborts at once into a FAILED TERMINAL state — the remaining chain never runs, nothing auto-retries, and all completed agents' outputs plus the failure reason are preserved with the mission record (FR-020); (2) a fresh full re-run is always available but is a NEW mission; (3) when the operator explicitly chooses "retry" on a failed mission, execution RESUMES at the failed step with the preserved completed-agent outputs as that step's inputs — completed agents are not re-run and their model quota is not re-burned (FR-021). Testable consequences: on failure, mission status == failed and prior outputs are queryable; on retry, the resumed step's task input contains the stored prior outputs and no `agent_started` event is emitted for already-completed steps.
- **Tool scope for F5 (operator-confirmed, least privilege)**: Only the Researcher profile is granted the pre-flight-verified `terminal` tool; the Critic and Summarizer profiles run tool-free on handed-off text (FR-022). Browser-capable tooling belongs to F6, not F5.
