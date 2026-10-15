"""Activity event package (event names per scratch/prd.md section 10).

Canonical event types: mission_started, poll_opened, vote_recorded,
audience_decision_applied, agent_started, tool_started, tool_completed,
agent_handoff, agent_completed, agent_failed, mission_completed.

F1 adds lifecycle extensions (mission_created, mission_paused,
mission_resumed, mission_failed, mission_reset) so the
created → running → paused → completed/failed + reset state machine is
fully visible and failure is never rendered as success.

F2 adds presence extensions (participant_joined, participant_left), one
real event per actual join/leave transition, scoped to mission_id
"session".
"""

from .models import (
    CANONICAL_EVENT_TYPES,
    EVENT_TYPES,
    EXTENDED_EVENT_TYPES,
    POLL_EVENT_TYPES,
    PRESENCE_EVENT_TYPES,
    ActivityEvent,
    utcnow,
)
from .store import EventStore, event_store

__all__ = [
    "ActivityEvent",
    "CANONICAL_EVENT_TYPES",
    "EVENT_TYPES",
    "EXTENDED_EVENT_TYPES",
    "POLL_EVENT_TYPES",
    "PRESENCE_EVENT_TYPES",
    "EventStore",
    "event_store",
    "utcnow",
]
