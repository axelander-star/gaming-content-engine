"""Channels: list, pause/resume (operator) and safety bounds (admin)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from api.deps import Admin, AppSettings, DbSession, Operator, Viewer, csrf_protect
from api.schemas import ChannelOut
from core.config import Settings
from core.enums import ChannelAuthStatus, ContentProjectStatus, Language, PlatformCode, UserRole
from models.access import User
from models.channels import Channel, ChannelCredential, Platform
from models.production import Variant
from models.projects import ContentProject
from models.publishing import Post
from services import audit, instagram, meta, platform, profile_sync, tiktok, youtube
from services.queue import get_redis

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
        content_project_id=channel.content_project_id,
        content_project=channel.content_project.name,
        auth_status=channel.auth_status,
        is_paused=channel.is_paused,
        min_posts_per_day=channel.min_posts_per_day,
        max_posts_per_day=channel.max_posts_per_day,
        min_interval_minutes=channel.min_interval_minutes,
        connected_account=account,
        profile_sync=(channel.strategy or {}).get("profile_sync"),
    )


def _get(db: DbSession, channel_id: int) -> Channel:
    channel = db.get(
        Channel,
        channel_id,
        options=[joinedload(Channel.platform), joinedload(Channel.content_project)],
    )
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Channel not found")
    return channel


@router.get("", response_model=list[ChannelOut])
def list_channels(_: Viewer, db: DbSession) -> list[ChannelOut]:
    rows = db.scalars(
        select(Channel)
        .options(joinedload(Channel.platform), joinedload(Channel.content_project))
        .order_by(Channel.id)
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


# --- channels per content project -------------------------------------------------


class ChannelIn(BaseModel):
    platform: PlatformCode
    language: Language
    name: str = Field(min_length=1, max_length=120)
    content_project_id: int


class ChannelProjectIn(BaseModel):
    content_project_id: int


def _active_project(db: DbSession, project_id: int) -> ContentProject:
    project = db.get(ContentProject, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Content project not found")
    if project.status == ContentProjectStatus.ARCHIVED:
        raise HTTPException(422, detail="Content project is archived")
    return project


@router.post("", response_model=ChannelOut, status_code=201)
def create_channel(body: ChannelIn, admin: Admin, db: DbSession) -> ChannelOut:
    """New channel for a content project, e.g. a second YouTube channel for nutrition.

    It starts paused, not connected and with ``max_posts_per_day = 0``: nothing can be
    published until the operator connects it and sets its safety bounds."""
    project = _active_project(db, body.content_project_id)
    plat = db.scalar(select(Platform).where(Platform.code == body.platform))
    if plat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Platform not found")
    name = " ".join(body.name.split())
    clash = db.scalar(
        select(Channel.id).where(
            Channel.platform_id == plat.id, Channel.language == body.language, Channel.name == name
        )
    )
    if clash is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A channel with this name exists")
    channel = Channel(
        platform_id=plat.id,
        content_project_id=project.id,
        language=body.language,
        name=name,
        auth_status=ChannelAuthStatus.NOT_CONNECTED,
        is_paused=True,
        min_posts_per_day=0,
        max_posts_per_day=0,
    )
    db.add(channel)
    db.flush()
    audit.record(
        db,
        "channel.create",
        user_id=admin.id,
        entity_type="channels",
        entity_id=channel.id,
        after={**body.model_dump(mode="json"), "name": name},
    )
    db.commit()
    return _out(_get(db, channel.id))


@router.put("/{channel_id}/project", response_model=ChannelOut)
def move_channel(
    channel_id: int, body: ChannelProjectIn, admin: Admin, db: DbSession
) -> ChannelOut:
    """Assign a channel to another content project. Only while it holds no videos,
    publishing jobs or posts, so no content ever changes its topic area."""
    channel = _get(db, channel_id)
    project = _active_project(db, body.content_project_id)
    if channel.content_project_id == project.id:
        return _out(channel)
    used = db.scalar(select(func.count(Variant.id)).where(Variant.channel_id == channel.id)) or 0
    used += db.scalar(select(func.count(Post.id)).where(Post.channel_id == channel.id)) or 0
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Der Kanal hat bereits Videos oder Beiträge und kann den Themenbereich "
            "nicht mehr wechseln. Lege für den neuen Themenbereich einen eigenen Kanal an.",
        )
    before = {"content_project_id": channel.content_project_id}
    channel.content_project_id = project.id
    audit.record(
        db,
        "channel.project",
        user_id=admin.id,
        entity_type="channels",
        entity_id=channel.id,
        before=before,
        after={"content_project_id": project.id},
    )
    db.commit()
    db.refresh(channel)
    return _out(_get(db, channel.id))


# --- platform connection (Phase 12/13) -----------------------------------------------


class ConnectOut(BaseModel):
    url: str


def _authorization_url(settings: Settings, channel: Channel, user_id: int) -> str:
    code = PlatformCode(channel.platform.code)
    provider = platform.provider_for(code, settings)
    state = platform.make_state(settings, provider, channel.id, user_id)
    if provider == instagram.PROVIDER:
        return instagram.authorization_url(settings, state)
    if code == PlatformCode.YOUTUBE:
        return youtube.authorization_url(settings, state)
    if code == PlatformCode.TIKTOK:
        return tiktok.authorization_url(settings, state)
    return meta.authorization_url(settings, state, code)


@router.post("/{channel_id}/connect", response_model=ConnectOut)
def connect_channel(
    channel_id: int, admin: Admin, db: DbSession, settings: AppSettings
) -> ConnectOut:
    """Start the OAuth consent at the platform; the browser is sent to ``url``."""
    channel = _get(db, channel_id)
    try:
        url = _authorization_url(settings, channel, admin.id)
    except platform.NotConfiguredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    audit.record(db, "channel.connect_started", user_id=admin.id, entity_type="channels",
                 entity_id=channel.id)  # fmt: skip
    db.commit()
    return ConnectOut(url=url)


def _revoke(settings: Settings, cred: ChannelCredential) -> bool:
    """Best effort. Meta: no documented revoke call is used; access ends when the
    stored Page token is deleted (the operator can remove the app in Facebook)."""
    if cred.provider == youtube.PROVIDER:
        return youtube.revoke(settings, cred)
    if cred.provider == tiktok.PROVIDER:
        return tiktok.revoke(settings, cred)
    return False


@router.post("/{channel_id}/disconnect", response_model=ChannelOut)
def disconnect_channel(
    channel_id: int, admin: Admin, db: DbSession, settings: AppSettings
) -> ChannelOut:
    """Revoke the access at the platform (best effort) and delete the stored tokens."""
    channel = _get(db, channel_id)
    cred = db.scalar(select(ChannelCredential).where(ChannelCredential.channel_id == channel.id))
    revoked = _revoke(settings, cred) if cred else False
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


def _status_after_connect(
    settings: Settings, code: PlatformCode, cred: ChannelCredential
) -> ChannelAuthStatus:
    scopes = cred.scopes or []
    if code == PlatformCode.YOUTUBE:
        ok = youtube.UPLOAD_SCOPE in scopes
    elif code == PlatformCode.TIKTOK:
        # Unaudited TikTok apps may only post privately: hold videos (PROJECT_SPEC 11).
        # Drafts to the creator's inbox never go public by themselves (E8).
        if settings.tiktok_post_mode == "inbox":
            ok = tiktok.UPLOAD_SCOPE in scopes
        else:
            ok = tiktok.PUBLISH_SCOPE in scopes and settings.tiktok_app_audited
    elif cred.provider == instagram.PROVIDER:
        ok = instagram.PUBLISH_SCOPE in scopes
    else:
        ok = meta.PUBLISH_SCOPE[code] in scopes
    return ChannelAuthStatus.AUTHORIZED if ok else ChannelAuthStatus.CONNECTED_RESTRICTED


#: Platform error reasons -> short code the dashboard explains in plain words.
_FAILURE_REASONS = {
    "no_channel": "no_channel",
    "youtubeSignupRequired": "no_channel",
    "no_refresh_token": "no_refresh",
    "accessNotConfigured": "api_disabled",
    "SERVICE_DISABLED": "api_disabled",
    "invalid_client": "client",
    "unauthorized_client": "client",
    "redirect_uri_mismatch": "redirect",
    "insufficientPermissions": "scopes",
    "ACCESS_TOKEN_SCOPE_INSUFFICIENT": "scopes",
}


def connect_failure_reason(exc: Exception) -> str:
    """Why connecting failed, as a code for ``?<provider>=failed&reason=…`` ("" = unknown)."""
    if isinstance(exc, platform.NotConfiguredError):
        return "not_configured"
    if isinstance(exc, platform.TransientError):
        return "temporary"
    if isinstance(exc, platform.PlatformError) and exc.reason:
        return _FAILURE_REASONS.get(exc.reason, "")
    return ""


oauth_router = APIRouter(prefix="/oauth", tags=["oauth"])
PROVIDERS = ("youtube", "tiktok", "meta", "instagram")


@oauth_router.get("/{provider}/callback")
def oauth_callback(
    provider: str,
    db: DbSession,
    settings: AppSettings,
    state: str = "",
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """The platform redirects here after the consent; the signed ``state`` names
    channel, user and provider. The dashboard shows the result (``?<provider>=…``)."""
    if provider not in PROVIDERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown provider")
    target = "/einstellungen"

    def back(result: str, reason: str = "") -> RedirectResponse:
        extra = f"&reason={reason}" if reason else ""
        return RedirectResponse(f"{target}?{provider}={result}{extra}", status_code=303)

    try:
        channel_id, user_id = platform.read_state(settings, provider, state)
    except platform.PlatformError:
        return back("invalid")
    if error or not code:
        return back("denied")
    channel = db.get(Channel, channel_id)
    user = db.get(User, user_id)
    if channel is None or user is None or user.role != UserRole.ADMIN or not user.is_active:
        return back("invalid")
    platform_code = PlatformCode(channel.platform.code)
    if platform.provider_for(platform_code, settings) != provider:
        return back("invalid")
    connect = {
        "youtube": youtube.connect,
        "tiktok": tiktok.connect,
        "meta": meta.connect,
        "instagram": instagram.connect,
    }
    try:
        cred = connect[provider](db, settings, channel, code, user_id)
    except (platform.PlatformError, platform.NotConfiguredError) as exc:
        db.rollback()
        reason = connect_failure_reason(exc)
        log.warning(
            "platform connect failed: %s (%s)",
            exc,
            reason or "unknown",
            extra={"provider": provider, "channel": channel_id, "error": str(exc)},
        )
        return back("failed", reason)
    # One real account belongs to exactly one channel: otherwise two topic areas
    # (e.g. Gaming and Ernährung) would post to the same YouTube channel.
    if cred.external_account_id and db.scalar(
        select(Channel.id).where(
            Channel.platform_id == channel.platform_id,
            Channel.external_channel_id == cred.external_account_id,
            Channel.id != channel.id,
        )
    ):
        db.rollback()
        log.warning(
            "platform account already used by another channel",
            extra={"provider": provider, "channel": channel_id},
        )
        return back("in_use")
    before = channel.auth_status.value
    channel.external_channel_id = cred.external_account_id
    channel.auth_status = _status_after_connect(settings, platform_code, cred)
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
    if provider == "youtube" and channel.auth_status == ChannelAuthStatus.AUTHORIZED:
        # fill the new channel's profile right away (description, keywords, banner);
        # a failure is shown in the dashboard and never undoes the connection
        profile_sync.sync_youtube(db, settings, get_redis(), channel)
        db.commit()
    return back(
        "connected" if channel.auth_status == ChannelAuthStatus.AUTHORIZED else "restricted"
    )


@router.post("/{channel_id}/profile-sync", response_model=ChannelOut)
def sync_profile(channel_id: int, admin: Admin, db: DbSession, settings: AppSettings) -> ChannelOut:
    """Write the prepared profile to the connected YouTube channel again."""
    channel = _get(db, channel_id)
    if channel.platform.code != PlatformCode.YOUTUBE:
        raise HTTPException(422, detail="Only YouTube profiles can be written via API")
    result = profile_sync.sync_youtube(db, settings, get_redis(), channel)
    audit.record(
        db,
        "channel.profile_sync",
        user_id=admin.id,
        entity_type="channels",
        entity_id=channel.id,
        after=result.as_dict(),
    )
    db.commit()
    return _out(channel)
