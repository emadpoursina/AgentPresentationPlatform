"""F5 T061: agent profiles (least privilege, verbatim sections) + RunLimits.

Everything here is static/config-level: no subprocess, no model quota
(FR-023). Pins come from data-model.md and tasks.md T061 verbatim.
"""

import pytest

from backend.app.agents.profiles import (
    CRITIC,
    PROFILES,
    RESEARCHER,
    SUMMARIZER,
    AgentProfile,
    ProfileDefinitionError,
    get_profile,
    validate_profiles,
)
from backend.app.agents.settings import RunLimits

# -- AgentProfile definitions ------------------------------------------------


def test_exactly_three_profiles_with_pinned_ids() -> None:
    validate_profiles(PROFILES.values())  # must not raise
    assert set(PROFILES) == {"researcher", "critic", "summarizer"}
    assert len(PROFILES) == 3


def test_profile_ids_are_unique_even_when_duplicates_injected() -> None:
    with pytest.raises(ProfileDefinitionError):
        validate_profiles([RESEARCHER, RESEARCHER, CRITIC])


@pytest.mark.parametrize("count", [0, 1, 2, 4])
def test_profile_count_must_be_exactly_three(count: int) -> None:
    pool = [RESEARCHER, CRITIC, SUMMARIZER]
    with pytest.raises(ProfileDefinitionError):
        validate_profiles(pool[:count] if count <= 3 else pool + [RESEARCHER])


def test_terminal_toolset_appears_in_at_most_one_profile() -> None:
    terminal_owners = [p.id for p in PROFILES.values() if "terminal" in p.toolsets.split(",")]
    assert terminal_owners == ["researcher"]  # least-privilege pin (FR-022)

    # A second terminal-granting profile must be rejected by validation.
    rogue = AgentProfile(
        id="critic",
        title="Critic",
        instructions="...",
        toolsets="terminal",
        output_sections=CRITIC.output_sections,
    )
    with pytest.raises(ProfileDefinitionError):
        validate_profiles([RESEARCHER, rogue, SUMMARIZER])


def test_researcher_terminal_and_others_tool_free_sentinel() -> None:
    # `none` is the pinned tool-free literal behind the CLI `-t none` (T064).
    assert RESEARCHER.toolsets == "terminal"
    assert CRITIC.toolsets == "none"
    assert SUMMARIZER.toolsets == "none"


def test_output_sections_verbatim() -> None:
    assert RESEARCHER.output_sections == ["findings", "sources", "uncertainties", "handoff_note"]
    assert CRITIC.output_sections == ["issues", "evidence", "remaining_uncertainty", "review"]
    assert SUMMARIZER.output_sections == [
        "main_conclusion",
        "key_findings",
        "caveats",
        "what_agents_did",
    ]


def test_get_profile_returns_defined_profiles_and_rejects_unknown() -> None:
    for pid in ("researcher", "critic", "summarizer"):
        assert get_profile(pid).id == pid
    with pytest.raises(KeyError):
        get_profile("planner")


def test_profile_titles_and_instructions_present() -> None:
    for profile in PROFILES.values():
        assert profile.title
        assert profile.instructions.strip()
        assert profile.id in ("researcher", "critic", "summarizer")


# -- RunLimits defaults + env overrides (data-model.md) ----------------------


def test_run_limits_defaults_verbatim() -> None:
    limits = RunLimits()
    assert limits.step_timeout_seconds == 300
    assert limits.run_budget_seconds == 240
    assert limits.max_turns == 8
    assert limits.max_output_chars == 20000
    assert limits.quota_warn_threshold_pct == 50.0
    assert limits.quota_block_threshold_pct == 35.0
    assert limits.usage_cache_seconds == 60


def test_run_limits_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("F5_STEP_TIMEOUT_SECONDS", "42")
    monkeypatch.setenv("F5_RUN_BUDGET_SECONDS", "17")
    monkeypatch.setenv("F5_MAX_TURNS", "3")
    monkeypatch.setenv("F5_MAX_OUTPUT_CHARS", "1234")
    monkeypatch.setenv("F5_QUOTA_WARN_THRESHOLD", "55.5")
    monkeypatch.setenv("F5_QUOTA_BLOCK_THRESHOLD", "40.0")
    limits = RunLimits.from_env()
    assert limits.step_timeout_seconds == 42
    assert limits.run_budget_seconds == 17
    assert limits.max_turns == 3
    assert limits.max_output_chars == 1234
    assert limits.quota_warn_threshold_pct == 55.5
    assert limits.quota_block_threshold_pct == 40.0
    # usage_cache_seconds is fixed at 60 (data-model.md): no env override.
    assert limits.usage_cache_seconds == 60


def test_run_limits_invalid_env_falls_back_to_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("F5_MAX_TURNS", "not-a-number")
    assert RunLimits.from_env().max_turns == 8
