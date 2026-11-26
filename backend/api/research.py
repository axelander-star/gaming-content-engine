"""Research feeds and the idea lab (extension phase E5)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from api.deps import Admin, AppSettings, DbSession, Operator, Viewer, csrf_protect
from core.enums import AgentRunStatus, ContentProjectStatus, IdeaStatus
from models.control import AgentRun
from models.projects import ContentProject
from models.research import Idea, ResearchItem, ResearchSource
from services import agent_control, audit, ideas, planning
from services.controls import effective_controls
from services.orchestrator import submit
from services.queue import get_redis

router = APIRouter(tags=["research"], dependencies=[Depends(csrf_protect)])


# --- sources -------------------------------------------------------------------------


class SourceOut(BaseModel):
    id: int
    content_project_id: int
    project: str
    name: str
    url: str
    enabled: bool
    last_fetched_at: datetime | None
    last_status: str | None
    last_error: str | None
    last_item_count: int
    items: int


class SourcesOut(BaseModel):
    mode: Literal["mock", "live"]
    sources: list[SourceOut]


class SourceIn(BaseModel):
    content_project_id: int
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=8, max_length=1000)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        parts = urlsplit(v)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("Nur http- und https-Adressen")
        if parts.username or parts.password:
            raise ValueError("Keine Zugangsdaten in der Adresse")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return " ".join(v.split())


class SourcePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None


def _source_out(s: ResearchSource, project: str, items: int) -> SourceOut:
    return SourceOut(
        id=s.id,
        content_project_id=s.content_project_id,
        project=project,
        name=s.name,
        url=s.url,
        enabled=s.enabled,
        last_fetched_at=s.last_fetched_at,
        last_status=s.last_status,
        last_error=s.last_error,
        last_item_count=s.last_item_count,
        items=items,
    )


def _item_counts(db: DbSession) -> dict[int, int]:
    rows = db.execute(
        select(ResearchItem.source_id, func.count(ResearchItem.id))
        .where(ResearchItem.source_id.is_not(None))
        .group_by(ResearchItem.source_id)
    ).all()
    return {int(sid): int(n) for sid, n in rows if sid is not None}


def _source(db: DbSession, source_id: int) -> ResearchSource:
    source = db.get(ResearchSource, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Quelle nicht gefunden")
    return source


def _project_name(db: DbSession, project_id: int) -> str:
    project = db.get(ContentProject, project_id)
    return project.name if project else "?"


@router.get("/research/sources", response_model=SourcesOut)
def list_sources(
    _: Viewer, db: DbSession, settings: AppSettings, project_id: int | None = None
) -> SourcesOut:
    query = (
        select(ResearchSource, ContentProject.name)
        .join(ContentProject, ContentProject.id == ResearchSource.content_project_id)
        .order_by(ContentProject.priority, ContentProject.id, ResearchSource.id)
    )
    if project_id is not None:
        query = query.where(ResearchSource.content_project_id == project_id)
    counts = _item_counts(db)
    return SourcesOut(
        mode=settings.research_sources_mode,
        sources=[_source_out(s, name, counts.get(s.id, 0)) for s, name in db.execute(query)],
    )


@router.post("/research/sources", response_model=SourceOut, status_code=201)
def create_source(body: SourceIn, admin: Admin, db: DbSession) -> SourceOut:
    project = db.get(ContentProject, body.content_project_id)
    if project is None or project.status == ContentProjectStatus.ARCHIVED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Themenbereich nicht gefunden")
    source = ResearchSource(content_project_id=project.id, name=body.name, url=body.url)
    db.add(source)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Diese Quelle gibt es im Themenbereich schon"
        ) from None
    audit.record(db, "research.source_created", user_id=admin.id, entity_type="research_sources",
                 entity_id=source.id, after={"name": source.name, "url": source.url,
                                             "project": project.name})  # fmt: skip
    db.commit()
    db.refresh(source)
    return _source_out(source, project.name, 0)


@router.patch("/research/sources/{source_id}", response_model=SourceOut)
def update_source(source_id: int, body: SourcePatch, admin: Admin, db: DbSession) -> SourceOut:
    source = _source(db, source_id)
    before = {"name": source.name, "enabled": source.enabled}
    if body.name is not None:
        source.name = " ".join(body.name.split())
    if body.enabled is not None:
        source.enabled = body.enabled
    audit.record(db, "research.source_updated", user_id=admin.id, entity_type="research_sources",
                 entity_id=source.id, before=before,
                 after={"name": source.name, "enabled": source.enabled})  # fmt: skip
    db.commit()
    db.refresh(source)
    return _source_out(
        source, _project_name(db, source.content_project_id), _item_counts(db).get(source.id, 0)
    )


@router.delete("/research/sources/{source_id}", status_code=204)
def delete_source(source_id: int, admin: Admin, db: DbSession) -> None:
    source = _source(db, source_id)
    audit.record(db, "research.source_deleted", user_id=admin.id, entity_type="research_sources",
                 entity_id=source.id, before={"name": source.name, "url": source.url})  # fmt: skip
    db.delete(source)
    db.commit()


# --- items and runs ------------------------------------------------------------------


class ItemOut(BaseModel):
    id: int
    content_project_id: int
    source: str | None
    title: str
    url: str | None
    summary: str | None
    published_at: datetime | None
    fetched_at: datetime
    is_mock: bool
    used: bool


@router.get("/research/items", response_model=list[ItemOut])
def list_items(
    _: Viewer,
    db: DbSession,
    project_id: int | None = None,
    limit: int = Query(default=30, ge=1, le=200),
) -> list[ItemOut]:
    query = (
        select(ResearchItem, ResearchSource.name)
        .outerjoin(ResearchSource, ResearchSource.id == ResearchItem.source_id)
        .order_by(ResearchItem.fetched_at.desc(), ResearchItem.id.desc())
        .limit(limit)
    )
    if project_id is not None:
        query = query.where(ResearchItem.content_project_id == project_id)
    return [
        ItemOut(
            id=i.id,
            content_project_id=i.content_project_id,
            source=name or ("Beispiel-Feed" if i.is_mock else None),
            title=i.title,
            url=i.url,
            summary=i.summary,
            published_at=i.published_at,
            fetched_at=i.fetched_at,
            is_mock=i.is_mock,
            used=i.used_at is not None,
        )
        for i, name in db.execute(query)
    ]


class RunIn(BaseModel):
    project_id: int | None = None
    ideas: bool = True


class RunOut(BaseModel):
    jobs: dict[str, str]


def start_research(
    db: DbSession, redis: Redis, project_id: int | None, with_ideas: bool, settings: Any
) -> dict[str, str]:
    """Queue research (and the idea lab) like a manual agent run; raises HTTP errors."""
    if effective_controls(db, settings).emergency_stop:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Not-Aus ist aktiv")
    names = ["research", "idea_lab"] if with_ideas else ["research"]
    paused = [n for n in names if not agent_control.is_enabled(db, n)]
    if paused:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Agent pausiert: {', '.join(paused)}")
    payload: dict[str, Any] = {} if project_id is None else {"project_id": project_id}
    return {n: submit(n, payload, priority=True, connection=redis).id for n in names}


@router.post("/research/run", response_model=RunOut)
def run_research(
    body: RunIn,
    admin: Admin,
    db: DbSession,
    settings: AppSettings,
    redis: Annotated[Redis, Depends(get_redis)],
) -> RunOut:
    if body.project_id is not None:
        project = db.get(ContentProject, body.project_id)
        if project is None or project.status != ContentProjectStatus.ACTIVE:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Themenbereich ist nicht aktiv")
    jobs = start_research(db, redis, body.project_id, body.ideas, settings)
    # remembered so the page can show progress after the operator left and came back
    redis.set(
        MANUAL_RUN_KEY,
        json.dumps(
            {
                "started_at": datetime.now(UTC).isoformat(),
                "project_id": body.project_id,
                "agents": list(jobs),
            }
        ),
        ex=int(MANUAL_RUN_TTL.total_seconds()),
    )
    audit.record(db, "research.run_manual", user_id=admin.id, entity_type="agents",
                 after={"project_id": body.project_id, "jobs": jobs})  # fmt: skip
    db.commit()
    return RunOut(jobs=jobs)


MANUAL_RUN_KEY = "research:manual_run"
MANUAL_RUN_TTL = timedelta(hours=6)
#: a queued step that never started within this time is reported as stuck
STUCK_AFTER = timedelta(minutes=20)


class RunStep(BaseModel):
    agent: str
    state: Literal["queued", "running", "done", "failed", "skipped"]
    detail: str | None = None


class RunStatusOut(BaseModel):
    state: Literal["idle", "running", "done", "stuck"]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    project_id: int | None = None
    steps: list[RunStep] = []
    new_items: int = 0
    new_ideas: int = 0


def _step(agent: str, run: AgentRun | None) -> RunStep:
    if run is None:
        return RunStep(agent=agent, state="queued")
    if run.status == AgentRunStatus.RUNNING:
        return RunStep(agent=agent, state="running")
    if run.status == AgentRunStatus.SUCCEEDED:
        return RunStep(agent=agent, state="done")
    if run.status == AgentRunStatus.SKIPPED:
        reason = (run.output or {}).get("reason") or run.error
        return RunStep(agent=agent, state="skipped", detail=str(reason or "")[:300] or None)
    return RunStep(agent=agent, state="failed", detail=(run.error or "")[:300] or None)


@router.get("/research/status", response_model=RunStatusOut)
def research_status(
    _: Viewer, db: DbSession, redis: Annotated[Redis, Depends(get_redis)]
) -> RunStatusOut:
    """Progress of the last manual research run (survives leaving the page)."""
    raw = redis.get(MANUAL_RUN_KEY)
    if not raw:
        return RunStatusOut(state="idle")
    try:
        data = json.loads(raw)
        started = datetime.fromisoformat(data["started_at"])
        agents = [str(a) for a in data.get("agents") or []]
        project_id = data.get("project_id")
    except (ValueError, KeyError, TypeError):
        return RunStatusOut(state="idle")
    # the first run of each agent that started after the button was pressed
    since = started - timedelta(seconds=5)
    steps: list[RunStep] = []
    runs: list[AgentRun] = []
    for agent in agents:
        run = db.scalar(
            select(AgentRun)
            .where(AgentRun.agent_name == agent, AgentRun.started_at >= since)
            .order_by(AgentRun.id)
            .limit(1)
        )
        steps.append(_step(agent, run))
        if run is not None:
            runs.append(run)
    open_steps = [s for s in steps if s.state in ("queued", "running")]
    state: Literal["idle", "running", "done", "stuck"] = "running" if open_steps else "done"
    waiting = all(s.state == "queued" for s in open_steps)
    if state == "running" and waiting and datetime.now(UTC) - started > STUCK_AFTER:
        state = "stuck"
    new_items = 0
    for run in runs:
        if run.agent_name == "research":
            new_items = sum(
                int(p.get("new_items") or 0)
                for p in (run.output or {}).get("projects") or []
                if isinstance(p, dict)
            )
    ideas_query = select(func.count()).select_from(Idea).where(Idea.created_at >= since)
    if isinstance(project_id, int):
        ideas_query = ideas_query.where(Idea.content_project_id == project_id)
    finished = [r.finished_at for r in runs if r.finished_at is not None]
    return RunStatusOut(
        state=state,
        started_at=started,
        finished_at=max(finished) if state == "done" and finished else None,
        project_id=project_id if isinstance(project_id, int) else None,
        steps=steps,
        new_items=new_items,
        new_ideas=int(db.scalar(ideas_query) or 0),
    )


# --- ideas ---------------------------------------------------------------------------


class IdeaSourceOut(BaseModel):
    item_id: int | None = None
    title: str
    url: str | None = None


class IdeaOut(BaseModel):
    id: int
    created_at: datetime
    content_project_id: int
    project: str
    title: str
    pitch: str
    format: str
    sources: list[IdeaSourceOut]
    trend_score: int
    fit_score: int
    effort_score: int
    rights_risk: int
    score: int
    reasoning: str
    status: IdeaStatus
    provider: str
    planned_for: date | None
    decided_at: datetime | None


def _idea_out(i: Idea, project: str) -> IdeaOut:
    return IdeaOut(
        id=i.id,
        created_at=i.created_at,
        content_project_id=i.content_project_id,
        project=project,
        title=i.title,
        pitch=i.pitch,
        format=i.format,
        sources=[IdeaSourceOut.model_validate(s) for s in i.sources or []],
        trend_score=i.trend_score,
        fit_score=i.fit_score,
        effort_score=i.effort_score,
        rights_risk=i.rights_risk,
        score=i.score,
        reasoning=i.reasoning,
        status=i.status,
        provider=i.provider,
        planned_for=i.planned_for,
        decided_at=i.decided_at,
    )


@router.get("/ideas", response_model=list[IdeaOut])
def list_ideas(
    _: Viewer,
    db: DbSession,
    project_id: int | None = None,
    status_: Annotated[IdeaStatus | None, Query(alias="status")] = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[IdeaOut]:
    query = select(Idea, ContentProject.name).join(
        ContentProject, ContentProject.id == Idea.content_project_id
    )
    if project_id is not None:
        query = query.where(Idea.content_project_id == project_id)
    if status_ is not None:
        query = query.where(Idea.status == status_)
    query = query.order_by(Idea.created_at.desc(), Idea.score.desc(), Idea.id.desc()).limit(limit)
    return [_idea_out(i, name) for i, name in db.execute(query)]


IdeaSort = Literal["score", "trend", "title", "newest", "oldest", "fit"]
_SORTS: dict[str, tuple[Any, ...]] = {
    "score": (Idea.score.desc(), Idea.created_at.desc()),
    "trend": (Idea.trend_score.desc(), Idea.score.desc()),
    "fit": (Idea.fit_score.desc(), Idea.score.desc()),
    "title": (func.lower(Idea.title).asc(),),
    "newest": (Idea.created_at.desc(), Idea.score.desc()),
    "oldest": (Idea.created_at.asc(), Idea.score.desc()),
}


class IdeaPageOut(BaseModel):
    total: int
    offset: int
    limit: int
    sort: IdeaSort
    items: list[IdeaOut]


@router.get("/ideas/page", response_model=IdeaPageOut)
def page_ideas(
    _: Viewer,
    db: DbSession,
    project_id: int | None = None,
    status_: Annotated[IdeaStatus | None, Query(alias="status")] = None,
    sort: IdeaSort = "score",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=5, ge=1, le=50),
) -> IdeaPageOut:
    """One page of ideas, sorted on the server (default: best ranking first)."""
    filters = []
    if project_id is not None:
        filters.append(Idea.content_project_id == project_id)
    if status_ is not None:
        filters.append(Idea.status == status_)
    total = int(db.scalar(select(func.count(Idea.id)).where(*filters)) or 0)
    query = (
        select(Idea, ContentProject.name)
        .join(ContentProject, ContentProject.id == Idea.content_project_id)
        .where(*filters)
        .order_by(*_SORTS[sort], Idea.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return IdeaPageOut(
        total=total,
        offset=offset,
        limit=limit,
        sort=sort,
        items=[_idea_out(i, name) for i, name in db.execute(query)],
    )


class AcceptIn(BaseModel):
    day: date | None = None


def _idea(db: DbSession, idea_id: int) -> Idea:
    idea = db.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Idee nicht gefunden")
    return idea


def _decided(db: DbSession, idea: Idea, action: str, user_id: int) -> IdeaOut:
    audit.record(db, f"idea.{action}", user_id=user_id, entity_type="ideas", entity_id=idea.id,
                 after={"status": idea.status.value, "planned_for": str(idea.planned_for)
                        if idea.planned_for else None, "title": idea.title})  # fmt: skip
    db.commit()
    db.refresh(idea)
    return _idea_out(idea, _project_name(db, idea.content_project_id))


@router.post("/ideas/{idea_id}/accept", response_model=IdeaOut)
def accept_idea(
    idea_id: int, body: AcceptIn, user: Operator, db: DbSession, settings: AppSettings
) -> IdeaOut:
    idea = _idea(db, idea_id)
    try:
        ideas.accept(db, settings, idea, user.id, body.day)
    except (ideas.IdeaError, planning.PlanningError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _decided(db, idea, "accepted", user.id)


@router.post("/ideas/{idea_id}/reject", response_model=IdeaOut)
def reject_idea(idea_id: int, user: Operator, db: DbSession) -> IdeaOut:
    idea = _idea(db, idea_id)
    try:
        ideas.reject(db, idea, user.id)
    except ideas.IdeaError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _decided(db, idea, "rejected", user.id)


@router.post("/ideas/{idea_id}/reopen", response_model=IdeaOut)
def reopen_idea(idea_id: int, user: Operator, db: DbSession) -> IdeaOut:
    idea = _idea(db, idea_id)
    try:
        ideas.reopen(db, idea)
    except ideas.IdeaError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _decided(db, idea, "reopened", user.id)
