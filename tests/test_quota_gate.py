"""F5 T062 (quota gate) + T093 (model pin refusal) + preflight wiring.

All `hermes` invocations are stubbed at the loader seam: the default
gate run spends zero quota and makes zero subprocess calls (FR-023).
"""

import pytest

from backend.app.agents import modelinfo, quota
from backend.app.agents.modelinfo import ModelPinError, ResolvedModel
from backend.app.agents.runner import LowQuotaError, run_preflight
from backend.app.agents.settings import RunLimits

PINNED_CONFIG = {
    "default": "muse-spark-1.3-contributor",
    "provider": "opencode-go",
    "base_url": "https://opencode.ai/zen/go/v1",
    "api_mode": "codex_responses",
}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch):
    quota.clear_cache()
    yield
    quota.clear_cache()


def _usage(monthly_used: float | None = 68.0, **extra) -> dict:
    payload: dict = {"provider": "opencode-go", "source": "go_usage_api"}
    if monthly_used is not None:
        payload["windows"] = [
            {
                "label": "Monthly",
                "used_percent": monthly_used,
                "resets_at": "2026-10-22T22:09:20+00:00",
                "detail": None,
            }
        ]
    payload.update(extra)
    return payload


def _stub_usage(monkeypatch: pytest.MonkeyPatch, payload: dict | None) -> list:
    calls: list = []

    def _load() -> dict | None:
        calls.append(1)
        return payload

    monkeypatch.setattr(quota, "_load_usage", _load)
    return calls


# -- T062: quota gate --------------------------------------------------------


def test_block_start_below_threshold_without_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_usage(monkeypatch, _usage(monthly_used=70.0))  # 30% remaining < 35%
    decision = quota.check(False)
    assert decision.allowed is False
    assert decision.needs_confirmation is True
    assert decision.remaining_pct == pytest.approx(30.0)
    assert decision.note == (
        "monthly quota below threshold (30% remaining); pass confirm_low_quota to proceed"
    )


def test_allow_below_threshold_with_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_usage(monkeypatch, _usage(monthly_used=70.0))
    decision = quota.check(True)
    assert decision.allowed is True
    assert decision.needs_confirmation is True  # still surfaced honestly
    assert decision.remaining_pct == pytest.approx(30.0)


def test_warn_below_50_but_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_usage(monkeypatch, _usage(monthly_used=60.0))  # 40% remaining: warn band
    decision = quota.check(False)
    assert decision.allowed is True
    assert decision.needs_confirmation is False
    assert "low" in decision.note
    assert "40" in decision.note


def test_healthy_quota_has_no_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_usage(monkeypatch, _usage(monthly_used=10.0))  # 90% remaining
    decision = quota.check(False)
    assert decision.allowed is True
    assert "low" not in decision.note
    assert "90" in decision.note


def test_unavailable_fails_open_with_quota_unknown_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_usage(monkeypatch, None)  # `hermes usage` failed entirely
    decision = quota.check(False)
    assert decision.allowed is True  # fail-open (research.md §7)
    assert decision.available is False
    assert decision.remaining_pct is None
    assert "quota unknown" in decision.note
    assert calls  # a fetch was genuinely attempted

    quota.clear_cache()
    _stub_usage(monkeypatch, _usage(monthly_used=None, unavailable_reason="no credential"))
    decision = quota.check(False)
    assert decision.allowed is True
    assert decision.available is False
    assert "quota unknown" in decision.note


def test_usage_result_cached_60_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_usage(monkeypatch, _usage(monthly_used=68.0))
    now = {"t": 1000.0}
    monkeypatch.setattr(quota, "_monotonic", lambda: now["t"])

    quota.check(False)
    quota.check(False)
    assert len(calls) == 1  # second call served from cache

    now["t"] = 1061.0  # past the 60s cache window
    quota.check(False)
    assert len(calls) == 2


def test_env_threshold_overrides_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("F5_QUOTA_BLOCK_THRESHOLD", "45.0")
    _stub_usage(monkeypatch, _usage(monthly_used=60.0))  # 40% remaining
    decision = quota.check(False)
    assert decision.allowed is False  # 40 < 45 (env-raised threshold)


# -- T093: resolved-model pin refusal ---------------------------------------


def test_model_pin_passes_for_pre_flight_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(modelinfo, "_load_model_config", lambda: dict(PINNED_CONFIG))
    resolved = modelinfo.resolve()
    assert resolved == ResolvedModel(**PINNED_CONFIG)
    assert resolved.display == "muse-spark-1.3-contributor @ opencode-go (codex_responses)"


def test_model_pin_mismatch_refuses_with_pre_flight_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed = dict(PINNED_CONFIG, provider="anthropic", default="anthropic/claude-opus-4.6")
    monkeypatch.setattr(modelinfo, "_load_model_config", lambda: changed)
    with pytest.raises(ModelPinError) as excinfo:
        modelinfo.resolve()
    message = str(excinfo.value)
    assert "resolved model changed" in message
    assert "re-run the PRD §8 pre-flight" in message


def test_model_config_unavailable_also_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> dict:
        raise RuntimeError("hermes config get failed")

    monkeypatch.setattr(modelinfo, "_load_model_config", _boom)
    with pytest.raises(ModelPinError) as excinfo:
        modelinfo.resolve()
    assert "re-run the PRD §8 pre-flight" in str(excinfo.value)


# -- run_preflight wiring (used by both the endpoint and the CLI) ------------


def test_run_preflight_returns_resolved_model_and_quota_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(modelinfo, "_load_model_config", lambda: dict(PINNED_CONFIG))
    _stub_usage(monkeypatch, _usage(monthly_used=68.0))  # 32% remaining -> confirm
    resolved, note = run_preflight(confirm_low_quota=True)
    assert resolved == "muse-spark-1.3-contributor @ opencode-go (codex_responses)"
    assert note is not None and "32" in note


def test_run_preflight_blocks_on_low_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(modelinfo, "_load_model_config", lambda: dict(PINNED_CONFIG))
    _stub_usage(monkeypatch, _usage(monthly_used=70.0))
    with pytest.raises(LowQuotaError) as excinfo:
        run_preflight(confirm_low_quota=False)
    assert "confirm_low_quota" in str(excinfo.value)


def test_run_preflight_refuses_on_model_change(monkeypatch: pytest.MonkeyPatch) -> None:
    changed = dict(PINNED_CONFIG, default="someone-else")
    monkeypatch.setattr(modelinfo, "_load_model_config", lambda: changed)
    _stub_usage(monkeypatch, _usage(monthly_used=10.0))
    with pytest.raises(ModelPinError):
        run_preflight(confirm_low_quota=False)


def test_run_preflight_reads_env_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(modelinfo, "_load_model_config", lambda: dict(PINNED_CONFIG))
    _stub_usage(monkeypatch, _usage(monthly_used=60.0))  # 40% remaining
    limits = RunLimits(quota_block_threshold_pct=45.0)
    with pytest.raises(LowQuotaError):
        run_preflight(confirm_low_quota=False, limits=limits)
