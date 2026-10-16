"""F5 run limits (RunLimits): verbatim defaults + `F5_*` env overrides.

Defaults are pinned by `specs/004-agent-serial-workflow/data-model.md` and
tasks.md T061 — changing them requires updating those artifacts first.
`usage_cache_seconds` is fixed at 60 (no env override, per data-model.md).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RunLimits:
    """Per-step / per-run execution bounds and quota-gate thresholds."""

    step_timeout_seconds: int = 300  # F5_STEP_TIMEOUT_SECONDS (outer kill)
    run_budget_seconds: int = 240  # F5_RUN_BUDGET_SECONDS (hermes --run-budget)
    max_turns: int = 8  # F5_MAX_TURNS (hermes --max-turns, request cap)
    max_output_chars: int = 20000  # F5_MAX_OUTPUT_CHARS (handoff bound)
    quota_warn_threshold_pct: float = 50.0  # F5_QUOTA_WARN_THRESHOLD
    quota_block_threshold_pct: float = 35.0  # F5_QUOTA_BLOCK_THRESHOLD (FR-024)
    usage_cache_seconds: int = 60  # fixed (data-model.md): no env override

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> RunLimits:
        """Build limits from `F5_*` environment variables; invalid or absent
        values fall back to the pinned defaults."""
        env = os.environ if environ is None else environ
        return cls(
            step_timeout_seconds=_read(env, "F5_STEP_TIMEOUT_SECONDS", int, 300),
            run_budget_seconds=_read(env, "F5_RUN_BUDGET_SECONDS", int, 240),
            max_turns=_read(env, "F5_MAX_TURNS", int, 8),
            max_output_chars=_read(env, "F5_MAX_OUTPUT_CHARS", int, 20000),
            quota_warn_threshold_pct=_read(env, "F5_QUOTA_WARN_THRESHOLD", float, 50.0),
            quota_block_threshold_pct=_read(env, "F5_QUOTA_BLOCK_THRESHOLD", float, 35.0),
            usage_cache_seconds=60,
        )


def _read(env: Mapping[str, str], key: str, cast: type, default):
    raw = env.get(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return cast(str(raw).strip())
    except (TypeError, ValueError):
        return default
