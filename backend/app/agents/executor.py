"""Hermes executor boundary — F5's only path to the model world (contracts/hermes-executor.md).

This module holds the `AgentExecutor` protocol, the per-step context/result
shapes, and the typed errors the runner maps to `agent_failed` + mission
abort. The subprocess adapter (`HermesCliExecutor`) and the isolated
stream-json parser live here too (T071/T072/T080); unit tests inject a
`FakeExecutor` instead, so default gate runs make zero model calls (FR-023).

Sync by contract: `run` is a plain function executed on the calling thread
(runner worker thread on the API path, main thread on the CLI path). No
asyncio anywhere in F5 (research.md §1).
"""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

# -- typed errors (runner maps each to agent_failed + mission abort, FR-020) --


class AgentStepError(RuntimeError):
    """Common ancestor of all typed step failures."""


class AgentStepTimeout(AgentStepError):
    """Outer wall-clock timeout hit; subprocess killed (SIGTERM, SIGKILL after 5s)."""


class AgentCancelled(AgentStepTimeout):
    """Cancellation flavour of the timeout abort (executor contract rule 5):
    the mission's cancel event fired (reset during execution) and the
    in-flight subprocess was killed."""


class AgentToolError(AgentStepError):
    """A real tool call invalidated the step (non-zero exit after tool activity)."""


class AgentExitedError(AgentStepError):
    """Non-zero process exit / spawn failure / harness misconfiguration."""


class AgentOutputError(AgentStepError):
    """Empty or over-bound output after trimming (garbage must not flow downstream)."""


def failure_kind_for(exc: BaseException) -> str:
    """Map a typed executor error to the contract's `failure_kind` values
    (contracts/agent-event-payloads.md): timeout | tool | model |
    output_invalid | cancelled. Unexpected non-typed errors surface as
    `model` — the runner wraps them in `AgentExitedError` before calling."""
    if isinstance(exc, AgentCancelled):
        return "cancelled"
    if isinstance(exc, AgentStepTimeout):
        return "timeout"
    if isinstance(exc, AgentToolError):
        return "tool"
    if isinstance(exc, AgentOutputError):
        return "output_invalid"
    return "model"  # AgentExitedError and wrapped harness errors


# -- protocol + shapes (contract: Interface (protocol)) -----------------------


@dataclass(frozen=True)
class StepContext:
    """Fully describes one agent step handed to the executor."""

    agent_id: str
    profile_id: str
    toolsets: str  # verbatim `-t` value; never empty (omitting -t is forbidden)
    task_text: str
    timeout_seconds: int
    run_budget_seconds: int
    max_turns: int
    workdir: str


@dataclass
class AgentStepResult:
    """Successful step result returned by `AgentExecutor.run`."""

    output: str
    session_id: str | None = None
    tool_calls: int = 0
    duration_seconds: float = 0.0


@runtime_checkable
class AgentExecutor(Protocol):
    """Sync executor protocol. `emit` is used for tool_started/tool_completed
    during execution only; the runner owns every other event."""

    def run(self, ctx: StepContext, emit: Callable[[str, dict], None]) -> AgentStepResult: ...


# -- subprocess adapter (T071) + isolated stream-json parser (T072/T080) -----
#
# Invocation decision (attempt 2, bounded probes — see contracts/hermes-executor.md):
# the `hermes` on PATH is a host shim (`~/.local/bin/hermes`) that `docker exec -i`
# into the `hermes-personal-coding` container. Repo paths are invisible inside it,
# so:
#   * the query travels over **stdin** (`--query-file -`, CLI-documented as
#     reading stdin) — never a host tempfile the container cannot see;
#   * `--in` must point at the container-visible bind mount
#     `/opt/data/mnt/workspace` (host `hermes-data/workspace`), not `data/runs/…`.
# Host-side `data/runs/<mission_id>/` still captures the raw stream + stderr
# for audit (gitignored, T060). The docker/workspace roots are env-overridable
# (`F5_HERMES_WS_HOST` / `F5_HERMES_WS_IN`) so a non-docker hermes install can
# point both at the same directory.

DEFAULT_WS_HOST = "/Users/emad/Projects/playground/hermes-data/workspace"
DEFAULT_WS_IN = "/opt/data/mnt/workspace"
RUNS_SEGMENT = "f5-runs"  # per-mission dir name under the workspace roots


def _env_or(key: str, default: str) -> str:
    value = os.environ.get(key, "").strip()
    return value or default


def container_workdir(mission_dir_name: str) -> str:
    """Container-side `--in` path for a mission (contract rule 3, amended)."""
    ws_in = _env_or("F5_HERMES_WS_IN", DEFAULT_WS_IN).rstrip("/")
    return f"{ws_in}/{RUNS_SEGMENT}/{mission_dir_name}"


def prepare_workdirs(host_run: Path) -> tuple[Path, str]:
    """Create the host audit dir (`data/runs/<mission_id>`) and the
    container-visible mission dir; returns (host_run_dir, container --in path)."""
    host_run.mkdir(parents=True, exist_ok=True)
    ws_host = Path(_env_or("F5_HERMES_WS_HOST", DEFAULT_WS_HOST))
    (ws_host / RUNS_SEGMENT / host_run.name).mkdir(parents=True, exist_ok=True)
    return host_run, container_workdir(host_run.name)


def build_argv(ctx: StepContext, workdir_in: str) -> list[str]:
    """The exact pinned argv (contracts/hermes-executor.md `Invocation`), with
    the stdin amendment: `--query-file -` reads the task from stdin."""
    return [
        "hermes", "chat", "-Q", "--oneshot",
        "--query-file", "-",
        "--format", "stream-json",
        "-t", ctx.toolsets,
        "--max-turns", str(ctx.max_turns),
        "--run-budget", str(ctx.run_budget_seconds),
        "--in", workdir_in,
    ]


@dataclass
class _StreamState:
    """Isolated parse state for one step's `--format stream-json` JSONL."""

    session_id: str | None = None
    text_parts: list[str] = field(default_factory=list)
    final_text: str | None = None
    result_exit: int | None = None
    aborted: bool = False
    tool_starts: int = 0
    tool_ends: int = 0
    tool_failures: int = 0


def _args_summary(args) -> str:
    """Short, safe action summary for `tool_started` — command text only,
    never secrets/env dumps (agent-event-payloads.md, contract rule)."""
    if isinstance(args, dict):
        text = args.get("command") or args.get("cmd") or args.get("file") or args
    else:
        text = args
    return str(text)[:120]


def _result_summary(result) -> tuple[str, str, int | None]:
    """(status, summary≤300, exit_code) for a `tool_execution_end` result."""
    status, exit_code = "completed", None
    if isinstance(result, dict):
        exit_code = result.get("exit_code")
        if result.get("is_error") or (exit_code not in (None, 0)):
            status = "failed"
        text = result.get("output") or result.get("stdout") or result.get("text") or result
    else:
        text = result
    return status, str(text)[:300], exit_code if isinstance(exit_code, int) else None


def parse_stream_line(
    line: str,
    state: _StreamState,
    emit: Callable[[str, dict], None],
    ctx: StepContext,
) -> None:
    """Map one stdout line to parse state / tool emissions.

    Real envelope (confirmed 2026-10-16 bounded probe, exit 0):
      {"type":"system","subtype":"init","session_id":…}
      {"type":"text","text":…}
      {"type":"result","session_id":…,"exit_code":…,"text":…}
    Non-JSON lines (the benign `Warning: Unknown toolsets: none` from `-t none`)
    and unknown event types are ignored — never surfaced as output or failure
    (contract rule 6 / isolation contract). `tool_execution_*` and
    `agent_settled` map per the contract table (real shape unobserved for tool
    turns; unknown keys ignored, forward-compatible)."""
    stripped = line.strip()
    if not stripped.startswith("{"):
        return  # CLI noise (e.g. the `-t none` warning) — ignored by contract
    try:
        event = json.loads(stripped)
    except (ValueError, TypeError):
        return
    if not isinstance(event, dict):
        return
    etype = event.get("type")
    if etype == "system" and event.get("subtype") == "init":
        state.session_id = event.get("session_id") or state.session_id
    elif etype == "session":  # contract schema family fallback
        state.session_id = event.get("id") or event.get("session_id") or state.session_id
    elif etype == "text":
        state.text_parts.append(str(event.get("text", "")))
    elif etype == "result":
        state.final_text = str(event.get("text", ""))
        state.session_id = event.get("session_id") or state.session_id
        exit_code = event.get("exit_code")
        state.result_exit = exit_code if isinstance(exit_code, int) else state.result_exit
    elif etype == "tool_execution_start":
        state.tool_starts += 1
        emit("tool_started", {
            "tool_name": event.get("toolName") or event.get("tool_name") or "unknown",
            "action": _args_summary(event.get("args")),
        })
    elif etype == "tool_execution_end":
        state.tool_ends += 1
        status, summary, exit_code = _result_summary(event.get("result"))
        if status == "failed":
            state.tool_failures += 1
        payload = {
            "tool_name": event.get("toolName") or event.get("tool_name") or "unknown",
            "status": status,
            "summary": summary,
        }
        if exit_code is not None:
            payload["exit_code"] = exit_code
        emit("tool_completed", payload)
    elif etype == "agent_settled":
        if event.get("aborted") is True:
            state.aborted = True
    # unknown types ignored (never fabricated into F5 events)


class HermesCliExecutor:
    """`AgentExecutor` subprocess adapter (T071): argv-list `subprocess.Popen`
    on the calling thread, task text over stdin, stream-json consumed in the
    same thread with a 0.5s cancel/timeout poll, SIGTERM → SIGKILL after 5s
    on cancel (own process group). No asyncio, no shell, no credentials."""

    def __init__(self, cancel_event: threading.Event | None = None) -> None:
        self.cancel_event = cancel_event or threading.Event()

    def run(self, ctx: StepContext, emit: Callable[[str, dict], None]) -> AgentStepResult:
        started = time.monotonic()
        host_run = Path(ctx.workdir) if ctx.workdir else Path("data/runs") / "mission"
        host_run, workdir_in = prepare_workdirs(host_run)
        argv = build_argv(ctx, workdir_in)

        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,  # own process group → killpg on cancel/timeout
        )

        def _feed_stdin() -> None:
            try:
                assert proc.stdin is not None
                proc.stdin.write(ctx.task_text)
                proc.stdin.close()
            except (BrokenPipeError, ValueError, OSError):
                pass

        threading.Thread(target=_feed_stdin, daemon=True).start()

        state = _StreamState()
        stream_path = host_run / "stream.jsonl"
        stderr_path = host_run / "stderr.log"
        failure: AgentStepError | None = None

        with open(stream_path, "w", encoding="utf-8") as stream_file:
            assert proc.stdout is not None
            while True:
                if self.cancel_event.is_set():
                    failure = AgentCancelled(
                        "execution cancelled (in-flight subprocess killed)"
                    )
                    _terminate(proc)
                    break
                elapsed = time.monotonic() - started
                if elapsed >= ctx.timeout_seconds:
                    failure = AgentStepTimeout(
                        f"step timeout after {ctx.timeout_seconds}s (killed)"
                    )
                    _terminate(proc)
                    break
                ready, _, _ = select.select([proc.stdout], [], [], 0.5)
                if not ready:
                    continue
                line = proc.stdout.readline()
                if line == "":
                    break  # EOF — process exiting
                stream_file.write(line)
                stream_file.flush()
                parse_stream_line(line, state, emit, ctx)

        stderr_text = ""
        try:
            if proc.stderr is not None:
                stderr_text = proc.stderr.read() or ""
        except (ValueError, OSError):
            pass
        try:
            returncode = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _terminate(proc)
            returncode = proc.wait(timeout=5)
        stderr_path.write_text(stderr_text, encoding="utf-8")

        if failure is not None:
            raise failure
        if state.aborted:
            raise AgentExitedError("agent settled aborted=true (step failed)")
        if state.result_exit not in (None, 0) or returncode != 0:
            code = state.result_exit if state.result_exit not in (None, 0) else returncode
            tail = stderr_text.strip().splitlines() if stderr_text.strip() else []
            detail = tail[-1][:300] if tail else ""
            message = f"hermes exited {code}" + (f": {detail}" if detail else "")
            if state.tool_ends > 0 or state.tool_failures > 0:
                raise AgentToolError(
                    message + f" (after {state.tool_ends} real tool event(s))"
                )
            raise AgentExitedError(message)

        output = (
            state.final_text if state.final_text is not None else "".join(state.text_parts)
        ).strip()
        if not output:
            raise AgentOutputError("empty agent output after stream parse")
        return AgentStepResult(
            output=output,
            session_id=state.session_id,
            tool_calls=state.tool_ends,
            duration_seconds=round(time.monotonic() - started, 3),
        )


def _terminate(proc: subprocess.Popen) -> None:
    """SIGTERM the process group, SIGKILL after 5s (contract rule 5)."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
