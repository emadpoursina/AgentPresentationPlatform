"""In-memory polls coordinator (F3).

Mirrors the F1/F2 pattern: dict-keyed state guarded by a lock, lazy
server-side deadline sweep on every read/write path (no threads), and
all transitions published to the shared event store. Server arrival time
is authoritative: a vote arriving after close is rejected.

Votes are keyed `(poll_id, participant_id) -> option_id`; resubmission
before close replaces the previous choice, and resubmitting the same
option is a 200 no-op with no new event (FR-006, FR-021).
"""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta

from backend.app.events.store import EventStore
from backend.app.events.store import event_store as _event_store

from .models import OpenPollRequest, Poll, PollOutcome, utcnow


class PollNotFoundError(KeyError):
    pass


class MissionNotActiveError(ValueError):
    def __init__(self, mission_id: str, status: str) -> None:
        super().__init__(f"cannot open a poll: mission {mission_id} is {status}")
        self.mission_id = mission_id


class PollConflictError(ValueError):
    def __init__(self, mission_id: str) -> None:
        super().__init__(f"mission {mission_id} already has an open poll")
        self.mission_id = mission_id


class PollNotOpenError(ValueError):
    def __init__(self, poll_id: str, state: str) -> None:
        super().__init__(f"poll {poll_id} is {state}; voting is stopped")
        self.poll_id = poll_id
        self.state = state


class VoterNotFoundError(KeyError):
    pass


class VoterNotEligibleError(ValueError):
    def __init__(self, participant_id: str) -> None:
        super().__init__("you must join before voting; please join and try again")
        self.participant_id = participant_id


class InvalidVoteError(ValueError):
    pass


class NotAwaitingResolveError(ValueError):
    def __init__(self, poll_id: str, state: str) -> None:
        super().__init__(f"poll {poll_id} is {state}; nothing to resolve")
        self.poll_id = poll_id
        self.state = state


class IneligibleChoiceError(ValueError):
    pass


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class PollsController:
    """Per-mission ephemeral polls; outcomes persist via the event log and
    `Mission.branch_context` (applied through `MissionController`)."""

    def __init__(self, store: EventStore) -> None:
        self._store = store
        self._lock = threading.Lock()
        self._polls: dict[str, Poll] = {}
        self._votes: dict[tuple[str, str], str] = {}

    # -- test/reset helpers ---------------------------------------------
    def clear(self, mission_id: str | None = None) -> None:
        with self._lock:
            if mission_id is None:
                self._polls.clear()
                self._votes.clear()
            else:
                for pid in [p for p, poll in self._polls.items() if poll.mission_id == mission_id]:
                    del self._polls[pid]
                # Drop votes whose poll is gone; keep other missions untouched.
                for key in [k for k in self._votes if k[0] not in self._polls]:
                    del self._votes[key]

    # -- queries ----------------------------------------------------------
    def get(self, poll_id: str) -> Poll:
        self.sweep()
        with self._lock:
            try:
                return self._polls[poll_id]
            except KeyError:
                raise PollNotFoundError(poll_id) from None

    def current(self, mission_id: str) -> Poll | None:
        self.sweep()
        with self._lock:
            for poll in self._polls.values():
                if poll.mission_id == mission_id and poll.state in ("open", "closing"):
                    return poll
        return None

    def tally(self, poll: Poll) -> dict[str, int]:
        counts = {opt.id: 0 for opt in poll.options}
        with self._lock:
            for (pid, _), option_id in self._votes.items():
                if pid == poll.id and option_id in counts:
                    counts[option_id] += 1
        return counts

    def total_votes(self, poll: Poll) -> int:
        return sum(self.tally(poll).values())

    def audience_view(self, poll: Poll) -> dict:
        """Audience-safe shape: no `branch_instruction`, per-option counts
        only for live polls or completed polls (FR-015, FR-017)."""
        counts = self.tally(poll)
        show_counts = poll.reveal_mode == "live" or poll.state == "completed"
        return {
            "id": poll.id,
            "mission_id": poll.mission_id,
            "question": poll.question,
            "options": [{"id": o.id, "label": o.label} for o in poll.options],
            "state": poll.state,
            "reveal_mode": poll.reveal_mode,
            "deadline_at": poll.deadline_at.isoformat(),
            "tally": dict(counts) if show_counts else None,
            "total_votes": sum(counts.values()),
            "outcome": (
                {
                    "winning_option_id": poll.outcome.winning_option_id,
                    "decided_by": poll.outcome.decided_by,
                }
                if poll.outcome
                else None
            ),
        }

    # -- lifecycle ----------------------------------------------------------
    def open_poll(self, mission_id: str, req: OpenPollRequest) -> Poll:
        from backend.app.missions.controller import MissionNotFoundError
        from backend.app.missions.controller import get_controller as get_missions

        try:
            mission = get_missions().get(mission_id)
        except MissionNotFoundError:
            raise MissionNotFoundError(mission_id) from None
        if mission.status.value != "running":
            raise MissionNotActiveError(mission_id, mission.status.value)
        self.sweep()
        if self.current(mission_id) is not None:
            raise PollConflictError(mission_id)
        now = utcnow()
        poll = Poll(
            id=_new_id(),
            mission_id=mission_id,
            question=req.question,
            options=list(req.options),
            deadline_at=now + timedelta(seconds=req.deadline_seconds),
            reveal_mode=req.reveal_mode,
            state="open",
            outcome=None,
            opened_at=now,
            closed_at=None,
        )
        with self._lock:
            self._polls[poll.id] = poll
        self._store.append(
            "poll_opened",
            mission_id,
            {
                "poll_id": poll.id,
                "question": poll.question,
                "options": [{"id": o.id, "label": o.label} for o in poll.options],
                "deadline_at": poll.deadline_at.isoformat(),
                "reveal_mode": poll.reveal_mode,
            },
        )
        return poll

    def vote(
        self, mission_id: str, poll_id: str, participant_id: str | None, option_id: str | None
    ) -> tuple[Poll, bool]:
        """Cast or change a vote. Returns (poll, changed); same-option
        resubmission returns changed=False with no new event."""
        from backend.app.participants.controller import (
            ParticipantNotFoundError,
            get_participants_controller,
        )

        poll = self._require_open(mission_id, poll_id)
        if not participant_id or not participant_id.strip():
            raise InvalidVoteError("vote needs a participant; please join and try again")
        if not option_id or not str(option_id).strip():
            raise InvalidVoteError("choose one of the listed options")
        try:
            participants = get_participants_controller()
            participants.sweep_timeouts()
            voter = participants.get(participant_id)
        except ParticipantNotFoundError:
            raise VoterNotFoundError(participant_id) from None
        if voter.status != "connected":
            raise VoterNotEligibleError(participant_id)
        option_ids = [o.id for o in poll.options]
        if option_id not in option_ids:
            raise InvalidVoteError("that option is not part of this poll")
        key = (poll.id, participant_id)
        with self._lock:
            if self._votes.get(key) == option_id:
                return poll, False
            self._votes[key] = option_id
        counts = self.tally(poll)
        payload: dict = {"poll_id": poll.id, "total": sum(counts.values())}
        if poll.reveal_mode == "live":
            payload["counts"] = counts
        self._store.append("vote_recorded", mission_id, payload)
        return poll, True

    def close(self, mission_id: str, poll_id: str) -> Poll:
        """Presenter early close. Takes effect immediately: outright winners
        complete at once, otherwise the poll awaits presenter resolution."""
        poll = self._require_known(mission_id, poll_id)
        if poll.state == "completed":
            raise PollNotOpenError(poll.id, poll.state)
        if poll.state == "closing":
            return poll
        return self._settle_open(poll)

    def resolve(self, mission_id: str, poll_id: str, winning_option_id: str | None) -> Poll:
        """Presenter tie-break / no-vote fallback. Only valid in `closing`."""
        poll = self._require_known(mission_id, poll_id)
        if poll.state != "closing":
            raise NotAwaitingResolveError(poll.id, poll.state)
        if not winning_option_id or not winning_option_id.strip():
            raise IneligibleChoiceError("choose one of the listed options")
        counts = self.tally(poll)
        total = sum(counts.values())
        option_ids = [o.id for o in poll.options]
        if winning_option_id not in option_ids:
            raise IneligibleChoiceError("that option is not part of this poll")
        if total == 0:
            decided_by = "presenter_fallback"
        else:
            top = max(counts.values())
            tied = [oid for oid, n in counts.items() if n == top]
            if winning_option_id not in tied:
                raise IneligibleChoiceError("tie-break must pick one of the tied options")
            decided_by = "presenter_tiebreak"
        return self._complete(poll, winning_option_id, decided_by)  # type: ignore[arg-type]

    # -- deadline sweep -------------------------------------------------------
    def sweep(self) -> None:
        """Roll expired `open` polls forward. Runs on every read/write path;
        server arrival time stays authoritative for close races."""
        now = utcnow()
        expired: list[Poll] = []
        with self._lock:
            for poll in self._polls.values():
                if poll.state == "open" and now >= poll.deadline_at:
                    expired.append(poll)
        for poll in expired:
            self._settle_open(poll)

    # -- internals ------------------------------------------------------------
    def _require_known(self, mission_id: str, poll_id: str) -> Poll:
        self.sweep()
        with self._lock:
            poll = self._polls.get(poll_id)
        if poll is None or poll.mission_id != mission_id:
            raise PollNotFoundError(poll_id)
        return poll

    def _require_open(self, mission_id: str, poll_id: str) -> Poll:
        poll = self._require_known(mission_id, poll_id)
        if poll.state != "open":
            raise PollNotOpenError(poll.id, poll.state)
        return poll

    def _settle_open(self, poll: Poll) -> Poll:
        """Stop voting on an open poll: outright winner completes at once,
        ties and zero-vote polls move to `closing` for presenter resolve."""
        counts = self.tally(poll)
        total = sum(counts.values())
        if total > 0:
            top = max(counts.values())
            leaders = [oid for oid, n in counts.items() if n == top]
            if len(leaders) == 1:
                return self._complete(poll, leaders[0], "tally")
        with self._lock:
            if poll.state == "open":
                poll.state = "closing"
                poll.closed_at = utcnow()
        self._store.append(
            "poll_closing",
            poll.mission_id,
            {
                "poll_id": poll.id,
                "total": total,
                "outcome_status": "awaiting_presenter",
                "tied_option_ids": (
                    [oid for oid, n in counts.items() if n == max(counts.values())]
                    if total > 0
                    else []
                ),
            },
        )
        return poll

    def _complete(self, poll: Poll, winning_option_id: str, decided_by: str) -> Poll:
        with self._lock:
            if poll.state == "completed":
                return poll
            poll.state = "completed"
            poll.closed_at = utcnow()
            poll.outcome = PollOutcome(
                winning_option_id=winning_option_id,
                decided_by=decided_by,  # type: ignore[arg-type]
                decided_at=utcnow(),
            )
        counts = self.tally(poll)
        self._store.append(
            "poll_closed",
            poll.mission_id,
            {
                "poll_id": poll.id,
                "final_counts": counts,
                "total": sum(counts.values()),
                "outcome_status": "completed",
                "winning_option_id": winning_option_id,
                "decided_by": decided_by,
            },
        )
        branch_map = {o.id: o.branch_instruction for o in poll.options}
        from backend.app.missions.controller import get_controller as get_missions

        get_missions().apply_decision(
            poll.mission_id, poll.id, winning_option_id, branch_map, decided_by
        )
        return poll


controller = PollsController(_event_store)


def get_polls_controller() -> PollsController:
    return controller
