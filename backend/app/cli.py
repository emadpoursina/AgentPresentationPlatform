"""Terminal-first F5 CLI (FR-017, contracts/workflow-api.md CLI section).

    uv run python -m backend.app.cli run "topic" [--confirm-low-quota] [--mission-id ID]
    uv run python -m backend.app.cli retry  <mission_id> [--confirm-low-quota]
    uv run python -m backend.app.cli status [<mission_id>]

One code path: `run`/`retry` drive the same `SerialWorkflowRunner` synchronously
in-process (no HTTP server) and print every event live as `<seq> <type> <json
data>`. Exit codes: 0 completed, 1 failed (reason + preserved outputs +
options printed), 2 pre-flight/validation failure (model pin, quota, topic).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable

from backend.app.agents.runner import (
    LowQuotaError,
    ModelPinError,
    run_mission_sync,
    run_preflight,
)
from backend.app.events.store import event_store
from backend.app.missions.controller import (
    InvalidTransitionError,
    MissionNotFoundError,
    get_controller,
)
from backend.app.missions.models import CreateMissionRequest, MissionStatus

TOPIC_MAX = 500  # objective bound; title stays the F1 120-char bound
TITLE_MAX = 120


def _print_event(payload: dict) -> None:
    print(
        f"{payload['id']} {payload['type']} {json.dumps(payload['data'])}",
        flush=True,
    )


def _print_events_after(
    mission_id: str, after_id: int, printer: Callable[[dict], None] | None = None
) -> None:
    for payload in event_store.list(mission_id=mission_id, after_id=after_id, limit=500):
        (printer or _print_event)(payload)


def _cmd_run(args: argparse.Namespace) -> int:
    topic = args.topic
    if len(topic) > TOPIC_MAX:
        print(
            f"error: topic must be {TOPIC_MAX} characters or fewer "
            f"(got {len(topic)}) — no mission created",
            file=sys.stderr,
        )
        return 2

    try:
        resolved_model, quota_note = run_preflight(
            confirm_low_quota=args.confirm_low_quota
        )
    except (ModelPinError, LowQuotaError) as exc:
        print(f"pre-flight gate failed: {exc}", file=sys.stderr)
        return 2

    ctrl = get_controller()
    # `--mission-id` is accepted for CLI-shape compatibility; F1's controller
    # owns id generation, so the real id is reported right after creation.
    mission = ctrl.create(CreateMissionRequest(title=topic[:TITLE_MAX]))
    ctrl.record_run_context(
        mission.id,
        objective=topic,
        resolved_model=resolved_model,
        quota_note=quota_note,
    )
    ctrl.start(mission.id)
    print(f"mission {mission.id}: {mission.title}", flush=True)
    printed = {"last": 0}

    def printer(payload: dict) -> None:
        printed["last"] = payload["id"]
        _print_event(payload)

    _print_events_after(mission.id, 0, printer)  # mission_created + mission_started

    run_mission_sync(mission.id, on_event=printer)
    # Terminal lifecycle events are emitted by the controller itself — flush
    # anything not seen live so stdout always ends with the terminal event.
    _print_events_after(mission.id, printed["last"], printer)
    return _finish(mission.id)


def _cmd_retry(args: argparse.Namespace) -> int:
    ctrl = get_controller()
    try:
        mission = ctrl.get(args.mission_id)
    except MissionNotFoundError:
        print(f"error: mission {args.mission_id!r} not found", file=sys.stderr)
        return 2
    if mission.status is not MissionStatus.FAILED or not mission.failed_step_id:
        print(
            "error: retry requires a failed mission with a failed step "
            f"(status={mission.status.value}) — start a new mission for a "
            "fresh full run",
            file=sys.stderr,
        )
        return 2
    try:
        resolved_model, quota_note = run_preflight(
            confirm_low_quota=args.confirm_low_quota
        )
    except (ModelPinError, LowQuotaError) as exc:
        print(f"pre-flight gate failed: {exc}", file=sys.stderr)
        return 2
    ctrl.record_run_context(
        mission.id, resolved_model=resolved_model, quota_note=quota_note
    )
    try:
        ctrl.retry(mission.id)  # sole failed→running owner; emits mission_resumed
    except InvalidTransitionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    last = event_store.list(mission_id=mission.id, after_id=0, limit=500)[-1]
    printed = {"last": last["id"]}
    _print_event(last)  # the mission_resumed event

    def printer(payload: dict) -> None:
        printed["last"] = payload["id"]
        _print_event(payload)

    run_mission_sync(mission.id, on_event=printer)
    _print_events_after(mission.id, printed["last"], printer)
    return _finish(mission.id)


def _finish(mission_id: str) -> int:
    """Print the terminal outcome; exit 0 completed / 1 failed."""
    mission = get_controller().get(mission_id)
    if mission.status is MissionStatus.COMPLETED:
        print("\nresult:", flush=True)
        print(mission.result_summary or "", flush=True)
        return 0
    print(f"\nmission failed: {mission.error or 'unknown error'}", file=sys.stderr)
    print("preserved step outputs:", file=sys.stderr)
    for record in mission.agent_runs:
        status = record.status
        output = (record.output or "").strip()
        preview = output[:200] if output else "(no output)"
        print(f"  [{record.step_id}] {record.agent_id} {status}: {preview}", file=sys.stderr)
    print(
        "options: uv run python -m backend.app.cli retry "
        f"{mission_id} --confirm-low-quota  |  create a new mission "
        "(fresh full re-run)",
        file=sys.stderr,
    )
    return 1


def _cmd_status(args: argparse.Namespace) -> int:
    ctrl = get_controller()
    if args.mission_id:
        try:
            missions = [ctrl.get(args.mission_id)]
        except MissionNotFoundError:
            print(f"error: mission {args.mission_id!r} not found", file=sys.stderr)
            return 2
    else:
        missions = ctrl.list()
    if not missions:
        print("no missions")
        return 0
    for mission in missions:
        print(f"mission {mission.id} [{mission.status.value}]: {mission.title}")
        print(f"  objective: {mission.objective or '-'}")
        print(f"  resolved_model: {mission.resolved_model or '-'}")
        print(f"  quota_note: {mission.quota_note or '-'}")
        print(f"  retry_count: {mission.retry_count}  failed_step: {mission.failed_step_id or '-'}")
        if mission.result_summary:
            print(f"  result_summary: {mission.result_summary}")
        for record in mission.agent_runs:
            print(f"  step {record.step_id} ({record.profile}) {record.agent_id}: {record.status}")
            print(f"    task_input: {record.task_input}")
            print(f"    output: {record.output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.app.cli",
        description="Run serial F5 missions through the real Hermes CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="create + run a mission to completion")
    run_p.add_argument("topic", help="mission topic (≤500 chars)")
    run_p.add_argument("--confirm-low-quota", action="store_true")
    run_p.add_argument("--mission-id", default=None, help="(reserved; ids are generated)")

    retry_p = sub.add_parser("retry", help="resume a failed mission at its failed step")
    retry_p.add_argument("mission_id")
    retry_p.add_argument("--confirm-low-quota", action="store_true")

    status_p = sub.add_parser("status", help="show mission(s) and agent runs")
    status_p.add_argument("mission_id", nargs="?")

    args = parser.parse_args(argv)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "retry":
        return _cmd_retry(args)
    return _cmd_status(args)


if __name__ == "__main__":
    sys.exit(main())
