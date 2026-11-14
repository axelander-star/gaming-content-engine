"""Publishing plan and strategy per channel (Phase 11)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from api.deps import Admin, DbSession, Viewer, csrf_protect
from core.enums import PublishingJobStatus, VideoStatus
from models.channels import Channel
from models.production import Variant
from models.publishing import Post, PublishingJob, StrategyVersion
from services import audit, strategy

router = APIRouter(prefix="/publishing", tags=["publishing"], dependencies=[Depends(csrf_protect)])


class VersionOut(BaseModel):
    version: int
    created_at: datetime
    planned_for: date
    posts_per_day: int
    reasons: list[str]
    inputs: dict[str, Any]
    params: dict[str, Any]
    created_by: str
    rolled_back_to: int | None


class JobOut(BaseModel):
    id: int
    variant_id: int
    label: str
    language: str
    title: str | None
    status: PublishingJobStatus
    mode: str
    scheduled_for: datetime | None
    note: str | None
    external_id: str | None = None
    url: str | None = None


class ChannelPlan(BaseModel):
    channel_id: int
    name: str
    platform: str
    language: str
    is_paused: bool
    auth_status: str
    min_posts_per_day: int
    max_posts_per_day: int
    min_interval_minutes: int
    timezone: str
    window: list[int]
    ready: int
    current: VersionOut | None
    history: list[VersionOut]
    jobs: list[JobOut]


def _version(v: StrategyVersion) -> VersionOut:
    return VersionOut(
        version=v.version,
        created_at=v.created_at,
        planned_for=v.planned_for,
        posts_per_day=v.posts_per_day,
        reasons=[str(r) for r in v.reasons or []],
        inputs=v.inputs or {},
        params=v.params or {},
        created_by=v.created_by,
        rolled_back_to=v.rolled_back_to,
    )


@router.get("/plan", response_model=list[ChannelPlan])
def plan(_: Viewer, db: DbSession) -> list[ChannelPlan]:
    channels = db.scalars(
        select(Channel).options(joinedload(Channel.platform)).order_by(Channel.id)
    ).all()
    ready = dict(
        db.execute(
            select(Variant.channel_id, func.count(Variant.id))
            .where(Variant.status == VideoStatus.READY_TO_PUBLISH)
            .group_by(Variant.channel_id)
        ).all()
    )
    since = datetime.now(UTC) - timedelta(days=1)
    jobs: dict[int, list[JobOut]] = {}
    for job, variant, post in db.execute(
        select(PublishingJob, Variant, Post)
        .join(Variant, Variant.id == PublishingJob.variant_id)
        .outerjoin(Post, Post.publishing_job_id == PublishingJob.id)
        .where(PublishingJob.scheduled_for >= since)
        .order_by(PublishingJob.scheduled_for)
        .limit(500)
    ).all():
        jobs.setdefault(job.channel_id, []).append(
            JobOut(
                id=job.id,
                variant_id=variant.id,
                label=variant.variant_label,
                language=variant.language.value,
                title=variant.title,
                status=job.status,
                mode=job.mode.value,
                scheduled_for=job.scheduled_for,
                note=job.last_error,
                external_id=post.external_post_id if post else None,
                url=post.url if post else None,
            )
        )
    out = []
    for c in channels:
        versions = db.scalars(
            select(StrategyVersion)
            .where(StrategyVersion.channel_id == c.id)
            .order_by(StrategyVersion.version.desc())
            .limit(10)
        ).all()
        out.append(
            ChannelPlan(
                channel_id=c.id,
                name=c.name,
                platform=c.platform.code.value,
                language=c.language.value,
                is_paused=c.is_paused or c.platform.is_paused,
                auth_status=c.auth_status.value,
                min_posts_per_day=c.min_posts_per_day,
                max_posts_per_day=c.max_posts_per_day,
                min_interval_minutes=c.min_interval_minutes,
                timezone=str(strategy.timezone_for(c)),
                window=list(strategy.window_for(c)),
                ready=int(ready.get(c.id, 0)),
                current=_version(versions[0]) if versions else None,
                history=[_version(v) for v in versions],
                jobs=jobs.get(c.id, []),
            )
        )
    return out


class RollbackIn(BaseModel):
    version: int = Field(ge=1)


@router.post("/channels/{channel_id}/rollback", response_model=VersionOut)
def rollback(channel_id: int, body: RollbackIn, admin: Admin, db: DbSession) -> VersionOut:
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Channel not found")
    try:
        restored = strategy.rollback(db, channel, body.version, actor=f"user:{admin.id}")
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    audit.record(
        db,
        "strategy.rollback",
        user_id=admin.id,
        entity_type="channels",
        entity_id=channel.id,
        after={"version": restored.version, "restored": body.version},
    )
    db.commit()
    return _version(restored)
