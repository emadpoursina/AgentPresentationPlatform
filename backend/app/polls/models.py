"""Poll/voting/decision models (F3, spec 002).

Polls are per-mission ephemeral state: one question with 2-6 predefined
options, a fixed reveal mode, and an `open -> closing -> completed` state
machine. Votes are a keyed map `(poll_id, participant_id) -> option_id`
(see controller); the counted state here is the option list plus outcome.
All poll content is untrusted and rendered as plain text by clients.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

PollState = Literal["open", "closing", "completed"]
RevealMode = Literal["live", "controlled"]
DecidedBy = Literal["tally", "presenter_tiebreak", "presenter_fallback"]

QUESTION_MAX_LENGTH = 200
OPTIONS_MIN = 2
OPTIONS_MAX = 6
LABEL_MAX_LENGTH = 80
OPTION_ID_MAX_LENGTH = 32
DEADLINE_DEFAULT_SECONDS = 60
DEADLINE_MIN_SECONDS = 10
DEADLINE_MAX_SECONDS = 600


def utcnow() -> datetime:
    return datetime.now(UTC)


class PollOption(BaseModel):
    """One predefined option. `branch_instruction` is the per-option
    next-step task text applied to the mission if this option wins."""

    id: str = Field(min_length=1, max_length=OPTION_ID_MAX_LENGTH)
    label: str = Field(min_length=1, max_length=LABEL_MAX_LENGTH)
    branch_instruction: str = Field(default="", max_length=2000)


class PollOutcome(BaseModel):
    winning_option_id: str = Field(min_length=1)
    decided_by: DecidedBy
    decided_at: datetime


class AudienceDecision(BaseModel):
    """Recorded outcome stored in `Mission.branch_context` (T022)."""

    poll_id: str = Field(min_length=1)
    mission_id: str = Field(min_length=1)
    winning_option_id: str = Field(min_length=1)
    decided_by: DecidedBy
    applied_at: datetime


class Poll(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    mission_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=QUESTION_MAX_LENGTH)
    options: list[PollOption] = Field(min_length=OPTIONS_MIN, max_length=OPTIONS_MAX)
    deadline_at: datetime
    reveal_mode: RevealMode = "live"
    state: PollState = "open"
    outcome: PollOutcome | None = None
    opened_at: datetime
    closed_at: datetime | None = None

    @field_validator("question")
    @classmethod
    def _strip_question(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question must not be blank")
        return v


class OpenPollRequest(BaseModel):
    question: str = Field(min_length=1, max_length=QUESTION_MAX_LENGTH)
    options: list[PollOption] = Field(min_length=OPTIONS_MIN, max_length=OPTIONS_MAX)
    deadline_seconds: int = Field(default=DEADLINE_DEFAULT_SECONDS)
    reveal_mode: RevealMode = "live"

    @field_validator("question")
    @classmethod
    def _strip_question(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question must not be blank")
        return v

    @field_validator("options")
    @classmethod
    def _unique_option_ids(cls, v: list[PollOption]) -> list[PollOption]:
        ids = [o.id.strip() for o in v]
        if any(not i for i in ids):
            raise ValueError("option ids must not be blank")
        if len(set(ids)) != len(ids):
            raise ValueError("option ids must be unique")
        for opt in v:
            opt.id = opt.id.strip()
            opt.label = opt.label.strip()
            if not opt.label:
                raise ValueError("option labels must not be blank")
        return v

    @field_validator("deadline_seconds")
    @classmethod
    def _bound_deadline(cls, v: int) -> int:
        if not (DEADLINE_MIN_SECONDS <= v <= DEADLINE_MAX_SECONDS):
            raise ValueError(
                f"deadline_seconds must be {DEADLINE_MIN_SECONDS}-{DEADLINE_MAX_SECONDS}"
            )
        return v


class VoteRequest(BaseModel):
    """Lenient shape so malformed payloads become 400 with a clear
    message (handled in the route), not bare 422s."""

    participant_id: str | None = None
    option_id: str | None = None


class ResolveRequest(BaseModel):
    winning_option_id: str | None = None
