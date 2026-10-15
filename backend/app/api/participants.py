"""Participant join + presence routes (F2: join page, QR, live count).

Name validation failures are 400 with a clear message (contracts);
unknown participant ids are 404; heartbeat on a departed id is 409.
"""

from __future__ import annotations

import io
import os
import socket

import qrcode
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from backend.app.participants.controller import (
    ParticipantGoneError,
    ParticipantNotFoundError,
    get_participants_controller,
)
from backend.app.participants.models import JoinRequest, ParticipantView, RosterView

router = APIRouter(prefix="/api", tags=["participants"])

QR_URL = "/api/join-info/qr"
JOIN_PAGE_PATH = "/join.html"
_LOOPBACK_PREFIXES = ("localhost", "127.", "0.0.0.0", "::1", "[::1]")


class JoinInfo(BaseModel):
    join_url: str
    qr_url: str = QR_URL
    ready: bool


def _ctrl():
    return get_participants_controller()


def _is_loopback(host: str) -> bool:
    return host.lower() in ("localhost", "::1", "[::1]") or host.startswith(
        ("127.", "0.0.0.0")
    )


def _lan_ip() -> str | None:
    """Best-effort local LAN address (UDP trick sends no traffic)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))
            ip = sock.getsockname()[0]
    except OSError:
        return None
    return None if ip is None or _is_loopback(ip) else ip


def _resolve_join_base(request: Request) -> tuple[str | None, bool]:
    """Return (join_url, ready). Never advertises a loopback-only target."""
    override = os.environ.get("PLAYGROUND_JOIN_URL", "").strip().rstrip("/")
    if override:
        return f"{override}{JOIN_PAGE_PATH}", True
    host_header = (request.headers.get("host") or "").split(",")[0].strip()
    host = host_header.split(":")[0] if host_header else ""
    if host_header and host and not _is_loopback(host):
        return f"http://{host_header}{JOIN_PAGE_PATH}", True
    ip = _lan_ip()
    if ip:
        port = request.url.port or 8000
        return f"http://{ip}:{port}{JOIN_PAGE_PATH}", True
    return f"http://localhost:{request.url.port or 8000}{JOIN_PAGE_PATH}", False


def _view(participant) -> ParticipantView:
    return ParticipantView(
        id=participant.id,
        display_name=participant.display_name,
        anonymous=participant.anonymous,
        status=participant.status,
        joined_at=participant.joined_at,
    )


@router.get("/join-info", response_model=JoinInfo)
def join_info(request: Request) -> JoinInfo:
    join_url, ready = _resolve_join_base(request)
    return JoinInfo(join_url=join_url, ready=ready)


@router.get("/join-info/qr")
def join_qr(request: Request) -> Response:
    join_url, ready = _resolve_join_base(request)
    if not ready:
        raise HTTPException(status_code=404, detail="join target not reachable")
    qr = qrcode.QRCode(border=2, box_size=8)
    qr.add_data(join_url)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image().save(buf, format="PNG")
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/participants", response_model=RosterView)
def list_participants() -> RosterView:
    roster = _ctrl().roster()
    return RosterView(count=len(roster), participants=[_view(p) for p in roster])


@router.post("/participants/join", response_model=ParticipantView, status_code=201)
def join_participant(req: JoinRequest) -> ParticipantView:
    try:
        return _view(_ctrl().join(req.display_name))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/participants/{participant_id}/heartbeat", response_model=ParticipantView)
def heartbeat_participant(participant_id: str) -> ParticipantView:
    try:
        return _view(_ctrl().heartbeat(participant_id))
    except ParticipantNotFoundError:
        raise HTTPException(status_code=404, detail="participant not found") from None
    except ParticipantGoneError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/participants/{participant_id}/leave", response_model=ParticipantView)
def leave_participant(participant_id: str) -> ParticipantView:
    try:
        return _view(_ctrl().leave(participant_id))
    except ParticipantNotFoundError:
        raise HTTPException(status_code=404, detail="participant not found") from None


@router.post("/participants/{participant_id}/rejoin", response_model=ParticipantView)
def rejoin_participant(participant_id: str) -> ParticipantView:
    try:
        return _view(_ctrl().rejoin(participant_id))
    except ParticipantNotFoundError:
        raise HTTPException(status_code=404, detail="participant not found") from None
