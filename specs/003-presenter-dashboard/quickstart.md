# Quickstart: Presenter Dashboard Real-Events-Only (F4)

Validation guide for the Walkthrough. Uses `uv run` commands per AGENTS.md; F1–F3 (T001–T044) taken as done — do not redo them, only the regression check noted. See [contracts/dashboard-api.md](contracts/dashboard-api.md) and [data-model.md](data-model.md).

## Prerequisites

- Server: `uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`
- Dashboard: `http://<host>:8000/` (presenter screen).

## Flow 1 — Mission header + result, zero fabrication (US1, SC-001/SC-003)

1. Load `/` with no missions → header shows "No mission yet", result empty, agent/tool/handoff/influence all show honest empty states.
2. New mission → Start → Pause → Resume → Complete(summary "ok", outcome "success") → header + progress + result update within ~3s per step; progress matches workflow position only.
3. New mission → Start → Fail(error "boom") → result shows error + outcome "failed" in a style distinct from success.
4. Idle 30s at any point → nothing advances on its own (no timers drive progress/result).

## Flow 2 — Agent/tool/handoff readiness (US2, SC-002)

1. With only F1–F3 events present → agent/tool/handoff sections each show "No ... yet — waiting for real execution events" and zero rows.
2. Inject one of each via Python (`event_store.append("agent_started", mid, {...})`, `tool_started`, `tool_completed`, `agent_handoff`, `agent_completed`, `agent_failed`) → each section lists exactly the injected rows with timestamp + mission id within ~3s, no refresh.
3. Payloads containing `<script>`/markup → render as inert text; page structure unchanged.

## Flow 3 — Influence + disconnect trust (US3, SC-004)

1. Start mission → open poll (2 options, live) → vote from a joined participant → close/resolve → influence block shows question/state/counts/outcome (`winning_option_id` + `decided_by`) + branch instruction from `branch_context`, each within ~3s.
2. Repeat with a `controlled`-mode poll → pre-close counts hidden, full counts + outcome at close.
3. Stop the server (or offline the browser) → banner reads "Disconnected — showing last known state, not live"; no section presents stale data as live. Restart → banner returns to "Connected — live", missed events replay with no duplicates.
4. Spot-check every activity row against `GET .../events` → 1:1 correspondence, zero fabricated entries; "Real events only" labels visually distinct from data.

## Regression (F1–F3, only if suspected)

- Mission start/pause/reset 200/409 behavior, presence convergence on join/leave, SSE replay via `Last-Event-ID` lossless, vote/tally/branch rules unchanged. Do not re-run T001–T044 wholesale.

## Commands

- `uv sync --group dev`
- `uv run ruff check .`
- `uv run pytest -q`
