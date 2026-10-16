"""Mission lifecycle routes (F1: start/pause/resume/complete/fail/reset)
plus the F5 run/retry endpoints (contracts/workflow-api.md)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.agents import runner as runner_mod
from backend.app.agents.runner import (
    LowQuotaError,
    ModelPinError,
    run_preflight,
)
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
    MissionStatus,
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
    # F5 reset wiring (T090): cancel in-flight execution FIRST so the runner
    # aborts at its next 0.5s poll (kills the subprocess — no orphan), then
    # the existing F1 reset transition, then clear F5 run-scoped fields.
    active = runner_mod.get_active(mission_id)
    if active is not None:
        active.cancel_event.set()
    _action(mission_id, "reset")  # F1 transition (404/409 propagate unchanged)
    _ctrl().clear_run_state(mission_id)
    return _ctrl().get(mission_id)


# -- F5: serial workflow entry points (contracts/workflow-api.md) ------------


class RunMissionRequest(BaseModel):
    objective: str | None = Field(
        default=None, max_length=500,
        description="Operator topic override (≤500 chars)",
    )
    confirm_low_quota: bool = False


class RetryMissionRequest(BaseModel):
    confirm_low_quota: bool = False


def _reject_concurrent(mission_id: str) -> None:
    """Distinct 409s: this mission executing / any other mission executing."""
    active = runner_mod.get_active(mission_id)
    if active is not None and active.alive:
        raise HTTPException(status_code=409, detail="mission is already executing")
    for run in runner_mod.active_runs():
        if run.mission_id != mission_id and run.alive:
            raise HTTPException(
                status_code=409, detail="another mission is already running"
            )


def _preflight(confirm_low_quota: bool) -> tuple[str, str | None]:
    """Model pin → quota gate, in contract order; both failures are 409."""
    try:
        return run_preflight(confirm_low_quota=confirm_low_quota)
    except ModelPinError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except LowQuotaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/{mission_id}/run", response_model=Mission, status_code=202)
def run_mission(mission_id: str, req: RunMissionRequest | None = None) -> Mission:
    req = req or RunMissionRequest()
    ctrl = _ctrl()
    try:
        mission = ctrl.get(mission_id)
    except MissionNotFoundError:
        raise HTTPException(status_code=404, detail="mission not found") from None

    # 1) startable: `created`, or F1-started `running` with no active F5
    #    runner (the poll window — contracts/workflow-api.md sequencing).
    _reject_concurrent(mission_id)
    if mission.status is not MissionStatus.CREATED and mission.status is not MissionStatus.RUNNING:
        raise HTTPException(
            status_code=409,
            detail=(
                f"mission not runnable: {mission.status.value} "
                "(use resume / retry / a new mission)"
            ),
        )
    # 2) model pin, 3) quota gate — both 409, never a silent switch/override.
    resolved_model, quota_note = _preflight(req.confirm_low_quota)

    if mission.status is MissionStatus.CREATED:
        ctrl.start(mission_id)  # F1 start remains the only mission_started source
    ctrl.record_run_context(
        mission_id,
        objective=req.objective,
        resolved_model=resolved_model,
        quota_note=quota_note,
    )
    try:
        runner_mod.start_background(mission_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return ctrl.get(mission_id)


@router.post("/{mission_id}/retry", response_model=Mission, status_code=202)
def retry_mission(mission_id: str, req: RetryMissionRequest | None = None) -> Mission:
    req = req or RetryMissionRequest()
    ctrl = _ctrl()
    try:
        mission = ctrl.get(mission_id)
    except MissionNotFoundError:
        raise HTTPException(status_code=404, detail="mission not found") from None

    if mission.status is not MissionStatus.FAILED or not mission.failed_step_id:
        raise HTTPException(
            status_code=409,
            detail="mission not retryable: requires failed status with a failed step",
        )
    _reject_concurrent(mission_id)
    # Re-check gates exactly like `run` (SC-011 / FR-011 re-verify).
    resolved_model, quota_note = _preflight(req.confirm_low_quota)
    ctrl.record_run_context(
        mission_id, resolved_model=resolved_model, quota_note=quota_note
    )
    # The controller's narrow retry() is the sole failed→running owner (I2).
    try:
        ctrl.retry(mission_id)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    try:
        runner_mod.start_background(mission_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return ctrl.get(mission_id)
