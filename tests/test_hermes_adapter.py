"""T071/T072/T080: the real subprocess plumbing, without any model call.

A fake `hermes` executable is placed at the front of PATH. It records its
argv and stdin to files and prints the exact envelope confirmed by the
2026-10-16 bounded probe (`system init` → `text` → `result`, plus the benign
`Warning: Unknown toolsets: none` line and a tool round trip). This exercises
argv construction, stdin query transport, the isolated JSONL parser, tool
event mapping, the 0.5s cancel/timeout poll, and process-group kill — all
quota-free (FR-023). The single real invocation lives in
`tests/test_agent_e2e_real.py` (double-gated).
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from backend.app.agents.executor import (
    AgentCancelled,
    AgentExitedError,
    AgentStepTimeout,
    AgentToolError,
    HermesCliExecutor,
    StepContext,
)

ENVELOPE_LINES = [
    "Warning: Unknown toolsets: none",  # benign `-t none` noise — must be ignored
    '{"type": "system", "subtype": "init", "model": "muse-spark-1.3-contributor",'
    ' "session_id": "sess-123", "timestamp": 1}',
    '{"type": "text", "text": "OK", "timestamp": 2}',
    '{"type": "tool_execution_start", "toolName": "terminal", "args": {"command": "ls -la"}}',
    '{"type": "tool_execution_end", "toolName": "terminal",'
    ' "result": {"exit_code": 0, "output": "file.txt"}}',
    '{"type": "result", "session_id": "sess-123", "exit_code": 0, "text": "OK",'
    ' "tokens": {"input": 1380, "output": 55}}',
]

_ENVELOPE = "\n".join(
    "printf '%s\\n' '" + line + "'" for line in ENVELOPE_LINES
)

FAKE_SCRIPT = (
    "#!/bin/bash\n"
    "printf '%s\\n' \"$@\" > \"$FAKE_ARGV_LOG\"\n"
    "cat > \"$FAKE_STDIN_LOG\"\n"
    "if [ -n \"${FAKE_SLEEP:-}\" ]; then sleep \"$FAKE_SLEEP\"; fi\n"
    + _ENVELOPE
    + "\nexit \"${FAKE_EXIT:-0}\"\n"
)


@pytest.fixture
def fake_hermes(tmp_path, monkeypatch):
    """Fake `hermes` on PATH + isolated workspace roots (no repo/docker side
    effects beyond the gitignored `data/runs/<dir>` audit dir)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "hermes"
    script.write_text(FAKE_SCRIPT)
    script.chmod(0o755)
    logs = {
        "FAKE_ARGV_LOG": str(tmp_path / "argv.log"),
        "FAKE_STDIN_LOG": str(tmp_path / "stdin.log"),
        "FAKE_WS_HOST": str(tmp_path / "ws-host"),
    }
    for key, value in logs.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("F5_HERMES_WS_HOST", logs["FAKE_WS_HOST"])
    monkeypatch.setenv("F5_HERMES_WS_IN", "/container/ws")
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    monkeypatch.delenv("FAKE_SLEEP", raising=False)
    monkeypatch.delenv("FAKE_EXIT", raising=False)
    return tmp_path


def _ctx(tmp_path, *, timeout: int = 10) -> StepContext:
    return StepContext(
        agent_id="research-1",
        profile_id="researcher",
        toolsets="none",  # the pinned tool-free literal flows through verbatim
        task_text="TASK: reply with OK.\nSecond line with $(meta) chars.",
        timeout_seconds=timeout,
        run_budget_seconds=10,
        max_turns=3,
        workdir=str(tmp_path / "data" / "runs" / "adap"),
    )


def test_adapter_argv_stdin_and_envelope(fake_hermes, tmp_path) -> None:
    emitted: list[tuple[str, dict]] = []
    result = HermesCliExecutor().run(
        _ctx(tmp_path), lambda etype, data: emitted.append((etype, data))
    )

    # Envelope parse: output + session + tool-call count.
    assert result.output == "OK"
    assert result.session_id == "sess-123"
    assert result.tool_calls == 1

    # Exact pinned argv, stdin amendment, container-visible `--in`, verbatim -t.
    argv = (tmp_path / "argv.log").read_text().splitlines()
    assert argv[:6] == ["chat", "-Q", "--oneshot", "--query-file", "-", "--format"]
    assert argv[argv.index("-t") + 1] == "none"
    assert argv[argv.index("--max-turns") + 1] == "3"
    assert argv[argv.index("--run-budget") + 1] == "10"
    assert argv[argv.index("--in") + 1] == "/container/ws/f5-runs/adap"
    # Task text travels ONLY over stdin (never -q): byte-exact round trip.
    assert (tmp_path / "stdin.log").read_text() == _ctx(tmp_path).task_text
    assert "-q" not in argv and "--query-file" != "-q"
    assert not any(a.startswith("RESEARCH") for a in argv)  # no query in argv

    # Tool mapping (T080): one emission per real occurrence; identity keys are
    # the runner's — the adapter emits tool fields only.
    kinds = [etype for etype, _ in emitted]
    assert kinds == ["tool_started", "tool_completed"]
    start = emitted[0][1]
    assert start["tool_name"] == "terminal"
    assert "ls -la" in start["action"]
    end = emitted[1][1]
    assert end["status"] == "completed"
    assert end["exit_code"] == 0
    assert "file.txt" in end["summary"]

    # Host audit artifacts (contract rule 3): raw stream + stderr preserved.
    run_dir = tmp_path / "data" / "runs" / "adap"
    stream = (run_dir / "stream.jsonl").read_text()
    assert "sess-123" in stream
    assert "Warning: Unknown toolsets: none" in stream  # recorded, never surfaced
    assert (run_dir / "stderr.log").exists()
    # Container-visible mission dir created on the host bind side.
    assert (tmp_path / "ws-host" / "f5-runs" / "adap").is_dir()


def test_adapter_nonzero_exit_maps_to_tool_and_model_errors(
    fake_hermes, tmp_path, monkeypatch
) -> None:
    # Non-zero exit AFTER real tool activity -> AgentToolError (contract).
    monkeypatch.setenv("FAKE_EXIT", "3")
    with pytest.raises(AgentToolError) as excinfo:
        HermesCliExecutor().run(_ctx(tmp_path), lambda *_: None)
    assert "exited 3" in str(excinfo.value)

    # Non-zero exit with no tool activity -> AgentExitedError (model kind):
    # swap in a script that prints nothing but stderr and exits 5.
    empty = tmp_path / "bin" / "hermes"
    empty.write_text(
        "#!/bin/bash\nprintf '%s\\n' \"$@\" > \"$FAKE_ARGV_LOG\"\n"
        "cat > \"$FAKE_STDIN_LOG\"\necho 'boom' >&2\nexit 5\n"
    )
    empty.chmod(0o755)
    with pytest.raises(AgentExitedError) as excinfo2:
        HermesCliExecutor().run(_ctx(tmp_path), lambda *_: None)
    assert "exited 5" in str(excinfo2.value)
    assert "boom" in str(excinfo2.value)  # stderr excerpt carried as detail


def test_adapter_wall_timeout_kills_process(fake_hermes, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_SLEEP", "30")
    started = time.monotonic()
    with pytest.raises(AgentStepTimeout) as excinfo:
        HermesCliExecutor().run(_ctx(tmp_path, timeout=1), lambda *_: None)
    elapsed = time.monotonic() - started
    assert "timeout after 1s" in str(excinfo.value)
    assert elapsed < 8  # SIGTERM honored (SIGKILL fallback not needed)


def test_adapter_cancel_kills_process(fake_hermes, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_SLEEP", "30")
    cancel = threading.Event()
    executor = HermesCliExecutor(cancel)
    threading.Timer(0.3, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(AgentCancelled):
        executor.run(_ctx(tmp_path, timeout=30), lambda *_: None)
    assert time.monotonic() - started < 8  # stopped at the next 0.5s poll
