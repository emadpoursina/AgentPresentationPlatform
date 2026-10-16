"""Mission state-machine models (PRD 4C, 5.3, 6 workflow requirements).

F1 is the thin coordinator only: predefined bounded missions, explicit
status transitions, no agent execution (Hermes owns that in F5) and no
polls (F3). Progress is derived from workflow position, never fabricated.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backend.app.polls.models import AudienceDecision


class BranchContext(BaseModel):
    """Applied audience decisions (F3). Outcomes persist here and in the
    event log; `current_branch_instruction` holds the winning option's
    next-step task text, read by Hermes at execution time (F5)."""

    applied_decisions: list[AudienceDecision] = Field(default_factory=list)
    current_branch_instruction: str | None = Field(default=None, max_length=2000)


class MissionStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL_STATUSES = {MissionStatus.COMPLETED, MissionStatus.FAILED}


class MissionStep(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    agent_profile: str = Field(default="", max_length=64)


DEFAULT_STEPS = [
    MissionStep(
        id="research",
        title="Research",
        description="Researcher gathers evidence on the mission topic.",
        agent_profile="researcher",
    ),
    MissionStep(
        id="critique",
        title="Critique",
        description="Critic challenges findings and identifies uncertainty.",
        agent_profile="critic",
    ),
    MissionStep(
        id="summarize",
        title="Summarize",
        description="Summarizer produces the accessible final result.",
        agent_profile="summarizer",
    ),
]


def default_steps() -> list[MissionStep]:
    return [s.model_copy(deep=True) for s in DEFAULT_STEPS]


class AgentRunRecord(BaseModel):
    """One executed (or aborted) agent step, preserved across failure and
    retry (F5, data-model.md). Additive: F1 consumers ignore these fields."""

    step_id: str = Field(min_length=1, max_length=64)
    profile: str = Field(min_length=1, max_length=64)
    agent_id: str = Field(min_length=1, max_length=64)
    task_input: str = Field(default="", description="Exact composed task text handed to Hermes")
    output: str = Field(default="", max_length=20000, description="Bounded raw agent output")
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    error: str | None = Field(default=None, max_length=2000)
    tool_calls: int = Field(default=0, ge=0)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    session_id: str | None = Field(default=None, max_length=128)


class Mission(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    status: MissionStatus = MissionStatus.CREATED
    steps: list[MissionStep] = Field(default_factory=default_steps)
    current_step_index: int = Field(default=0, ge=0)
    result_summary: str | None = Field(default=None, max_length=5000)
    outcome: Literal["success", "partial", "failed"] | None = None
    error: str | None = Field(default=None, max_length=2000)
    branch_context: BranchContext = Field(default_factory=BranchContext)
    created_at: datetime
    updated_at: datetime

    # F5 additions — all default-valued so F1–F4 tests and consumers stay valid.
    objective: str | None = Field(default=None, max_length=500)
    agent_runs: list[AgentRunRecord] = Field(default_factory=list)
    failed_step_id: str | None = Field(default=None, max_length=64)
    retry_count: int = Field(default=0, ge=0)
    resolved_model: str | None = Field(default=None, max_length=200)
    quota_note: str | None = Field(default=None, max_length=500)

    @property
    def current_step(self) -> MissionStep | None:
        if not self.steps:
            return None
        idx = min(self.current_step_index, len(self.steps) - 1)
        return self.steps[idx]

    @property
    def progress(self) -> float:
        """Honest progress: workflow position only, no simulated activity."""
        if self.status in TERMINAL_STATUSES:
            return 1.0
        if not self.steps:
            return 0.0
        return min(1.0, max(0.0, self.current_step_index / len(self.steps)))


class CreateMissionRequest(BaseModel):
    title: str = Field(default="Investigate AI agents", min_length=1, max_length=120)
    steps: list[MissionStep] | None = None

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be blank")
        return v


class CompleteMissionRequest(BaseModel):
    summary: str = Field(default="", max_length=5000)
    outcome: Literal["success", "partial"] = "success"

    @field_validator("summary")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class FailMissionRequest(BaseModel):
    error: str = Field(default="Mission failed", min_length=1, max_length=2000)

    @field_validator("error")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("error must not be blank")
        return v


def utcnow() -> datetime:
    return datetime.now(UTC)
