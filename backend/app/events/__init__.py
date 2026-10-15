"""Activity event package (event names per scratch/prd.md section 10).

Canonical event types: mission_started, poll_opened, vote_recorded,
audience_decision_applied, agent_started, tool_started, tool_completed,
agent_handoff, agent_completed, agent_failed, mission_completed.

Streaming (SSE/WebSocket) wiring is implemented via feature cards.
"""

EVENT_TYPES = [
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
