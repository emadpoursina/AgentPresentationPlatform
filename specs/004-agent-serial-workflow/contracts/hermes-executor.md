# Contract: Hermes Executor Adapter (`backend/app/agents/executor.py`)

**Feature**: [spec.md](../spec.md) | **Plan**: [plan.md](../plan.md) | **Date**: 2026-10-15

The executor is F5's only boundary to the outside model world. Everything behind it (profiles, runner, events) is model- and CLI-agnostic, which is what makes quota-free stub tests possible (FR-023).

## Interface (protocol)

```python
class AgentExecutor(Protocol):
    def run(self, ctx: StepContext, emit: Callable[[str, dict], None]) -> AgentStepResult: ...
```

- `run` is **synchronous**: `HermesCliExecutor` uses `subprocess.Popen` (argv list) on the calling thread — the runner's single worker thread on the API path, the main thread on the CLI path. No `asyncio` anywhere in F5 (research.md §1/§4); stdout is consumed incrementally in that same thread so the cancel poll (rule 5) runs every 0.5s.
- `StepContext`: `{agent_id, profile_id, toolsets, task_text, timeout_seconds, run_budget_seconds, max_turns, workdir}` — fully describes one agent step.
- `emit(event_type, data)` — called *during* execution for `tool_started` / `tool_completed` only; the runner owns all other event emission.
- Returns `AgentStepResult {output, session_id, tool_calls, duration_seconds}` on success.
- Raises typed errors — the runner maps each to `agent_failed` + mission abort (FR-020):
  - `AgentStepTimeout` — outer wall-clock timeout hit; subprocess killed (SIGTERM, then SIGKILL after 5s).
  - `AgentToolError` — a real tool call failed in a way that invalidates the step (non-zero exit on the step's required tool use, or Hermes exited non-zero after tool activity).
  - `AgentExitedError` — non-zero process exit / spawn failure (includes "Hermes unreachable or misconfigured" fail-fast case).
  - `AgentOutputError` — empty or > `max_output_chars` output after trimming (edge case: garbage must not flow downstream).

## Invocation (the exact CLI shape, from the passed pre-flight + `hermes chat --help`)

```text
hermes chat -Q --oneshot \
  --query-file <tempfile> \
  --format stream-json \
  -t <toolsets> \
  --max-turns <N> \
  --run-budget <SECONDS> \
  --in <workdir>
```

Rules:

1. **Task text only via `--query-file`** (CLI-documented as safe for arbitrary text — nothing shell-interpreted). Never `-q`, never a shell (`subprocess.Popen`, argv list). This is the injection boundary for untrusted branch instructions and agent outputs.
2. **No credentials in app code or env**: Hermes uses its own pooled auth store (`hermes auth status opencode-go` → logged in). F5 never reads, writes, or forwards API keys.
3. **Working dir** = a per-mission directory under `data/runs/<mission_id>/` (gitignored); Researcher's `terminal` tool is scoped there by convention + instructions.
4. **Model/provider are NOT passed as flags** — Hermes resolves them (pre-flight-verified: `muse-spark-1.3-contributor` @ `opencode-go`, `codex_responses`). The runner separately pins the resolved value via `modelinfo` (FR-011) so a silent profile change is refused, never papered over with `-m`.
5. **Kill on cancel**: the stream-read loop polls the mission's cancel `threading.Event` every 0.5s; set by `reset` during execution — subprocess killed, `AgentStepTimeout`-style abort raised, no orphan.
6. **Toolsets literal**: Researcher → `-t terminal`; Critic/Summarizer → **`-t none`** (the pinned tool-free literal — pre-flight-probed with exit 0; the CLI's benign `Warning: Unknown toolsets: none` must be ignored by the parser and never surfaced as step output or as a failure; omitting `-t` is forbidden — it would enable the CLI's default toolsets and violate least privilege). Confirmation that a `-t none` step produces zero `tool_execution_*` events belongs to the bounded invocation in the stream-parsing section below (T072) and must hold before T080 maps tool events.

## Stream parsing (isolation contract)

One module parses `--format stream-json` JSONL from stdout. Observed schema family (pre-flight session log): `session {id, …}`, `agent_start`, `turn_start`, `message_*`, `tool_execution_start {toolName, args}`, `tool_execution_update`, `tool_execution_end {toolName, result}`, `turn_end`, `agent_end`, `agent_settled {aborted}`.

Mapping:

| Stream event | F5 action |
|---|---|
| `session` | record `session_id` on the step result |
| `tool_execution_start` | `emit("tool_started", {agent_id, tool_name: toolName, action: short safe summary of args})` |
| `tool_execution_end` | `emit("tool_completed", {agent_id, tool_name, status: "completed"\|"failed", summary: truncated result, exit_code?})` |
| final assistant text (`turn_end`/`agent_end`) | step `output` |
| `agent_settled {aborted: true}` | treat as step failure with reason |

Unknown event types are ignored (forward-compatible); never fabricated into F5 events. **Implementation-time verification (bounded, not a pre-flight re-run)**: confirm the envelope **and the `-t none` tool-free sentinel (zero `tool_execution_*` lines on a tool-free step)** against one real opt-in invocation (`F5_REAL_E2E=1` or one manual `hermes chat -Q --format stream-json …`) — one bounded invocation owns both confirmations (research.md §2/§3), and it runs before T080 relies on tool mapping and before the real E2E (T070) is executed; if Hermes's schema differs from the family above, only this parser changes.

Tool-free profiles (argv `-t none`) must produce **zero** `tool_execution_*` events (contract test in the opt-in real run; stub tests assert the adapter passes the profile's `toolsets` through verbatim).

## Fake/stub contract (tests, default gate runs)

`FakeExecutor` implements the same protocol with scripted steps:

- `FakeExecutor(steps={profile_id: StepScript(output=…, tool_events=[…], fail=…, delay=…)})`
- Can simulate: normal output, tool round trips (emits matching `tool_started`/`tool_completed`), timeout (`AgentStepTimeout`), tool failure, model error (`AgentExitedError`), empty/oversized output (`AgentOutputError`), and configurable delay for timeout tests (with a 50ms test timeout, not 300s).
- Zero subprocesses, zero quota, runs in milliseconds (FR-023).
- A separate adapter-shape fixture (fake `hermes` executable on `PATH` printing canned JSONL) exercises the real subprocess plumbing without any model call.

## Quota & model helpers (same package)

- `quota.check(overrides_confirm: bool) -> QuotaDecision {allowed, needs_confirmation, remaining_pct, note}` via `hermes usage --json` (60s cache; `available=false` ⇒ fail-open with visible warning).
- `modelinfo.resolve() -> ResolvedModel {default, provider, base_url, api_mode}` via `hermes config get model`; runner refuses to start unless it equals the pre-flight pin (`muse-spark-1.3-contributor` / `opencode-go`).
