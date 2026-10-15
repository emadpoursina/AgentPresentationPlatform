# Research: Presenter Dashboard Real-Events-Only (F4)

**Feature**: `specs/003-presenter-dashboard/spec.md` | **Date**: 2026-10-15

No `NEEDS CLARIFICATION` items remain (spec Assumptions fix frontend-only scope, honest empty states, workflow-position progress, and F1/F2/F3 reuse). Research below resolves the design choices the plan depends on.

## 1. Frontend-only derivation, no new backend

- **Decision**: F4 adds no backend endpoints, models, or event types. All PRD 5.5 fields already exist: `GET /api/missions[/{id}]` (title/status/steps/index/result/outcome/error/branch_context/progress), `GET .../polls/current` (question/state/reveal/tally/total/outcome/deadline), `GET .../events` + SSE (every activity row with id/type/timestamp/mission_id/data).
- **Rationale**: Keeps the thin-controller invariant (PRD 4C) and avoids a snapshot endpoint that could drift from the event log; the dashboard is a pure reducer over history + tail, so spot-checks (SC-001) are trivially honest.
- **Alternatives considered**: New `GET .../dashboard` snapshot endpoint — rejected (second source of truth, extra backend + tests for no new data; F5 agent state will still arrive as events anyway).

## 2. Client-side state reduction

- **Decision**: On load: fetch mission → fetch history (`limit=100`) → reduce rows into `{agents: Map, tools: [], handoffs: [], influence}` → render → open SSE from `lastEventId` and apply each new event through the same reducer + re-render. Single `renderDashboard(snapshot, mission)` entry point; per-section renderers (`renderAgents`, `renderTools`, `renderHandoffs`, `renderInfluence`, `renderResult`).
- **Rationale**: One code path for history and live tail eliminates gap/overlap bugs (edge: mid-mission open) and makes reconnect convergence (FR-009) structural: replay is just re-reduction.
- **Alternatives considered**: Separate history vs live render paths — rejected (duplicated logic, divergence risk).

## 3. Agent/tool readiness before F5

- **Decision**: Ship subscriptions + renderers + empty states for `agent_started/agent_completed/agent_failed/tool_started/tool_completed/agent_handoff` now, fed by the same reducer. With zero such events the sections show "No ... yet — waiting for real execution events" and zero rows. F5 only needs to emit the canonical events; no F4 client-protocol change (FR-010).
- **Rationale**: Matches the existing `app.js` forward-subscription pattern (already listens to future types); acceptance #8 sections exist from day one and stay honest.
- **Alternatives considered**: Deferring agent/tool sections to F5 — rejected (then F4 would not satisfy PRD 5.5's agent/tool/handoff blocks).

## 4. Honest progress and result

- **Decision**: Progress = existing `mission.progress` (workflow position only, 100% iff terminal) rendered as a bar + "%" with caption "Workflow position only — never simulated". Result block reads `result_summary/outcome/error` directly; `failed` gets a distinct style + "failed" label so it can never read as success (carries acceptance #9 forward).
- **Rationale**: Reuses the F1 honest-progress property; no timers touch progress or result (FR-007).
- **Alternatives considered**: Time-based or event-count progress — rejected (fabrication by definition).

## 5. Influence block composition

- **Decision**: Influence = `polls/current` (question/state/reveal/counts-or-hidden/deadline countdown for UX only) + latest `audience_decision_applied` event + `mission.branch_context` (applied decisions + current instruction). Counts hidden pre-close in `controlled` mode reuse the F3 audience-view rule; branch text comes from `branch_context.current_branch_instruction` with fallback to the event's `next_step`.
- **Rationale**: Single place where poll lifecycle (F3) meets workflow branch (F3 hook) meets display (F4); showing both the outcome and the branch it selected proves "audience changed the workflow" on one screen.
- **Alternatives considered**: Poll panel alone as the influence block — rejected (panel is a control surface; the spec needs a read-only influence summary plus branch linkage visible even after the poll leaves `current`).

## 6. Disconnected vs live, replay without duplicates

- **Decision**: Keep `EventSource` with `retry: 3000`, `?lastEventId=` + `Last-Event-ID` replay, `onopen → connected`, `onerror → disconnected`. History-load sets `lastEventId` to max seen id; live handler skips `ev.id <= lastEventId`. Banner copy stays exactly "Connected — live." / "Disconnected — showing last known state, not live." Sections never rewrite while disconnected except the banner.
- **Rationale**: Existing F1 transport already satisfies PRD §10 reconnect; F4 only extends the banner contract to all new sections (FR-009) and adds the dedup guard.
- **Alternatives considered**: Custom heartbeat/WebSocket — rejected (no benefit; SSE already proven in F1–F3).

## 7. Sanitized rendering without a library

- **Decision**: All dynamic strings via `textContent` / `createTextNode` only; structured rows built with `createElement` + `textContent`. Long tool summaries truncated client-side (e.g. 300 chars + "…") with full data left in the event log. One `try/catch` around `JSON.parse(msg.data)` keeps malformed rows from breaking the stream. No `innerHTML` for any untrusted data; audit with `grep innerHTML frontend/static/app.js`.
- **Rationale**: Same `textContent`-only pattern as F1–F3; safe by construction, zero dependencies.
- **Alternatives considered**: Sanitizer library (DOMPurify/bleach) — rejected (no HTML rendering needed at all).

## 8. Test strategy (no F1–F3 redo)

- **Decision**: New `tests/test_dashboard.py` asserts: (a) `index.html` contains all six required sections + banner + real-events-only labels; (b) `app.js` subscribes to every canonical/extended type and uses `textContent` (static file assertions, no browser needed); (c) mission + poll-current + events APIs expose every field the dashboard consumes (integration via TestClient). Regression guard only: existing `test_missions/test_events/test_polls/test_participants` must stay green; investigate only on failure.
- **Rationale**: Vanilla-JS dashboard is not unit-testable without a browser harness (out of scope); file + API-shape tests pin the contract F5 will rely on while honoring "do NOT redo T001–T044".
- **Alternatives considered**: Playwright/E2E — rejected (new harness + flake for a LAN demo; manual quickstart flows cover visual verification).
