"""Quota gate (FR-024 / SC-011, research.md §7): `hermes usage --json`.

- Monthly window remaining drives the gate: start/retry is **blocked** below
  `quota_block_threshold_pct` (default 35%) unless the request carries an
  explicit operator confirmation; a visible warning is attached below
  `quota_warn_threshold_pct` (default 50%).
- Results are cached for `RunLimits.usage_cache_seconds` (fixed 60s) so the
  CLI/API never spams the usage command.
- **Fail-open** when usage cannot be fetched: start proceeds with a visible
  "quota unknown" note (documented trade-off, research.md §7).
- Zero model quota: `hermes usage` is a metering read, never a model call —
  and unit tests stub `_load_usage` entirely (FR-023).
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass

from backend.app.agents.settings import RunLimits


class LowQuotaError(RuntimeError):
    """Monthly remaining below the block threshold without confirmation."""


@dataclass(frozen=True)
class QuotaSnapshot:
    """Ephemeral cached parse of `hermes usage --json` (data-model.md)."""

    fetched_at: float
    monthly_remaining_pct: float | None
    monthly_used_pct: str  # raw `used_percent` as reported
    raw: dict
    available: bool


@dataclass(frozen=True)
class QuotaDecision:
    """Result of `check()`: gate outcome + honest operator-facing note."""

    allowed: bool
    needs_confirmation: bool
    remaining_pct: float | None
    note: str
    available: bool = True


_cache_lock = threading.Lock()
_cache: QuotaSnapshot | None = None


def _monotonic() -> float:
    return time.monotonic()


def _load_usage() -> dict | None:
    """Run `hermes usage --json`; returns None on any failure (fail-open path)."""
    try:
        proc = subprocess.run(
            ["hermes", "usage", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            return None
        payload = json.loads(proc.stdout)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _snapshot(payload: dict | None, fetched_at: float) -> QuotaSnapshot:
    if not isinstance(payload, dict):
        return QuotaSnapshot(fetched_at, None, "", {}, False)
    windows = payload.get("windows") or []
    monthly = next(
        (w for w in windows if str(w.get("label", "")).strip().lower() == "monthly"),
        None,
    )
    if monthly is None or payload.get("unavailable_reason"):
        return QuotaSnapshot(fetched_at, None, "", payload, False)
    used = monthly.get("used_percent")
    if not isinstance(used, (int, float)):
        return QuotaSnapshot(fetched_at, None, str(used), payload, False)
    remaining = round(100.0 - float(used), 1)
    return QuotaSnapshot(fetched_at, remaining, str(used), payload, True)


def clear_cache() -> None:
    """Drop the cached snapshot (tests / forced refresh)."""
    global _cache
    with _cache_lock:
        _cache = None


def check(overrides_confirm: bool = False, *, limits: RunLimits | None = None) -> QuotaDecision:
    """Evaluate the quota gate (research.md §7).

    `overrides_confirm=True` plays the operator's `confirm_low_quota` flag:
    the block is lifted but the low-quota condition stays visible in `note`
    and `needs_confirmation`."""
    limits = limits or RunLimits.from_env()
    now = _monotonic()
    global _cache
    with _cache_lock:
        snap = _cache
        if snap is None or now - snap.fetched_at >= limits.usage_cache_seconds:
            snap = _snapshot(_load_usage(), now)
            _cache = snap

    if not snap.available or snap.monthly_remaining_pct is None:
        # Fail-open with a visible warning (research.md §7).
        return QuotaDecision(
            allowed=True,
            needs_confirmation=False,
            remaining_pct=None,
            note="quota unknown: usage unavailable — proceeding with a visible warning",
            available=False,
        )

    remaining = snap.monthly_remaining_pct
    if remaining < limits.quota_block_threshold_pct:
        if not overrides_confirm:
            return QuotaDecision(
                allowed=False,
                needs_confirmation=True,
                remaining_pct=remaining,
                note=(
                    f"monthly quota below threshold ({remaining:g}% remaining); "
                    "pass confirm_low_quota to proceed"
                ),
            )
        return QuotaDecision(
            allowed=True,
            needs_confirmation=True,
            remaining_pct=remaining,
            note=f"monthly quota low: {remaining:g}% remaining (operator confirmed)",
        )
    if remaining < limits.quota_warn_threshold_pct:
        return QuotaDecision(
            allowed=True,
            needs_confirmation=False,
            remaining_pct=remaining,
            note=(
                f"monthly quota low: {remaining:g}% remaining "
                f"(warn threshold {limits.quota_warn_threshold_pct:g}%)"
            ),
        )
    return QuotaDecision(
        allowed=True,
        needs_confirmation=False,
        remaining_pct=remaining,
        note=f"monthly quota: {remaining:g}% remaining",
    )
