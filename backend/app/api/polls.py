"""Poll/voting/decision routes (F3: open/current/vote/close/resolve).

Audience vote routes are callable by any joined participant (voter
identity = F2 participant id). Presenter routes (open, close, resolve)
require `X-Presenter-Token` only when `PLAYGROUND_PRESENTER_TOKEN` is set
(research section 7); otherwise same-trust open like F1/F2 routes.
All poll/vote strings render client-side via `textContent` only.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from backend.app.missions.controller import MissionNotFoundError, get_controller
from backend.app.polls.controller import (
    IneligibleChoiceError,
    InvalidVoteError,
    MissionNotActiveError,
    NotAwaitingResolveError,
    PollConflictError,
    PollNotFoundError,
    PollNotOpenError,
    VoterNotEligibleError,
    VoterNotFoundError,
    get_polls_controller,
)
from backend.app.polls.models import OpenPollRequest

router = APIRouter(prefix="/api/missions/{mission_id}/polls", tags=["polls"])


def _polls():
    return get_polls_controller()


def _require_presenter(request: Request) -> None:
    token = os.environ.get("PLAYGROUND_PRESENTER_TOKEN", "").strip()
    if not token:
        return
    if request.headers.get("x-presenter-token") != token:
        raise HTTPException(status_code=403, detail="presenter authorization required")


def _require_mission(mission_id: str) -> None:
    try:
        get_controller().get(mission_id)
    except MissionNotFoundError:
        raise HTTPException(status_code=404, detail="mission not found") from None


def _friendly_validation_error(exc: ValidationError) -> str:
    first = exc.errors()[0] if exc.errors() else None
    if first is None:
        return "invalid poll request"
    loc = ".".join(str(p) for p in first.get("loc", ()))
    msg = first.get("msg", "invalid value")
    # Strip Pydantic's "Value error, " prefix for non-technical messages.
    msg = msg.replace("Value error, ", "")
    return f"{loc}: {msg}" if loc else msg


async def _read_json(request: Request) -> dict:
    """Parse a JSON object body; raises HTTPException 400 when missing/malformed."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="request body must be valid JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object") from None
    return body


@router.post("", status_code=201)
async def open_poll(mission_id: str, request: Request) -> dict:
    _require_presenter(request)
    body = await _read_json(request)
    try:
        req = OpenPollRequest(**body)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=_friendly_validation_error(exc)) from None
    try:
        poll = _polls().open_poll(mission_id, req)
    except MissionNotFoundError:
        raise HTTPException(status_code=404, detail="mission not found") from None
    except MissionNotActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except PollConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return _polls().audience_view(poll)


@router.get("/current")
def current_poll(mission_id: str) -> dict:
    _require_mission(mission_id)
    poll = _polls().current(mission_id)
    return {"poll": _polls().audience_view(poll) if poll else None}


@router.post("/{poll_id}/vote")
async def vote(mission_id: str, poll_id: str, request: Request) -> dict:
    body = await _read_json(request)
    participant_id = body.get("participant_id")
    option_id = body.get("option_id")
    if participant_id is not None and not isinstance(participant_id, str):
        raise HTTPException(status_code=400, detail="participant_id must be a string")
    if option_id is not None and not isinstance(option_id, str):
        raise HTTPException(status_code=400, detail="option_id must be a string")
    try:
        poll, _ = _polls().vote(mission_id, poll_id, participant_id, option_id)
    except PollNotFoundError:
        raise HTTPException(status_code=404, detail="poll not found") from None
    except PollNotOpenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except VoterNotFoundError:
        raise HTTPException(status_code=404, detail="participant not found") from None
    except VoterNotEligibleError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except InvalidVoteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    counts = _polls().tally(poll)
    show_counts = poll.reveal_mode == "live" or poll.state == "completed"
    return {
        "poll_id": poll.id,
        "option_id": option_id,
        "tally": dict(counts) if show_counts else None,
        "total_votes": sum(counts.values()),
        "state": poll.state,
    }


@router.post("/{poll_id}/close")
def close_poll(mission_id: str, poll_id: str, request: Request) -> dict:
    _require_presenter(request)
    try:
        poll = _polls().close(mission_id, poll_id)
    except PollNotFoundError:
        raise HTTPException(status_code=404, detail="poll not found") from None
    except PollNotOpenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return _polls().audience_view(poll)


@router.post("/{poll_id}/resolve")
async def resolve_poll(mission_id: str, poll_id: str, request: Request) -> dict:
    _require_presenter(request)
    body = await _read_json(request)
    winning_option_id = body.get("winning_option_id")
    if winning_option_id is not None and not isinstance(winning_option_id, str):
        raise HTTPException(status_code=400, detail="winning_option_id must be a string")
    try:
        poll = _polls().resolve(mission_id, poll_id, winning_option_id)
    except PollNotFoundError:
        raise HTTPException(status_code=404, detail="poll not found") from None
    except NotAwaitingResolveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except IneligibleChoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _polls().audience_view(poll)
