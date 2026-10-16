# Implementation Plan: Agent Profiles + Serial Hermes Workflow (F5)

**Branch**: `serial-agent-handoffs` | **Date**: 2026-10-15 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/004-agent-serial-workflow/spec.md` — F5 agent profiles + serial Researcher→Critic→Summarizer handoffs over the real Hermes harness per `scratch/prd.md` §4A/§4E/§6/§8 and `docs/implementation-plan.md` L62-67 (acceptance #3/#4/#5/#12). F1–F4 (T001–T058) taken as done; the PRD §8 pre-flight already PASSED (evidence `.agent/pi/f5-preflight/2026-10-15T21-48-43-554Z_4af17e/report.json`) and is not re-run.

## Summary

F5 turns the F1 thin coordinator into a real executor without becoming a second agent framework: a subprocess adapter drives the installed Hermes CLI (v0.21.7, resolved model `muse-spark-1.3-contributor` on `opencode-go` — documented free-tier deviation) once per agent step, a serial workflow runner composes each step's task from the mission objective + F3's `branch_context` + the previous agent's output and passes it programmatically (no copy-paste), emits only the six canonical agent/tool events F4 already renders (1:1 with real execution), enforces per-step timeouts and PRD §8 usage controls (single active agent, `--max-turns`/run-budget caps, `hermes usage`-based quota gate blocking start below 35% remaining unless the operator confirms), aborts any mid-mission step failure into the failed terminal state with completed outputs preserved, and offers a deliberate retry that resumes at the failed step without re-executing completed agents. Terminal-runnable in-process CLI is the primary acceptance path; unit/integration tests stub the executor, with exactly one real end-to-end test behind an opt-in marker + env flag. Zero frontend and zero event-protocol changes.

## Technical Context

**Language/Version**: Python 3.12 (`requires-python = ">=3.12"`) + dependency-free vanilla HTML/JS + SSE (frontend untouched by F5).

**Primary Dependencies**: FastAPI 0.143.1, uvicorn 0.54.0, Pydantic 2.14.1, aiosqlite 0.22.1, httpx 0.28.1 (tests). **No new Python dependencies** — the Hermes integration is `subprocess` against the already-installed CLI (`/Users/emad/.local/bin/hermes`, v0.21.7, verified by the passed pre-flight). Dev: pytest 9.1.1, ruff 0.17.0.

**Storage**: Same in-memory mission store + event log (F1). F5 extends the `Mission` record additively (per-step agent run records, failure reason/step, retry count, resolved model) — no schema/migration, no new persistence layer (SQLite file wiring remains out of F5 as it was for F1–F4).

**Testing**: pytest 9.1.1 + ruff 0.17.0. Gates (tester runs, per AGENTS.md): `uv sync --group dev`, `uv run ruff check .`, `uv run pytest -q` (57-test baseline must stay green; F5 tests only add). One real end-to-end mission test opt-in via new `real_e2e` marker + `F5_REAL_E2E=1`, excluded from the default gate run.

**Target Platform**: Local-network server (`uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`) + operator terminal (primary acceptance path) + existing dashboard at `/`.

**Project Type**: Web application (FastAPI backend + vanilla `frontend/static/`), with a new in-process CLI entry (`python -m backend.app.cli`) for the terminal-first acceptance path.

**Performance Goals**: Each agent step completes within its configured timeout (default 300s wall; pre-flight measured 12–15s wall for a trivial Hermes turn including CLI bootstrap); agent/tool events appear on the live dashboard within ~2s of the real occurrence (streamed from `--format stream-json` as execution happens); mission start refuses in <2s when the quota gate blocks.

**Constraints**: Hermes is the sole executor — the mission controller stays a thin coordinator, no second agent framework, no self-granted tools (FR-003/FR-007/FR-022); emit only the six canonical agent/tool events F4 renders, each 1:1 with a real occurrence (FR-012/FR-013); abort-to-failed-terminal on any step failure with completed outputs preserved, retry resumes at the failed step (FR-020/FR-021); quota gate blocks start below 35% remaining without explicit confirmation (FR-024); resolved model pinned to the pre-flight-verified one, re-pre-flight on any change (FR-011); F1–F4 behavior frozen — 57-test baseline + lint stay green (FR-019).

**Scale/Scope**: One room, one active mission, three serial agent steps. Roughly: `backend/app/agents/` (~6 new modules: profiles, executor, runner, quota, modelinfo, settings ≈ 600–800 LOC), additive `Mission` fields + narrow controller hooks (≈ 100 LOC), two new mission routes (`run`, `retry`) + CLI entry (≈ 150 LOC), `pyproject.toml` marker, and new tests (`tests/test_agents*.py`, ≈ 400 LOC). No frontend changes at all.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is an unratified placeholder template with no enforceable principles, so there are no constitution-derived gates to violate (same finding as the F4 plan). Evaluated against standing project rules from `AGENTS.md` / PRD instead:

- [x] Hermes owns agent execution; the coordinator only composes tasks, passes outputs, enforces timeouts/limits, and publishes events — the subprocess adapter is an integration boundary, not an agent loop (PRD §4C, project rules) — PASS.
- [x] Profiles: exactly Researcher, Critic, Summarizer; Researcher alone gets the pre-flight-verified `terminal` tool, Critic/Summarizer tool-free (FR-003/FR-022) — PASS.
- [x] Dashboard shows only real execution events; every agent/tool event maps 1:1 to a real Hermes run/tool call, streamed from the executor's own JSONL output — no synthetic events (FR-008/FR-013) — PASS.
- [x] Audience input (F3 `branch_context`) consumed as-is as a real task input; F3 production logic untouched (FR-005) — PASS.
- [x] Security: API keys stay inside Hermes' own auth store — never read by app code; all task text passed via `--query-file` (stdin/file), never shell-interpreted; subprocess runs with a scoped working dir; input size-bounded (PRD §9 security constraints) — PASS.
- [x] Reliability: per-step timeout, abort-to-failed-terminal, visible errors, reset cancels in-flight execution, manual terminal fallback (PRD §10) — PASS.
- [x] Main workflow never depends on Telegram; F5 is web/terminal only (Telegram is F8) — PASS.
- [x] Stack gates: Python 3.12 + FastAPI via uv, no new deps, no frontend build step (AGENTS.md) — PASS.

No violations. No Complexity Tracking entry required.

*Post-design re-check (after Phase 1): still PASS — the design adds one subprocess integration boundary and additive state only; the coordinator remains thin, events stay canonical and real, and no F1–F4 contract is modified.*

## Project Structure

### Documentation (this feature)

```text
specs/004-agent-serial-workflow/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   ├── hermes-executor.md      # CLI adapter contract + stub interface
│   ├── agent-event-payloads.md # exact data keys for the 6 canonical events
│   └── workflow-api.md         # run/retry endpoints + mission record additions
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── agents/                # EXTEND (currently package stub only)
│   │   ├── profiles.py        # NEW: Researcher/Critic/Summarizer definitions + toolsets
│   │   ├── executor.py        # NEW: AgentExecutor protocol, HermesCliExecutor (subprocess), stub-able
│   │   ├── runner.py          # NEW: SerialWorkflowRunner (handoffs, timeouts, abort, retry-resume)
│   │   ├── quota.py           # NEW: hermes usage --json gate (35% default threshold)
│   │   ├── modelinfo.py       # NEW: resolved-model capture + pre-flight pin guard
│   │   └── settings.py        # NEW: RunLimits defaults + env overrides
│   ├── api/
│   │   └── missions.py        # EXTEND: POST /{id}/run, POST /{id}/retry (+ cancel-on-reset hook)
│   ├── missions/
│   │   ├── models.py          # EXTEND: additive Mission fields (agent_runs, failure, retry, resolved_model)
│   │   └── controller.py      # EXTEND: narrow step/retry transition hooks (still no execution logic)
│   ├── events/                # UNCHANGED (all 6 F5 event types already exist and validate)
│   ├── cli.py                 # NEW: python -m backend.app.cli run "topic" (terminal acceptance path)
│   └── main.py                # UNCHANGED (routes live on the existing missions router)
frontend/
└── static/                    # UNCHANGED (F4 already renders the 6 events; FR-012 forbids F5 UI work)
tests/
├── test_health.py             # existing (regression only)
├── test_events.py             # existing (regression only)
├── test_missions.py           # existing (regression only)
├── test_participants.py       # existing (regression only)
├── test_polls.py              # existing (regression only)
├── test_dashboard.py          # existing (regression only)
├── test_agent_profiles.py     # NEW: profile defs, least-privilege toolsets, task composition
├── test_agent_runner.py       # NEW: stub-executor serial flow, events 1:1, abort, retry-resume
├── test_quota_gate.py         # NEW: gate math, block/confirm, usage-unavailable behavior
└── test_agent_e2e_real.py     # NEW: single real end-to-end mission (real_e2e marker + F5_REAL_E2E=1)
pyproject.toml                 # EXTEND: [tool.pytest.ini_options] markers = ["real_e2e: ..."]
```

**Structure Decision**: Web-application layout following the existing `backend/app/{api,missions,polls,events}` convention. All execution logic lands in the already-reserved `backend/app/agents/` package (its docstring explicitly anticipates F5); mission changes are additive model fields plus narrow controller transitions; the terminal path is a thin in-process CLI that reuses the exact same runner as the API (one code path, not two). No new top-level packages, no new dependencies, no frontend change.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — no violations.
