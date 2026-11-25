"""Video series: one big topic as many short parts, released over days (own production).

Nothing here publishes. ``prepare`` creates posts in the approval center; with
``approve`` the person releases all parts in one go and the Publishing Strategy
Agent then schedules them in order at a pace decided from the data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import AppSettings, DbSession, Operator, Viewer, csrf_protect
from api.library import BUSY, ProductionOut, _prod_out, _project, _project_names
from core.enums import ContentProjectStatus, IdeaStatus, Language, ProductionStatus, VideoStatus
from models.channels import Channel
from models.library import OwnProduction, ProductionSeries
from models.production import Variant
from models.research import Idea
from services import ai, approval, audit, own_production, series
from services.controls import effective_controls
from services.orchestrator import submit
from services.queue import get_redis

router = APIRouter(tags=["series"], dependencies=[Depends(csrf_protect)])


class SeriesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int
    topic: str | None = Field(default=None, max_length=300)
    pitch: str | None = Field(default=None, max_length=2000)
    idea_id: int | None = None
    language: Language = Language.DE
    #: Number of parts; or ``total_minutes``; neither = the AI decides.
    parts: int | None = Field(default=None, ge=series.MIN_PARTS, le=series.MAX_PARTS)
    total_minutes: float | None = Field(default=None, gt=0, le=120)
    part_seconds: int = Field(default=series.DEFAULT_PART_S, ge=series.MIN_PART_S,
                              le=series.MAX_PART_S)  # fmt: skip


class SeriesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    paused: bool | None = None


class PartChannel(BaseModel):
    channel_id: int
    channel: str
    variant_id: int
    status: VideoStatus


class SeriesPart(BaseModel):
    part: int
    production: ProductionOut
    posts: list[PartChannel]


class SeriesOut(BaseModel):
    id: int
    project_id: int
    project: str
    idea_id: int | None
    title: str
    topic: str
    pitch: str | None
    language: Language
    part_seconds: int
    outline: list[dict[str, Any]]
    script_source: str
    paused: bool
    created_at: datetime
    counts: dict[str, int]
    parts: list[SeriesPart]


def _series(db: Session, series_id: int) -> ProductionSeries:
    row = db.get(ProductionSeries, series_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Serie nicht gefunden")
    return row


def _out(db: Session, row: ProductionSeries) -> SeriesOut:
    prods = series.parts(db, row.id)
    items = [p.output_item_id for p in prods if p.output_item_id is not None]
    posts: dict[int, list[PartChannel]] = {}
    if items:
        for variant, name in db.execute(
            select(Variant, Channel.name)
            .join(Channel, Channel.id == Variant.channel_id)
            .where(Variant.library_item_id.in_(items))
            .order_by(Channel.name)
        ):
            assert variant.library_item_id is not None
            posts.setdefault(variant.library_item_id, []).append(
                PartChannel(
                    channel_id=variant.channel_id,
                    channel=name,
                    variant_id=variant.id,
                    status=variant.status,
                )
            )
    parts = [
        SeriesPart(
            part=p.series_part or 0,
            production=_prod_out(db, p),
            posts=posts.get(p.output_item_id or 0, []),
        )
        for p in prods
    ]
    all_posts = [c for part in parts for c in part.posts]
    counts = {
        "parts": len(prods),
        "scripted": sum(1 for p in prods if p.script_source != "pending"),
        "rendering": sum(1 for p in prods if p.status in BUSY),
        "done": sum(1 for p in prods if p.status == ProductionStatus.DONE),
        "failed": sum(1 for p in prods if p.status == ProductionStatus.FAILED),
        "prepared": sum(1 for part in parts if part.posts),
        "approved": sum(
            1
            for c in all_posts
            if c.status not in (VideoStatus.QUALITY_APPROVED, VideoStatus.FAILED)
        ),
        "scheduled": sum(1 for c in all_posts if c.status == VideoStatus.SCHEDULED),
        "published": sum(1 for c in all_posts if c.status in series.PUBLISHED_STATES),
    }
    project = row.content_project_id
    return SeriesOut(
        id=row.id,
        project_id=project,
        project=_project_names(db).get(project, "?"),
        idea_id=row.idea_id,
        title=row.title,
        topic=row.topic,
        pitch=row.pitch,
        language=row.language,
        part_seconds=row.part_seconds,
        outline=list(row.outline or []),
        script_source=row.script_source,
        paused=row.paused,
        created_at=row.created_at,
        counts=counts,
        parts=parts,
    )


def _ai_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, ai.AIBlockedError):
        return HTTPException(status.HTTP_409_CONFLICT, detail=f"KI nicht verfügbar: {exc.reason}")
    return HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.get("/series", response_model=list[SeriesOut])
def list_series(
    _: Viewer, db: DbSession, project_id: int | None = Query(default=None)
) -> list[SeriesOut]:
    query = select(ProductionSeries).order_by(ProductionSeries.id.desc()).limit(50)
    if project_id is not None:
        query = query.where(ProductionSeries.content_project_id == project_id)
    return [_out(db, row) for row in db.scalars(query)]


class Suggestion(BaseModel):
    title: str
    pitch: str
    parts: int
    reason: str
    source: str | None
    idea_id: int | None


@router.get("/series/suggestions", response_model=list[Suggestion])
def series_suggestions(
    _: Viewer,
    db: DbSession,
    settings: AppSettings,
    project_id: int = Query(),
    language: Annotated[Language, Query()] = Language.DE,
) -> list[dict[str, Any]]:
    """Ideas for new series from the area's own data (ideas lab, plan focus); no AI call."""
    project = _project(db, project_id, active=False)
    return series.suggestions(db, settings, project, language)


@router.post("/series/suggestions", response_model=list[Suggestion])
def series_ai_suggestions(
    user: Operator,
    db: DbSession,
    settings: AppSettings,
    project_id: int = Query(),
    language: Annotated[Language, Query()] = Language.DE,
) -> list[dict[str, Any]]:
    """Fresh ideas from the AI layer (mock unless Claude is released and in budget)."""
    project = _project(db, project_id, active=False)
    try:
        out = series.ai_suggestions(db, settings, project, language, user.id)
    except series.SeriesError as exc:
        raise HTTPException(exc.status, detail=exc.detail) from exc
    except (ai.AIBlockedError, ai.AIRefusedError, ai.AIFailedError) as exc:
        db.commit()  # keep the call log
        raise _ai_errors(exc) from exc
    db.commit()
    return out


@router.get("/series/{series_id}", response_model=SeriesOut)
def get_series(series_id: int, _: Viewer, db: DbSession) -> SeriesOut:
    return _out(db, _series(db, series_id))


@router.post("/series", response_model=SeriesOut, status_code=201)
def create_series(
    body: SeriesIn, user: Operator, db: DbSession, settings: AppSettings
) -> SeriesOut:
    project = _project(db, body.project_id)
    idea: Idea | None = None
    if body.idea_id is not None:
        idea = db.get(Idea, body.idea_id)
        if idea is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Idee nicht gefunden")
        if idea.content_project_id != project.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="Die Idee gehört zu einem anderen Themenbereich"
            )
        if idea.status == IdeaStatus.REJECTED:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Die Idee wurde verworfen")
    topic = body.topic or (idea.title if idea else "")
    pitch = body.pitch or (idea.pitch if idea else "")
    wanted = series.part_count(body.parts, body.total_minutes, body.part_seconds)
    try:
        row = series.create(
            db, settings, project, topic=topic, pitch=pitch, language=body.language,
            parts=wanted, part_seconds=body.part_seconds,
            idea_id=idea.id if idea else None, user_id=user.id,
        )  # fmt: skip
    except series.SeriesError as exc:
        db.rollback()
        raise HTTPException(exc.status, detail=exc.detail) from exc
    except (ai.AIBlockedError, ai.AIRefusedError, ai.AIFailedError) as exc:
        db.commit()
        raise _ai_errors(exc) from exc
    audit.record(
        db,
        "series.created",
        user_id=user.id,
        entity_type="production_series",
        entity_id=row.id,
        after={"title": row.title, "parts": len(row.outline), "script": row.script_source},
    )
    db.commit()
    return _out(db, row)


class ScriptsOut(BaseModel):
    series: SeriesOut
    remaining: int


@router.post("/series/{series_id}/scripts", response_model=ScriptsOut)
def write_scripts(
    series_id: int, user: Operator, db: DbSession, settings: AppSettings
) -> ScriptsOut:
    """Writes the next few part scripts; call again until ``remaining`` is 0."""
    row = _series(db, series_id)
    try:
        remaining = series.write_scripts(db, settings, row, user.id)
    except own_production.ProductionError as exc:
        db.commit()
        raise HTTPException(exc.status, detail=exc.detail) from exc
    except (ai.AIBlockedError, ai.AIRefusedError, ai.AIFailedError) as exc:
        db.commit()
        raise _ai_errors(exc) from exc
    db.commit()
    return ScriptsOut(series=_out(db, row), remaining=remaining)


class RenderOut(BaseModel):
    series: SeriesOut
    queued: int


@router.post("/series/{series_id}/render", response_model=RenderOut)
def render_series(
    series_id: int,
    user: Operator,
    db: DbSession,
    settings: AppSettings,
    redis: Annotated[Redis, Depends(get_redis)],
) -> RenderOut:
    """Queue every part that has a script and no finished video yet."""
    if effective_controls(db, settings).emergency_stop:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Not-Aus ist aktiv")
    row = _series(db, series_id)
    _project(db, row.content_project_id)
    prods = series.parts(db, row.id, lock=True)
    if any(p.script_source == "pending" for p in prods):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Erst alle Skripte schreiben")
    todo = [p for p in prods if p.status in (ProductionStatus.DRAFT, ProductionStatus.FAILED)]
    for prod in todo:
        try:
            own_production.check_images(db, prod.content_project_id, prod.segments)
        except own_production.ProductionError as exc:
            raise HTTPException(
                exc.status, detail=f"Teil {prod.series_part}: {exc.detail}"
            ) from exc
        prod.status = ProductionStatus.QUEUED
        prod.error_message = None
    audit.record(
        db,
        "series.render",
        user_id=user.id,
        entity_type="production_series",
        entity_id=row.id,
        after={"queued": len(todo)},
    )
    db.commit()
    failed: list[OwnProduction] = []
    for prod in todo:
        try:
            submit("own_production", {"entity_type": "own_productions", "entity_id": prod.id},
                   priority=False, connection=redis)  # fmt: skip
        except Exception:
            failed.append(prod)
    if failed:
        for prod in failed:
            prod.status = ProductionStatus.DRAFT
        db.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="Warteschlange nicht erreichbar"
        )
    return RenderOut(series=_out(db, row), queued=len(todo))


class PrepareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Empty = every channel of the area in the series language.
    channel_ids: list[int] = Field(default_factory=list, max_length=20)
    #: Release all prepared parts right away (the person's approval).
    approve: bool = False


class PrepareOut(BaseModel):
    series: SeriesOut
    prepared: int
    approved: int
    skipped: list[str]


@router.post("/series/{series_id}/prepare", response_model=PrepareOut)
def prepare_series(
    series_id: int, body: PrepareIn, user: Operator, db: DbSession, settings: AppSettings
) -> PrepareOut:
    """Every finished part becomes a post per channel; ``approve`` releases them all."""
    row = _series(db, series_id)
    project = _project(db, row.content_project_id)
    if project.status != ContentProjectStatus.ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"{project.name} ist pausiert")
    channels = list(
        db.scalars(
            select(Channel)
            .where(Channel.content_project_id == row.content_project_id)
            .order_by(Channel.id)
        )
    )
    if body.channel_ids:
        wanted = set(body.channel_ids)
        channels = [c for c in channels if c.id in wanted]
        if len(channels) != len(wanted):
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="Kanal gehört nicht zu diesem Themenbereich"
            )
    else:
        channels = [
            c for c in channels if c.language == row.language and c.platform.code in approval.RULES
        ]
    if not channels:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Kein passender Kanal in diesem Themenbereich (Sprache der Serie)",
        )
    prods = [p for p in series.parts(db, row.id) if p.status == ProductionStatus.DONE]
    if not prods:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Noch kein Teil fertig gerendert")
    prepared, approved, skipped = 0, 0, []
    try:
        for prod in prods:
            assert prod.output_item_id is not None
            taken = set(
                db.scalars(
                    select(Variant.channel_id).where(Variant.library_item_id == prod.output_item_id)
                )
            )
            open_ids = [c.id for c in channels if c.id not in taken]
            if open_ids:
                try:
                    new = approval.prepare(db, settings, prod.output_item_id, open_ids, user.id,
                                           skip_unfit=True)  # fmt: skip
                except approval.ApprovalError as exc:
                    skipped.append(f"Teil {prod.series_part}: {exc}")
                    continue
                prepared += len(new)
            if body.approve:
                for variant in db.scalars(
                    select(Variant).where(
                        Variant.library_item_id == prod.output_item_id,
                        Variant.channel_id.in_([c.id for c in channels]),
                        Variant.status == VideoStatus.QUALITY_APPROVED,
                    )
                ):
                    try:
                        approval.approve(db, variant, user.id)
                        approved += 1
                    except approval.ApprovalError as exc:
                        skipped.append(f"Teil {prod.series_part}: {exc}")
    except (ai.AIBlockedError, ai.AIRefusedError, ai.AIFailedError) as exc:
        db.rollback()
        raise _ai_errors(exc) from exc
    audit.record(
        db,
        "series.prepared",
        user_id=user.id,
        entity_type="production_series",
        entity_id=row.id,
        after={"prepared": prepared, "approved": approved, "channels": [c.id for c in channels]},
    )
    db.commit()
    return PrepareOut(series=_out(db, row), prepared=prepared, approved=approved,
                      skipped=skipped[:20])  # fmt: skip


class PlanDay(BaseModel):
    day: str
    parts: list[int]
    reasons: list[str]
    fixed: bool


class ChannelPlan(BaseModel):
    channel_id: int
    channel: str
    platform: str
    days: list[PlanDay]


@router.get("/series/{series_id}/plan", response_model=list[ChannelPlan])
def series_plan(
    series_id: int, _: Viewer, db: DbSession, settings: AppSettings
) -> list[ChannelPlan]:
    """Expected release days per channel (assumes today's numbers stay the same)."""
    row = _series(db, series_id)
    channels = db.scalars(
        select(Channel)
        .where(
            Channel.content_project_id == row.content_project_id,
            Channel.language == row.language,
        )
        .order_by(Channel.id)
    )
    out = []
    for channel in channels:
        if channel.platform.code not in approval.RULES:
            continue
        out.append(
            ChannelPlan(
                channel_id=channel.id,
                channel=channel.name,
                platform=channel.platform.name,
                days=[PlanDay(**d) for d in series.preview(db, settings, row, channel)],
            )
        )
    return out


@router.patch("/series/{series_id}", response_model=SeriesOut)
def update_series(series_id: int, body: SeriesPatch, user: Operator, db: DbSession) -> SeriesOut:
    row = _series(db, series_id)
    if body.title is not None:
        row.title = " ".join(body.title.split())
    if body.paused is not None:
        row.paused = body.paused
    audit.record(
        db,
        "series.updated",
        user_id=user.id,
        entity_type="production_series",
        entity_id=row.id,
        after={"title": row.title, "paused": row.paused},
    )
    db.commit()
    return _out(db, row)


@router.delete("/series/{series_id}", status_code=204)
def delete_series(series_id: int, user: Operator, db: DbSession) -> None:
    """Delete the series and its part drafts; finished videos stay in the library."""
    row = _series(db, series_id)
    prods = series.parts(db, row.id, lock=True)
    if any(p.status in BUSY for p in prods):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ein Teil wird gerade gerendert")
    audit.record(
        db,
        "series.deleted",
        user_id=user.id,
        entity_type="production_series",
        entity_id=row.id,
        before={"title": row.title, "parts": len(prods)},
    )
    for prod in prods:
        db.delete(prod)
    db.delete(row)
    db.commit()
