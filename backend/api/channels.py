"""Channels: list, pause/resume (operator) and safety bounds (admin)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from api.deps import Admin, DbSession, Operator, Viewer, csrf_protect
from api.schemas import ChannelOut
from models.channels import Channel
from services import audit

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


def _out(channel: Channel) -> ChannelOut:
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
    return [_out(c) for c in rows]


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
