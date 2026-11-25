"""Dashboard overview: counts, platform tiles, recent posts, errors and activity.

``GET /overview`` keeps the compact counts of the first dashboard;
``GET /overview/dashboard`` delivers everything the start page shows in one
request so the page can refresh itself periodically.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import func, select

from api.deps import AppSettings, DbSession, Viewer
from core.config import Settings
from core.enums import (
    AgentRunStatus,
    ChannelAuthStatus,
    PlatformCode,
    PublishingJobStatus,
    VideoStatus,
)
from models.access import AuditLog, User
from models.channels import Channel, Platform
from models.control import AgentRun
from models.production import Variant
from models.projects import ContentProject
from models.publishing import Post, PublishingJob
from services import source_status
from services.channel_setup import is_placeholder
from services.controls import EffectiveControls, effective_controls
from services.queue import get_redis

RedisDep = Annotated[Redis, Depends(get_redis)]

router = APIRouter(prefix="/overview", tags=["overview"])

_IN_PRODUCTION = {
    VideoStatus.SCENE_SELECTED,
    VideoStatus.EDITING,
    VideoStatus.LOCALIZATION,
    VideoStatus.VOICEOVER,
    VideoStatus.SUBTITLES,
}


class OverviewOut(BaseModel):
    published_videos: int
    videos_in_production: int
    videos_in_quality_check: int
    videos_ready_to_publish: int
    videos_failed: int
    channels_total: int
    channels_active: int
    controls: EffectiveControls


@router.get("", response_model=OverviewOut)
def overview(_: Viewer, db: DbSession, settings: AppSettings) -> OverviewOut:
    rows = db.execute(select(Variant.status, func.count()).group_by(Variant.status))
    by_status: dict[VideoStatus, int] = {status: n for status, n in rows}

    def count(*statuses: VideoStatus) -> int:
        return sum(by_status.get(s, 0) for s in statuses)

    # placeholders (seed channels without a real account) are not counted
    real_channels = [c for c in db.scalars(select(Channel)) if not is_placeholder(c)]
    channels_total = len(real_channels)
    channels_active = sum(1 for c in real_channels if not c.is_paused)
    published = (
        db.scalar(select(func.count()).select_from(Post).where(Post.is_mock.is_(False))) or 0
    )
    return OverviewOut(
        published_videos=published,
        videos_in_production=count(*_IN_PRODUCTION),
        videos_in_quality_check=count(VideoStatus.QUALITY_CHECK),
        videos_ready_to_publish=count(VideoStatus.READY_TO_PUBLISH, VideoStatus.SCHEDULED),
        videos_failed=count(VideoStatus.FAILED),
        channels_total=channels_total,
        channels_active=channels_active,
        controls=effective_controls(db, settings),
    )


# --- creator dashboard (extension E2) --------------------------------------------------

#: User-facing video states of the dashboard; ``uploading`` comes from running jobs.
_DASHBOARD_STATES: dict[str, set[VideoStatus]] = {
    "draft": {VideoStatus.SCENE_SELECTED},
    "in_progress": _IN_PRODUCTION
    | {VideoStatus.QUALITY_CHECK, VideoStatus.QUALITY_APPROVED, VideoStatus.QUALITY_REJECTED},
    "ready": {VideoStatus.READY_TO_PUBLISH},
    "scheduled": {VideoStatus.SCHEDULED},
    "published": {VideoStatus.PUBLISHED, VideoStatus.ANALYTICS_PENDING, VideoStatus.ANALYZED},
    "failed": {VideoStatus.FAILED},
}
_OPEN_JOBS = (
    PublishingJobStatus.PENDING,
    PublishingJobStatus.SCHEDULED,
    PublishingJobStatus.RUNNING,
)

#: Tiles of the dashboard. Twitch has no upload API: it is a data source only.
_TILES: tuple[tuple[str, str, bool, str], ...] = (
    ("youtube", "YouTube", True, "Shorts und Videos"),
    ("twitch", "Twitch", False, "Datenquelle – Twitch bietet keine Upload-Schnittstelle"),
    ("instagram", "Instagram", True, "Reels"),
    ("tiktok", "TikTok", True, "Ohne TikTok-Prüfung nur privat bzw. als Entwurf"),
)


class StateCount(BaseModel):
    key: str
    count: int


class PlatformTile(BaseModel):
    code: str
    name: str
    can_publish: bool
    note: str
    #: not_connected · restricted · connected · expired · data_source_mock · data_source_ok ·
    #: data_source_error
    connection: str
    channels: int
    channels_connected: int
    published: int
    test_posts: int
    last_published_at: datetime | None
    open_jobs: int
    failed_jobs: int


class RecentPost(BaseModel):
    id: int
    title: str | None
    platform: str
    channel: str
    content_project: str
    published_at: datetime | None
    url: str | None
    is_mock: bool


class FailedItem(BaseModel):
    kind: str  # "publishing" or "video"
    id: int
    title: str | None
    platform: str | None
    channel: str | None
    error: str | None
    at: datetime


class Activity(BaseModel):
    at: datetime
    kind: str  # "audit" or "agent"
    action: str
    actor: str | None
    entity_type: str | None
    entity_id: int | None
    status_before: str | None = None
    status_after: str | None = None
    message: str | None = None


class DashboardOut(BaseModel):
    videos_total: int
    published: int
    scheduled: int
    unpublished: int
    failed: int
    states: list[StateCount]
    platforms: list[PlatformTile]
    recent_posts: list[RecentPost]
    failures: list[FailedItem]
    activity: list[Activity]
    controls: EffectiveControls


def _connection(statuses: list[ChannelAuthStatus]) -> str:
    if ChannelAuthStatus.AUTHORIZED in statuses:
        return "connected"
    if ChannelAuthStatus.CONNECTED_RESTRICTED in statuses:
        return "restricted"
    if ChannelAuthStatus.EXPIRED in statuses:
        return "expired"
    return "not_connected"


def _twitch_connection(settings: Settings, redis: Redis) -> str:
    if not source_status.configured(settings, "twitch"):
        return "not_connected"
    info = next(s for s in source_status.overview(settings, redis) if s["name"] == "twitch")
    last = info["last"] or {}
    if settings.trend_sources_mode != "live":
        return "data_source_mock"
    if last.get("state") in ("ok", "partial"):
        return "data_source_ok"
    if last.get("state") == "error":
        return "data_source_error"
    return "data_source_mock"


def _tiles(db: DbSession, settings: Settings, redis: Redis) -> list[PlatformTile]:
    channels = db.execute(select(Channel, Platform.code).join(Platform)).all()
    by_platform: dict[str, list[ChannelAuthStatus]] = {}
    for channel, plat in channels:
        if is_placeholder(channel):
            continue  # no real account behind it yet
        by_platform.setdefault(PlatformCode(plat).value, []).append(channel.auth_status)
    posts = db.execute(
        select(
            Platform.code,
            Post.is_mock,
            func.count(Post.id),
            func.max(Post.published_at),
        )
        .join(Channel, Channel.id == Post.channel_id)
        .join(Platform, Platform.id == Channel.platform_id)
        .where(Post.published_at.is_not(None))
        .group_by(Platform.code, Post.is_mock)
    ).all()
    jobs = db.execute(
        select(Platform.code, PublishingJob.status, func.count(PublishingJob.id))
        .join(Channel, Channel.id == PublishingJob.channel_id)
        .join(Platform, Platform.id == Channel.platform_id)
        .group_by(Platform.code, PublishingJob.status)
    ).all()
    out = []
    for tile_code, name, can_publish, note in _TILES:
        real = [p for p in posts if PlatformCode(p[0]).value == tile_code and not p[1]]
        test = [p for p in posts if PlatformCode(p[0]).value == tile_code and p[1]]
        last_times = [p[3] for p in real if p[3] is not None]
        job_rows = [j for j in jobs if PlatformCode(j[0]).value == tile_code]
        statuses = by_platform.get(tile_code, [])
        out.append(
            PlatformTile(
                code=tile_code,
                name=name,
                can_publish=can_publish,
                note=note,
                connection=_twitch_connection(settings, redis)
                if tile_code == "twitch"
                else _connection(statuses),
                channels=len(statuses),
                channels_connected=sum(
                    1
                    for s in statuses
                    if s in (ChannelAuthStatus.AUTHORIZED, ChannelAuthStatus.CONNECTED_RESTRICTED)
                ),
                published=sum(int(p[2]) for p in real),
                test_posts=sum(int(p[2]) for p in test),
                last_published_at=max(last_times) if last_times else None,
                open_jobs=sum(int(j[2]) for j in job_rows if j[1] in _OPEN_JOBS),
                failed_jobs=sum(int(j[2]) for j in job_rows if j[1] == PublishingJobStatus.FAILED),
            )
        )
    return out


def _recent_posts(db: DbSession, limit: int = 8) -> list[RecentPost]:
    rows = db.execute(
        select(Post, Variant.title, Channel.name, Platform.code, ContentProject.name)
        .join(Variant, Variant.id == Post.variant_id)
        .join(Channel, Channel.id == Post.channel_id)
        .join(Platform, Platform.id == Channel.platform_id)
        .join(ContentProject, ContentProject.id == Post.content_project_id)
        .order_by(Post.published_at.desc().nulls_last(), Post.id.desc())
        .limit(limit)
    ).all()
    return [
        RecentPost(
            id=post.id,
            title=title,
            platform=PlatformCode(code).value,
            channel=channel,
            content_project=project,
            published_at=post.published_at,
            url=post.url,
            is_mock=post.is_mock,
        )
        for post, title, channel, code, project in rows
    ]


def _failures(db: DbSession, limit: int = 8) -> list[FailedItem]:
    jobs = db.execute(
        select(PublishingJob, Variant.title, Channel.name, Platform.code)
        .join(Variant, Variant.id == PublishingJob.variant_id)
        .join(Channel, Channel.id == PublishingJob.channel_id)
        .join(Platform, Platform.id == Channel.platform_id)
        .where(PublishingJob.status == PublishingJobStatus.FAILED)
        .order_by(PublishingJob.updated_at.desc())
        .limit(limit)
    ).all()
    videos = db.execute(
        select(Variant, Channel.name, Platform.code)
        .join(Channel, Channel.id == Variant.channel_id)
        .join(Platform, Platform.id == Channel.platform_id)
        .where(Variant.status == VideoStatus.FAILED)
        .order_by(Variant.updated_at.desc())
        .limit(limit)
    ).all()
    items = [
        FailedItem(
            kind="publishing",
            id=job.id,
            title=title,
            platform=PlatformCode(code).value,
            channel=channel,
            error=job.last_error,
            at=job.updated_at,
        )
        for job, title, channel, code in jobs
    ] + [
        FailedItem(
            kind="video",
            id=v.id,
            title=v.title,
            platform=PlatformCode(code).value,
            channel=channel,
            error=v.error_message,
            at=v.updated_at,
        )
        for v, channel, code in videos
    ]
    return sorted(items, key=lambda i: i.at, reverse=True)[:limit]


def _activity(db: DbSession, limit: int = 12) -> list[Activity]:
    audits = db.execute(
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
    ).all()
    runs = db.scalars(
        select(AgentRun)
        .where(AgentRun.status.in_((AgentRunStatus.SUCCEEDED, AgentRunStatus.FAILED)))
        .order_by(AgentRun.started_at.desc())
        .limit(limit)
    ).all()
    items = [
        Activity(
            at=a.created_at,
            kind="audit",
            action=a.action,
            actor=a.actor_agent or email,
            entity_type=a.entity_type,
            entity_id=a.entity_id,
            status_before=(a.before or {}).get("status"),
            status_after=(a.after or {}).get("status"),
            # login entries carry the client IP; the start page does not show it
            message=None if a.action.startswith("auth.") else a.message,
        )
        for a, email in audits
        if a.action != "auth.login_failed"
    ] + [
        Activity(
            at=r.finished_at or r.started_at,
            kind="agent",
            action=f"agent.{r.status.value}",
            actor=r.agent_name,
            entity_type=None,
            entity_id=None,
            message=(r.error or "")[:300] or None,
        )
        for r in runs
    ]
    return sorted(items, key=lambda i: i.at, reverse=True)[:limit]


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(_: Viewer, db: DbSession, settings: AppSettings, redis: RedisDep) -> DashboardOut:
    """Everything the start page shows, in one request (refreshed by the dashboard)."""
    rows = db.execute(select(Variant.status, func.count()).group_by(Variant.status))
    by_status: dict[VideoStatus, int] = {status: n for status, n in rows}
    uploading = (
        db.scalar(
            select(func.count(PublishingJob.id)).where(
                PublishingJob.status == PublishingJobStatus.RUNNING
            )
        )
        or 0
    )
    states = [
        StateCount(key=key, count=sum(by_status.get(s, 0) for s in statuses))
        for key, statuses in _DASHBOARD_STATES.items()
    ]
    states.insert(4, StateCount(key="uploading", count=int(uploading)))
    count = {s.key: s.count for s in states}
    total = sum(n for s, n in by_status.items() if s != VideoStatus.ARCHIVED)
    return DashboardOut(
        videos_total=total,
        published=count["published"],
        scheduled=count["scheduled"],
        unpublished=count["draft"] + count["in_progress"] + count["ready"] + count["scheduled"],
        failed=count["failed"],
        states=states,
        platforms=_tiles(db, settings, redis),
        recent_posts=_recent_posts(db),
        failures=_failures(db),
        activity=_activity(db),
        controls=effective_controls(db, settings),
    )
