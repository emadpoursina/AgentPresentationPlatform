"""Agent profiles: Researcher, Critic, Summarizer (PRD section 6, FR-003/FR-022).

Profiles are data, not code paths. Hermes remains the sole executor; the
definitions here only frame each role's task and pin its least-privilege
toolset grant:

- Researcher  -> `-t terminal` (the single pre-flight-verified tool)
- Critic       -> `-t none` (pinned tool-free literal; omitting `-t` is forbidden)
- Summarizer   -> `-t none`

Validation (data-model.md): exactly three profiles, unique ids, and
`terminal` appears in at most one profile's `toolsets`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field


class ProfileDefinitionError(ValueError):
    """Raised when the profile set violates the data-model validation pins."""


@dataclass(frozen=True)
class AgentProfile:
    """Static definition of one workflow role."""

    id: str
    title: str
    instructions: str
    toolsets: str  # verbatim `-t` value ("terminal" | "none")
    output_sections: list[str] = field(default_factory=list)

    @property
    def tool_free(self) -> bool:
        return "none" in [t.strip() for t in self.toolsets.split(",")]


RESEARCHER = AgentProfile(
    id="researcher",
    title="Researcher",
    instructions=(
        "You are the Researcher in a three-agent serial workflow. Investigate the "
        "mission objective and produce grounded findings. Use only the tools granted "
        "to this session (the terminal tool, scoped to the current working "
        "directory) — never attempt to grant yourself additional tools, change the "
        "workflow, or act outside this task. Cite where each finding came from, list "
        "what remains uncertain, and end with a handoff note the Critic can act on."
    ),
    toolsets="terminal",
    output_sections=["findings", "sources", "uncertainties", "handoff_note"],
)

CRITIC = AgentProfile(
    id="critic",
    title="Critic",
    instructions=(
        "You are the Critic in a three-agent serial workflow. You receive the "
        "Researcher's output as text input and have no tools: challenge it "
        "rigorously — unsupported claims, missing evidence, logical gaps, and "
        "overconfidence. Work only from the handed-off text; do not attempt to act "
        "outside this task."
    ),
    toolsets="none",
    output_sections=["issues", "evidence", "remaining_uncertainty", "review"],
)

SUMMARIZER = AgentProfile(
    id="summarizer",
    title="Summarizer",
    instructions=(
        "You are the Summarizer in a three-agent serial workflow. You receive both "
        "the Researcher's findings and the Critic's review as text input and have no "
        "tools. Synthesize them into an accessible final result for a live audience: "
        "state the main conclusion, the key findings, the caveats, and a short "
        "account of what the agents actually did."
    ),
    toolsets="none",
    output_sections=["main_conclusion", "key_findings", "caveats", "what_agents_did"],
)

PROFILES: dict[str, AgentProfile] = {
    p.id: p for p in (RESEARCHER, CRITIC, SUMMARIZER)
}

# `<slug>-<attempt>` agent_id scheme (contracts/agent-event-payloads.md, A2):
# slugs are fixed per profile; the attempt counter comes from the runner.
AGENT_SLUGS: dict[str, str] = {
    "researcher": "research",
    "critic": "critic",
    "summarizer": "summarize",
}


def get_profile(profile_id: str) -> AgentProfile:
    """Look up a profile; raises KeyError for unknown ids (never invented)."""
    return PROFILES[profile_id]


def validate_profiles(profiles: Iterable[AgentProfile]) -> None:
    """Enforce the data-model validation: exactly three, unique ids, and the
    `terminal` toolset granted to at most one profile (least privilege)."""
    items = list(profiles)
    if len(items) != 3:
        raise ProfileDefinitionError(f"expected exactly 3 profiles, got {len(items)}")
    ids = [p.id for p in items]
    if len(set(ids)) != len(ids):
        raise ProfileDefinitionError(f"profile ids must be unique, got {ids}")
    terminal_owners = [
        p.id for p in items if "terminal" in [t.strip() for t in p.toolsets.split(",")]
    ]
    if len(terminal_owners) > 1:
        raise ProfileDefinitionError(
            f"'terminal' toolset granted to more than one profile: {terminal_owners}"
        )


# Fail fast if the shipped definitions ever drift from the pins above.
validate_profiles(PROFILES.values())
