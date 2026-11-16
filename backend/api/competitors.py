"""Competitor radar (Ausbau A5): channels to watch and their stand-out videos."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy import select

from api.deps import AppSettings, DbSession, Operator, Viewer, csrf_protect
from core.enums import ContentProjectStatus
from models.competitors import Competitor, CompetitorVideo
from models.projects import ContentProject
from services import agent_control, audit, competitors
from services.controls import effective_controls
from services.orchestrator import submit
from services.queue import get_redis

router = APIRouter(
    prefix="/competitors", tags=["competitors"], dependencies=[Depends(csrf_protect)]
)


class CompetitorOut(BaseModel):
    id: int
    project_id: int
    project: str
    handle: str
    name: str | None
    url: str
    last_checked_at: datetime | None
    last_error: str | None
    videos: int
    standouts: int


class VideoOut(BaseModel):
    id: int
    competitor_id: int
    channel: str
    project_id: int
    title: str
    url: str | None
    published_at: datetime | None
    views: int
    likes: int | None
    comments: int | None
    outlier: float | None
    is_mock: bool
    in_idea_lab: bool


class RadarOut(BaseModel):
    live: bool
    competitors: list[CompetitorOut]
    standouts: list[VideoOut]


class CompetitorIn(BaseModel):
    project_id: int
    handle: str = Field(min_length=2, max_length=200)


class RunOut(BaseModel):
    job_id: str | None


def _video(v: CompetitorVideo, c: Competitor) -> VideoOut:
    return VideoOut(
        id=v.id,
        competitor_id=c.id,
        channel=c.name or c.handle,
        project_id=c.content_project_id,
        title=v.title,
        url=v.url,
        published_at=v.published_at,
        views=v.views,
        likes=v.likes,
        comments=v.comments,
        outlier=v.outlier,
        is_mock=v.is_mock,
        in_idea_lab=v.research_item_id is not None,
    )


@router.get("", response_model=RadarOut)
def radar(
    _: Viewer, db: DbSession, settings: AppSettings, project_id: int | None = Query(default=None)
) -> RadarOut:
    q = (
        select(Competitor, ContentProject.name)
        .join(ContentProject, ContentProject.id == Competitor.content_project_id)
        .where(Competitor.active.is_(True))
        .order_by(ContentProject.priority, Competitor.id)
    )
    if project_id is not None:
        q = q.where(Competitor.content_project_id == project_id)
    rows = [(c, name) for c, name in db.execute(q).all()]
    counts: dict[int, tuple[int, int]] = {}
    for c, _name in rows:
        vids = list(
            db.scalars(select(CompetitorVideo.outlier).where(CompetitorVideo.competitor_id == c.id))
        )
        counts[c.id] = (len(vids), sum(1 for o in vids if o and o >= competitors.OUTLIER_FACTOR))
    return RadarOut(
        live=competitors.live(settings),
        competitors=[
            CompetitorOut(
                id=c.id,
                project_id=c.content_project_id,
                project=name,
                handle=c.handle,
                name=c.name,
                url=f"https://www.youtube.com/{c.handle}",
                last_checked_at=c.last_checked_at,
                last_error=c.last_error,
                videos=counts[c.id][0],
                standouts=counts[c.id][1],
            )
            for c, name in rows
        ],
        standouts=[_video(v, c) for v, c in competitors.standouts(db, project_id)],
    )


@router.post("", response_model=CompetitorOut, status_code=201)
def add_competitor(body: CompetitorIn, user: Operator, db: DbSession) -> CompetitorOut:
    project = db.get(ContentProject, body.project_id)
    if project is None or project.status == ContentProjectStatus.ARCHIVED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Themenbereich nicht gefunden")
    try:
        comp = competitors.add(db, project, body.handle, user.id)
    except competitors.RadarError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    audit.record(db, "competitor.added", user_id=user.id, entity_type="competitors",
                 entity_id=comp.id,
                 after={"handle": comp.handle, "project": project.name})  # fmt: skip
    db.commit()
    return CompetitorOut(
        id=comp.id, project_id=project.id, project=project.name, handle=comp.handle,
        name=comp.name, url=f"https://www.youtube.com/{comp.handle}",
        last_checked_at=comp.last_checked_at, last_error=comp.last_error, videos=0, standouts=0,
    )  # fmt: skip


@router.delete("/{competitor_id}", status_code=204)
def remove_competitor(competitor_id: int, user: Operator, db: DbSession) -> None:
    comp = db.get(Competitor, competitor_id)
    if comp is None or not comp.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Kanal nicht gefunden")
    comp.active = False
    audit.record(db, "competitor.removed", user_id=user.id, entity_type="competitors",
                 entity_id=comp.id, before={"handle": comp.handle})  # fmt: skip
    db.commit()


@router.post("/run", response_model=RunOut)
def run_now(
    _: Operator,
    db: DbSession,
    settings: AppSettings,
    redis: Annotated[Redis, Depends(get_redis)],
) -> RunOut:
    if effective_controls(db, settings).emergency_stop:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Not-Aus ist aktiv")
    if not agent_control.is_enabled(db, "competitor_radar"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Agent Competitor Radar ist pausiert")
    job = submit("competitor_radar", {}, priority=True, connection=redis)
    return RunOut(job_id=job.id)
