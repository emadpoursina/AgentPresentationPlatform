"""Canonical activity event model (PRD section 10).

Every event carries timestamp, mission_id, event type, and safe metadata.
Tool outputs and agent content are treated as untrusted data: stored as
plain JSON, never executed, rendered with textContent on the client.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

# PRD section 10 canonical list.
CANONICAL_EVENT_TYPES = [
    "mission_started",
    "poll_opened",
    "vote_recorded",
    "audience_decision_applied",
    "agent_started",
    "tool_started",
    "tool_completed",
    "agent_handoff",
    "agent_completed",
    "agent_failed",
    "mission_completed",
]

# F1 lifecycle extensions needed for an honest state machine:
# created/running/paused/completed/failed + reset must all be visible
# on the stream, and failure must be distinguishable from success
# (acceptance #9). These are additive; the 11 canonical types above
# remain the contract for F3/F5 agent+poll slices.
EXTENDED_EVENT_TYPES = [
    "mission_created",
    "mission_paused",
    "mission_resumed",
    "mission_failed",
    "mission_reset",
]

EVENT_TYPES = CANONICAL_EVENT_TYPES + EXTENDED_EVENT_TYPES


class ActivityEvent(BaseModel):
    """Single structured activity event published to the dashboard."""

    id: int = Field(ge=1, description="Monotonic sequence, used as SSE id / Last-Event-ID")
    type: str = Field(description="Event type, one of EVENT_TYPES")
    mission_id: str = Field(min_length=1, description="Owning mission identifier")
    timestamp: datetime = Field(description="UTC timestamp of emission")
    data: dict[str, Any] = Field(default_factory=dict, description="Safe metadata")

    @field_validator("type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        if v not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {v!r}")
        return v

    @field_validator("timestamp")
    @classmethod
    def _ensure_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v

    model_config = {"ser_json_timedeltas": "float"}


def utcnow() -> datetime:
    return datetime.now(UTC)
