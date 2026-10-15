"""Participant presence package. Session-scoped roster only (see scratch/prd.md section 5.1)."""

from .controller import (
    PARTICIPANT_TIMEOUT_SECONDS,
    SESSION_SCOPE,
    ParticipantGoneError,
    ParticipantNotFoundError,
    ParticipantsController,
    controller,
    get_participants_controller,
)
from .models import (
    DISPLAY_NAME_HINT,
    DISPLAY_NAME_MAX_LENGTH,
    JoinRequest,
    Participant,
    ParticipantView,
    RosterView,
    normalize_display_name,
)

__all__ = [
    "DISPLAY_NAME_HINT",
    "DISPLAY_NAME_MAX_LENGTH",
    "SESSION_SCOPE",
    "PARTICIPANT_TIMEOUT_SECONDS",
    "JoinRequest",
    "Participant",
    "ParticipantGoneError",
    "ParticipantNotFoundError",
    "ParticipantView",
    "ParticipantsController",
    "RosterView",
    "controller",
    "get_participants_controller",
    "normalize_display_name",
]
