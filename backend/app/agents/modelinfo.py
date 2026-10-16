"""Resolved-model capture + pre-flight pin guard (FR-011, SC-009).

Model strategy — recorded here as required by tasks.md T093:

- Verified pair: `muse-spark-1.3-contributor` @ `opencode-go`
  (`base_url https://opencode.ai/zen/go/v1`, `api_mode codex_responses`),
  resolved by Hermes at runtime — never inferred from config.yaml's static
  default.
- Pre-flight evidence: `.agent/pi/f5-preflight/2026-10-15T21-48-43-554Z_4af17e/report.json`
  (PRD §8 pre-flight PASSED: real API call + real tool round trip).
- Known caveat (FR-010): opencode-go is a subscription/paid tier, a documented
  deviation from PRD §8's "free-tier API first".
- Enforcement (FR-011): any mismatch between the resolved model and the pinned
  pair refuses start/retry with an instruction to re-run the PRD §8 pre-flight —
  no silent model switch, ever.

`resolve()` runs `hermes config get model` (a config read — zero model quota)
and raises `ModelPinError` on mismatch or when the value cannot be verified.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

PINNED_MODEL_DEFAULT = "muse-spark-1.3-contributor"
PINNED_MODEL_PROVIDER = "opencode-go"
PREFLIGHT_EVIDENCE = (
    ".agent/pi/f5-preflight/2026-10-15T21-48-43-554Z_4af17e/report.json"
)


class ModelPinError(RuntimeError):
    """Resolved model differs from the pre-flight-verified pair (or cannot be
    verified). Start/retry must be refused — never silently switched."""


@dataclass(frozen=True)
class ResolvedModel:
    default: str
    provider: str
    base_url: str = ""
    api_mode: str = ""

    @property
    def display(self) -> str:
        """`"{default} @ {provider} ({api_mode})"` — the format stored in
        `Mission.resolved_model` (data-model.md)."""
        return f"{self.default} @ {self.provider} ({self.api_mode or 'unknown'})"


def _load_model_config() -> dict[str, str]:
    """Run `hermes config get model` and parse its `key: value` lines."""
    proc = subprocess.run(
        ["hermes", "config", "get", "model"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:200]
        raise RuntimeError(f"`hermes config get model` failed ({proc.returncode}): {detail}")
    config: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip():
            config[key.strip()] = value.strip()
    return config


def resolve() -> ResolvedModel:
    """Resolve the effective model and enforce the pre-flight pin.

    Returns the pinned `ResolvedModel`; raises `ModelPinError` when the
    resolved pair differs from `muse-spark-1.3-contributor` @ `opencode-go`
    or when the value cannot be read at all (fail closed — refusing is the
    only honest behavior when the model cannot be verified)."""
    try:
        raw = _load_model_config()
    except Exception as exc:  # refusal path: never paper over a read failure
        raise ModelPinError(
            f"resolved model could not be verified ({exc}); "
            "re-run the PRD §8 pre-flight before use"
        ) from exc
    resolved = ResolvedModel(
        default=raw.get("default", ""),
        provider=raw.get("provider", ""),
        base_url=raw.get("base_url", ""),
        api_mode=raw.get("api_mode", ""),
    )
    if (
        resolved.default != PINNED_MODEL_DEFAULT
        or resolved.provider != PINNED_MODEL_PROVIDER
    ):
        raise ModelPinError(
            f"resolved model changed ({resolved.display}); "
            "re-run the PRD §8 pre-flight before use "
            f"(pin: {PINNED_MODEL_DEFAULT} @ {PINNED_MODEL_PROVIDER}; "
            f"evidence: {PREFLIGHT_EVIDENCE})"
        )
    return resolved
