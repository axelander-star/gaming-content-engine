"""Channels: list, pause/resume (operator) and safety bounds (admin)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from api.deps import Admin, AppSettings, DbSession, Operator, Viewer, csrf_protect
from api.schemas import ChannelOut
from core.enums import ChannelAuthStatus, PlatformCode, UserRole
from models.access import User
from models.channels import Channel, ChannelCredential
from services import audit, youtube

log = logging.getLogger(__name__)

router = APIRouter(prefix="/channels", tags=["channels"], dependencies=[Depends(csrf_protect)])


class ChannelLimits(BaseModel):
    """Safety bounds, not targets. The strategy agent decides the actual amount."""

    min_posts_per_day: int = Field(ge=0, le=100)
    max_posts_per_day: int = Field(ge=0, le=100)
    min_interval_minutes: int = Field(ge=0, le=7 * 24 * 60)

    @model_validator(mode="after")
    def _max_gte_min(self) -> ChannelLimits:
        if self.max_posts_per_day < self.min_posts_per_day:
            raise ValueError("max_posts_per_day must be >= min_posts_per_day")
        return self


def _out(channel: Channel, account: str | None = None) -> ChannelOut:
    return ChannelOut(
        id=channel.id,
        name=channel.name,
        language=channel.language,
        platform=channel.platform.code,
        auth_status=channel.auth_status,
        is_paused=channel.is_paused,
        min_posts_per_day=channel.min_posts_per_day,
        max_posts_per_day=channel.max_posts_per_day,
        min_interval_minutes=channel.min_interval_minutes,
        connected_account=account,
    )


def _get(db: DbSession, channel_id: int) -> Channel:
    channel = db.get(Channel, channel_id, options=[joinedload(Channel.platform)])
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Channel not found")
    return channel


@router.get("", response_model=list[ChannelOut])
def list_channels(_: Viewer, db: DbSession) -> list[ChannelOut]:
    rows = db.scalars(
        select(Channel).options(joinedload(Channel.platform)).order_by(Channel.id)
    ).all()
    accounts = dict(
        db.execute(
            select(ChannelCredential.channel_id, ChannelCredential.external_account_name)
        ).all()
    )
    return [_out(c, accounts.get(c.id)) for c in rows]


def _set_paused(db: DbSession, channel_id: int, paused: bool, user_id: int) -> ChannelOut:
    channel = _get(db, channel_id)
    before = channel.is_paused
    channel.is_paused = paused
    audit.record(
        db,
        "channel.pause" if paused else "channel.resume",
        user_id=user_id,
        entity_type="channels",
        entity_id=channel.id,
        before={"is_paused": before},
        after={"is_paused": paused},
    )
    db.commit()
    return _out(channel)


@router.post("/{channel_id}/pause", response_model=ChannelOut)
def pause_channel(channel_id: int, user: Operator, db: DbSession) -> ChannelOut:
    return _set_paused(db, channel_id, True, user.id)


@router.post("/{channel_id}/resume", response_model=ChannelOut)
def resume_channel(channel_id: int, admin: Admin, db: DbSession) -> ChannelOut:
    return _set_paused(db, channel_id, False, admin.id)


@router.put("/{channel_id}/limits", response_model=ChannelOut)
def set_limits(channel_id: int, body: ChannelLimits, admin: Admin, db: DbSession) -> ChannelOut:
    channel = _get(db, channel_id)
    before = {
        "min_posts_per_day": channel.min_posts_per_day,
        "max_posts_per_day": channel.max_posts_per_day,
        "min_interval_minutes": channel.min_interval_minutes,
    }
    channel.min_posts_per_day = body.min_posts_per_day
    channel.max_posts_per_day = body.max_posts_per_day
    channel.min_interval_minutes = body.min_interval_minutes
    audit.record(
        db,
        "channel.limits",
        user_id=admin.id,
        entity_type="channels",
        entity_id=channel.id,
        before=before,
        after=body.model_dump(),
    )
    db.commit()
    return _out(channel)


# --- platform connection (Phase 12) --------------------------------------------------


class ConnectOut(BaseModel):
    url: str


@router.post("/{channel_id}/connect", response_model=ConnectOut)
def connect_channel(
    channel_id: int, admin: Admin, db: DbSession, settings: AppSettings
) -> ConnectOut:
    """Start the OAuth consent at the platform; the browser is sent to ``url``."""
    channel = _get(db, channel_id)
    if channel.platform.code != PlatformCode.YOUTUBE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Platform follows in phase 13")
    try:
        url = youtube.authorization_url(
            settings, youtube.make_state(settings, channel.id, admin.id)
        )
    except youtube.NotConfiguredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    audit.record(db, "channel.connect_started", user_id=admin.id, entity_type="channels",
                 entity_id=channel.id)  # fmt: skip
    db.commit()
    return ConnectOut(url=url)


@router.post("/{channel_id}/disconnect", response_model=ChannelOut)
def disconnect_channel(
    channel_id: int, admin: Admin, db: DbSession, settings: AppSettings
) -> ChannelOut:
    """Revoke the access at the platform (best effort) and delete the stored tokens."""
    channel = _get(db, channel_id)
    cred = db.scalar(select(ChannelCredential).where(ChannelCredential.channel_id == channel.id))
    revoked = youtube.revoke(settings, cred) if cred else False
    if cred is not None:
        db.delete(cred)
    before = channel.auth_status.value
    channel.auth_status = ChannelAuthStatus.NOT_CONNECTED
    audit.record(
        db,
        "channel.disconnect",
        user_id=admin.id,
        entity_type="channels",
        entity_id=channel.id,
        before={"auth_status": before},
        after={"auth_status": channel.auth_status.value, "revoked": revoked},
    )
    db.commit()
    return _out(channel)


oauth_router = APIRouter(prefix="/oauth", tags=["oauth"])


@oauth_router.get("/youtube/callback")
def youtube_callback(
    db: DbSession,
    settings: AppSettings,
    state: str = "",
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Google redirects here after the consent; the signed ``state`` names channel and user."""
    target = "/einstellungen"
    try:
        channel_id, user_id = youtube.read_state(settings, state)
    except youtube.YouTubeError:
        return RedirectResponse(f"{target}?youtube=invalid", status_code=303)
    if error or not code:
        return RedirectResponse(f"{target}?youtube=denied", status_code=303)
    channel = db.get(Channel, channel_id)
    user = db.get(User, user_id)
    if channel is None or user is None or user.role != UserRole.ADMIN or not user.is_active:
        return RedirectResponse(f"{target}?youtube=invalid", status_code=303)
    try:
        cred = youtube.connect(db, settings, channel, code, user_id)
    except (youtube.YouTubeError, youtube.NotConfiguredError) as exc:
        db.rollback()
        log.warning("youtube connect failed", extra={"channel": channel_id, "error": str(exc)})
        return RedirectResponse(f"{target}?youtube=failed", status_code=303)
    before = channel.auth_status.value
    channel.external_channel_id = cred.external_account_id
    channel.auth_status = (
        ChannelAuthStatus.AUTHORIZED
        if youtube.UPLOAD_SCOPE in (cred.scopes or [])
        else ChannelAuthStatus.CONNECTED_RESTRICTED
    )
    audit.record(
        db,
        "channel.connected",
        user_id=user_id,
        entity_type="channels",
        entity_id=channel.id,
        before={"auth_status": before},
        after={
            "auth_status": channel.auth_status.value,
            "account": cred.external_account_name,
            "scopes": cred.scopes,
        },
    )
    db.commit()
    return RedirectResponse(f"{target}?youtube=connected", status_code=303)
