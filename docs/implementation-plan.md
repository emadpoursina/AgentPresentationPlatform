# Implementation plan — Live Agent Playground (PRD handoff for `speckit-orchestrate`)

Source of truth: `scratch/prd.md` (gitignored working copy; do not treat this file as spec).
Scaffold baseline (already committed): Python 3.12 + FastAPI + uv, vanilla HTML/JS + SSE in
`frontend/static/`, SQLite via `aiosqlite` under `data/`, layout
`backend/app/{api,missions,agents,events}` + `tests/`. Health probe: `GET /api/health`.
Validation (tester runs, bootstrap never runs): `uv sync --group dev`, `uv run ruff check .`, `uv run pytest -q`.

## Prerequisite — Spec Kit is NOT installed in this repo

`speckit-orchestrate` refuses to run without it. Before any slice below:

1. `ls .specify` and `ls .pi/prompts/speckit.specify.md` must both exist. Today neither exists.
2. Initialise Spec Kit per your standard installer (do NOT hand-roll `.specify/` in a feature session).
3. Re-run `ready` via orchestrate; it creates the feature branch + worktree. Never commit to
   `master` (protected). Never commit/push/PR from a worker — parent ships.

If `ready` reports `READY: blocked`, fix `CHECKS`/`FIXES` first. Do not skip to implement.

## How to run each slice

One orchestrate run per slice, in order F1 → F8 (F9 optional). Example:

```text
/speckit-orchestrate path: feature F1 mission controller, event model, and SSE stream per scratch/prd.md sections 4C and 10
```

- Use `path: feature` for F1–F9 (new behaviour, needs specify → clarify → plan → tasks → implement → converge).
- Use `path: change` only for small fixes to an already-shipped slice.
- Use `skip` only if you want clarify to self-answer with recommended options; otherwise answer its max-5 questions.
- Ship decision and UAT are parent-only. Workers stay ship-dumb.

## Slice order and scope (P0 first, P1 gated, P2 forbidden)

### F1 — Mission controller + event model + SSE stream (P0 core)
PRD: 4C, 5.3, 10 (event format), 6 workflow requirements.
Scope: mission state machine (created → running → paused → completed/failed + reset), canonical
event list (`mission_started … mission_completed`), timestamp + mission_id + safe metadata,
SSE endpoint with reconnect + disconnected state. No agent logic, no polls yet.
Acceptance: PRD §13 #2 (start/reset), #8 (dashboard reflects real events), #9 (failure ≠ success).

### F2 — Join + QR + presence (P0)
PRD: 4B, 5.1, 10 local networking.
Scope: join page (display name or anonymous, no accounts), QR for actual join URL, participant count,
local-bind + hotspot reachability notes. Validate every input server-side.
Acceptance: §13 #1.

### F3 — Polls + voting + decision-applied branch (P0)
PRD: 5.2, 5.3, 5.4.
Scope: poll open/close/deadline, one vote per participant per poll (changeable before deadline),
live counts or controlled reveal, presenter tie-break + no-vote fallback, `audience_decision_applied`
recorded in history and passed into the real workflow branch (not cosmetic).
Acceptance: §13 #6.

### F4 — Presenter dashboard, real events only (P0)
PRD: 5.5.
Scope: mission title/status/step/progress; agent name/role/status/task; tool name/action/status/safe
summary; handoff who→whom + reason; poll + outcome + branch taken; final result + caveats + status.
Must distinguish real execution events from explanatory UI text; no fabricated progress.
Acceptance: §13 #8.

### F5 — Agent profiles + serial workflow + Hermes wiring (P0)
PRD: 4A, 4E, 6, 8, 12-Day-1.
Scope: Researcher → Critic → Summarizer serial handoffs (outputs passed, not copy-paste), role I/O
per §6, timeouts + error recovery, model strategy (free-tier API first; verify quota/tool-call/latency),
no second agent framework, no self-granted tools. Terminal-runnable end-to-end first.
Acceptance: §13 #3, #4, #5, #12.

### F6 — Real browser demonstration + fallback (P0)
PRD: 5.6.
Scope: verify existing Hermes-compatible browser tool first; dedicated profile, public read-only pages,
approved-destination allowlist, visible navigation alongside/alternating dashboard, extraction →
Critic → Summarizer. On failure: clear error + non-browser mission fallback; never mock as real.
Acceptance: §13 #7, #13.

### F7 — Presenter controls + error/recovery + safety (P0)
PRD: 3 (presenter), 8 failure/usage, 9 restrictions, 10 security/reliability.
Scope: start/pause/reset, mission select, poll close, usage/token limits, quota warnings, retry/switch/
cancel, API keys server-side only, no anonymous Hermes calls, sanitise rendering, hide private traces,
manual fallback + visible mission state.
Acceptance: §13 #11, #12, #13.

### F8 — Q&A (web fallback first, Telegram optional P1)
PRD: 7.
Scope: submit + one-vote-per-question + ranking + presenter select/answer/archive/remove; runs
independent of main workflow. Build web fallback first; add Telegram bot only if time permits and
never as a main-workflow dependency.
Acceptance: §13 #10.

### F9 — Playground + usage indicators (P1, gated — do last)
PRD: 8 usage, 9 playground.
Scope: presenter-enabled only, bounded tasks (ask/summarise/translate/bounded research), rate/task/
duration caps, instant disable, no shell/files/secrets/unrestricted browser/spawn/config changes.
Core demo must work with it off.

## Out of scope (do not accept as feature work)
PRD P2 §11: accounts, public hosting, arbitrary user agents, unlimited agent-to-agent chat,
general computer control, persistent profiles, multi-tenant infra, complex analytics.

## Done means (per slice)
Its §13 acceptance items pass on two phones over hotspot, failures shown honestly, no secrets leak,
and converge reports `CONVERGED` before the parent asks the ship decision.
