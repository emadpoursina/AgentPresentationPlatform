"""Mission lifecycle routes (F1: start/pause/resume/complete/fail/reset)."""

from fastapi import APIRouter, HTTPException

from backend.app.missions.controller import (
    InvalidTransitionError,
    MissionNotFoundError,
    get_controller,
)
from backend.app.missions.models import (
    CompleteMissionRequest,
    CreateMissionRequest,
    FailMissionRequest,
    Mission,
)

router = APIRouter(prefix="/api/missions", tags=["missions"])


def _ctrl():
    return get_controller()


@router.post("", response_model=Mission, status_code=201)
def create_mission(req: CreateMissionRequest) -> Mission:
    return _ctrl().create(req)


@router.get("", response_model=list[Mission])
def list_missions() -> list[Mission]:
    return _ctrl().list()


@router.get("/{mission_id}", response_model=Mission)
def get_mission(mission_id: str) -> Mission:
    try:
        return _ctrl().get(mission_id)
    except MissionNotFoundError:
        raise HTTPException(status_code=404, detail="mission not found") from None


def _action(mission_id: str, action: str) -> Mission:
    try:
        c = _ctrl()
        if action == "start":
            return c.start(mission_id)
        if action == "pause":
            return c.pause(mission_id)
        if action == "resume":
            return c.resume(mission_id)
        if action == "reset":
            return c.reset(mission_id)
        raise HTTPException(status_code=404, detail="unknown action")
    except MissionNotFoundError:
        raise HTTPException(status_code=404, detail="mission not found") from None
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/{mission_id}/start", response_model=Mission)
def start_mission(mission_id: str) -> Mission:
    return _action(mission_id, "start")


@router.post("/{mission_id}/pause", response_model=Mission)
def pause_mission(mission_id: str) -> Mission:
    return _action(mission_id, "pause")


@router.post("/{mission_id}/resume", response_model=Mission)
def resume_mission(mission_id: str) -> Mission:
    return _action(mission_id, "resume")


@router.post("/{mission_id}/complete", response_model=Mission)
def complete_mission(mission_id: str, req: CompleteMissionRequest) -> Mission:
    try:
        return _ctrl().complete(mission_id, req)
    except MissionNotFoundError:
        raise HTTPException(status_code=404, detail="mission not found") from None
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/{mission_id}/fail", response_model=Mission)
def fail_mission(mission_id: str, req: FailMissionRequest) -> Mission:
    try:
        return _ctrl().fail(mission_id, req)
    except MissionNotFoundError:
        raise HTTPException(status_code=404, detail="mission not found") from None
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/{mission_id}/reset", response_model=Mission)
def reset_mission(mission_id: str) -> Mission:
    return _action(mission_id, "reset")
