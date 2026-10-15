"""Participant models (PRD 5.1, F2 join + presence).

Display names are untrusted audience input: validated server-side here
(Balanced-30 rule from clarify) and rendered as plain text by clients.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

DISPLAY_NAME_MAX_LENGTH = 30
DISPLAY_NAME_PATTERN = re.compile(r"^[\w \-_'.,]+$", re.UNICODE)
DISPLAY_NAME_HINT = "Display name must be 1-30 characters: letters, numbers, spaces, - _ ' . ,"

ParticipantStatus = Literal["connected", "left", "timed_out"]


def normalize_display_name(raw: str | None) -> str | None:
    """Trim and validate a display name; None stays None (anonymous).

    Raises ValueError with a non-technical message when invalid.
    """
    if raw is None:
        return None
    name = raw.strip()
    if not name:
        raise ValueError(DISPLAY_NAME_HINT)
    if len(name) > DISPLAY_NAME_MAX_LENGTH or DISPLAY_NAME_PATTERN.fullmatch(name) is None:
        raise ValueError(DISPLAY_NAME_HINT)
    return name


class Participant(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=DISPLAY_NAME_MAX_LENGTH)
    anonymous: bool = False
    status: ParticipantStatus = "connected"
    joined_at: datetime
    last_seen_at: datetime


class JoinRequest(BaseModel):
    display_name: str | None = None


class ParticipantView(BaseModel):
    """Roster entry served to presenters and participants (names only, no PII)."""

    id: str
    display_name: str | None = None
    anonymous: bool = False
    status: ParticipantStatus = "connected"
    joined_at: datetime


class RosterView(BaseModel):
    count: int = Field(ge=0)
    participants: list[ParticipantView] = Field(default_factory=list)


def utcnow() -> datetime:
    return datetime.now(UTC)
