"""Dashboard overview: counts that already exist in the data model.

Views, costs, trends and best performers follow with the phases that produce
those data (analytics, budget, trend research).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from api.deps import AppSettings, DbSession, Viewer
from core.enums import VideoStatus
from models.channels import Channel
from models.production import Variant
from models.publishing import Post
from services.controls import EffectiveControls, effective_controls

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

    channels_total = db.scalar(select(func.count()).select_from(Channel)) or 0
    channels_active = (
        db.scalar(select(func.count()).select_from(Channel).where(Channel.is_paused.is_(False)))
        or 0
    )
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
