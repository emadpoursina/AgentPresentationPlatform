# AGENTS.md — Live Agent Playground

<!-- BEGIN project control-plane (owned by onboarding — do not overwrite) -->

## Project control plane

- Project: live-agent-playground (agent-presentation-platform)
- Source of truth: `scratch/prd.md` (PRD for Live Agent Playground)
- Stack (confirmed): backend Python FastAPI + uv (light), frontend Vanilla HTML/JS + SSE, persistence SQLite
- Layout (planned): `backend/app/{api,missions,agents,events}` + `frontend/static/` + `data/` + `tests/`, managed by uv
- Common files: `.ainative/project.yaml` (onboarding-owned manifest; bootstrapper owns `validation_commands` replacement)
- Constraints: no commits/pushes/installs/validation runs in bootstrap sessions; scratch/ is gitignored working space

<!-- END project control-plane -->

## Project rules

### Stack and layout (confirmed)

- Backend: Python 3.12 + FastAPI (serve API, SSE/WebSocket, static frontend) via `uv`.
- Frontend: dependency-free vanilla HTML/JS + SSE in `frontend/static/` (no build step).
- Persistence: SQLite via `aiosqlite`, file under `data/` (gitignored).
- Layout: `backend/app/{api,missions,agents,events}`, `frontend/static/`, `data/`, `tests/`.
- Manifest: `pyproject.toml` only (no `package.json`; frontend has no build).

### Commands (tester runs these; bootstrap never runs them)

- `uv sync --group dev`
- `uv run ruff check .`
- `uv run pytest -q`
- Serve locally: `uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`

### PRD constraints (from `scratch/prd.md`)

- Hermes owns agent execution; mission controller stays a thin coordinator (no second agent framework).
- Profiles: Researcher, Critic, Summarizer only; browser capability via verified Hermes-compatible tool.
- Dashboard shows only real execution events; never fabricate progress or mock tool activity as real.
- Audience input affects real workflow branches; one vote per participant per poll; presenter tie-break.
- Security: API keys server-side only, no Hermes/direct host access for participants, validate all input, sanitize rendering, restrict browser to approved destinations, Telegram optional with web fallback.
- Reliability: reset function, visible mission state, manual fallback; main workflow never depends on Telegram.
