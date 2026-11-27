"""Content projects (topic areas): list, create, edit, pause/archive, delete.

Every channel and every piece of content belongs to exactly one project; see
``services/projects.py`` for the guard that keeps content on its project's
channels.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from api.deps import Admin, AppSettings, DbSession, Viewer, csrf_protect
from core.enums import ContentProjectStatus, Language
from models.channels import Channel
from models.production import GameplayFile, Variant
from models.projects import DEFAULT_PROJECT_SLUG, ContentProject
from models.publishing import Post
from services import audit, project_delete, projects, topic_suggest
from services.queue import get_redis

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[Depends(csrf_protect)])


def _clean_topics(values: list[str]) -> list[str]:
    seen: list[str] = []
    for raw in values:
        topic = " ".join(raw.split())
        if not topic:
            continue
        if len(topic) > 80:
            raise ValueError("sub-topics have at most 80 characters")
        if topic.casefold() not in (t.casefold() for t in seen):
            seen.append(topic)
    return seen


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    languages: list[Language] = Field(default_factory=lambda: [Language.DE], min_length=1)
    audience: str | None = Field(default=None, max_length=1000)
    tone: str | None = Field(default=None, max_length=1000)
    subtopics: list[str] = Field(default_factory=list, max_length=50)
    priority: int = Field(default=100, ge=0, le=1000)

    @field_validator("subtopics")
    @classmethod
    def _topics(cls, v: list[str]) -> list[str]:
        return _clean_topics(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        name = " ".join(v.split())
        if not name:
            raise ValueError("name must not be empty")
        return name


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    languages: list[Language] | None = Field(default=None, min_length=1)
    audience: str | None = Field(default=None, max_length=1000)
    tone: str | None = Field(default=None, max_length=1000)
    subtopics: list[str] | None = Field(default=None, max_length=50)
    priority: int | None = Field(default=None, ge=0, le=1000)
    status: ContentProjectStatus | None = None

    @field_validator("subtopics")
    @classmethod
    def _topics(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _clean_topics(v)


class ProjectOut(BaseModel):
    id: int
    slug: str
    name: str
    description: str | None
    languages: list[Language]
    audience: str | None
    tone: str | None
    subtopics: list[str]
    priority: int
    status: ContentProjectStatus
    is_default: bool
    channels: int
    materials: int
    videos: int
    published: int
    created_at: datetime


def _counts(
    db: DbSession, model: type[Channel] | type[GameplayFile] | type[Variant]
) -> dict[int, int]:
    rows = db.execute(
        select(model.content_project_id, func.count(model.id)).group_by(model.content_project_id)
    ).all()
    return {int(pid): int(n) for pid, n in rows}


def _published(db: DbSession) -> dict[int, int]:
    rows = db.execute(
        select(Post.content_project_id, func.count(Post.id))
        .where(Post.published_at.is_not(None))
        .group_by(Post.content_project_id)
    ).all()
    return {int(pid): int(n) for pid, n in rows}


def _out(
    db: DbSession, p: ContentProject, stats: dict[str, dict[int, int]] | None = None
) -> ProjectOut:
    if stats is None:
        stats = _stats(db)
    return ProjectOut(
        id=p.id,
        slug=p.slug,
        name=p.name,
        description=p.description,
        languages=[Language(code) for code in p.languages],
        audience=p.audience,
        tone=p.tone,
        subtopics=[str(t) for t in p.subtopics],
        priority=p.priority,
        status=p.status,
        is_default=p.slug == DEFAULT_PROJECT_SLUG,
        channels=stats["channels"].get(p.id, 0),
        materials=stats["materials"].get(p.id, 0),
        videos=stats["videos"].get(p.id, 0),
        published=stats["published"].get(p.id, 0),
        created_at=p.created_at,
    )


def _stats(db: DbSession) -> dict[str, dict[int, int]]:
    return {
        "channels": _counts(db, Channel),
        "materials": _counts(db, GameplayFile),
        "videos": _counts(db, Variant),
        "published": _published(db),
    }


def _get(db: DbSession, project_id: int) -> ContentProject:
    project = db.get(ContentProject, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Content project not found")
    return project


def _snapshot(p: ContentProject) -> dict[str, object]:
    return {
        "name": p.name,
        "description": p.description,
        "languages": list(p.languages),
        "audience": p.audience,
        "tone": p.tone,
        "subtopics": list(p.subtopics),
        "priority": p.priority,
        "status": p.status.value,
    }


@router.get("", response_model=list[ProjectOut])
def list_projects(_: Viewer, db: DbSession) -> list[ProjectOut]:
    projects.ensure_default_project(db)
    db.commit()
    stats = _stats(db)
    rows = db.scalars(
        select(ContentProject).order_by(ContentProject.priority, ContentProject.name)
    ).all()
    return [_out(db, p, stats) for p in rows]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, _: Viewer, db: DbSession) -> ProjectOut:
    return _out(db, _get(db, project_id))


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, admin: Admin, db: DbSession) -> ProjectOut:
    slug = body.slug or projects.slugify(body.name)
    exists = db.scalar(
        select(ContentProject.id).where(
            (ContentProject.slug == slug) | (func.lower(ContentProject.name) == body.name.lower())
        )
    )
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A project with this name exists")
    project = ContentProject(
        slug=slug,
        name=body.name,
        description=body.description,
        languages=[lang.value for lang in body.languages],
        audience=body.audience,
        tone=body.tone,
        subtopics=body.subtopics,
        priority=body.priority,
        status=ContentProjectStatus.ACTIVE,
    )
    db.add(project)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="A project with this name exists"
        ) from exc
    audit.record(
        db,
        "project.create",
        user_id=admin.id,
        entity_type="content_projects",
        entity_id=project.id,
        after=_snapshot(project),
    )
    db.commit()
    return _out(db, project)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, body: ProjectPatch, admin: Admin, db: DbSession) -> ProjectOut:
    project = _get(db, project_id)
    before = _snapshot(project)
    data = body.model_dump(exclude_unset=True)
    if (
        data.get("status") == ContentProjectStatus.ARCHIVED
        and project.slug == DEFAULT_PROJECT_SLUG
        and db.scalar(select(Channel.id).where(Channel.content_project_id == project.id).limit(1))
        is not None
    ):
        # the default area is the fallback for old data; empty it may go away
        raise HTTPException(422, detail="The default project still has channels")
    if "name" in data and data["name"] is not None:
        name = " ".join(str(data["name"]).split())
        clash = db.scalar(
            select(ContentProject.id).where(
                func.lower(ContentProject.name) == name.lower(), ContentProject.id != project.id
            )
        )
        if clash is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="A project with this name exists")
        project.name = name
    for key in ("description", "audience", "tone", "priority", "subtopics"):
        if key in data and (data[key] is not None or key in ("description", "audience", "tone")):
            setattr(project, key, data[key])
    if data.get("languages") is not None:
        project.languages = [Language(code).value for code in data["languages"]]
    if data.get("status") is not None:
        project.status = ContentProjectStatus(data["status"])
    audit.record(
        db,
        "project.update",
        user_id=admin.id,
        entity_type="content_projects",
        entity_id=project.id,
        before=before,
        after=_snapshot(project),
    )
    db.commit()
    return _out(db, project)


class DeletionItem(BaseModel):
    key: str
    label: str
    count: int


class DeletionPreviewOut(BaseModel):
    id: int
    name: str
    can_delete: bool
    blockers: list[str]
    #: everything that is deleted together with the topic area
    items: list[DeletionItem]
    #: rows that stay but no longer belong to a topic area
    kept: list[DeletionItem]
    #: posts that are online on a platform; they stay there
    published: int


class DeleteIn(BaseModel):
    #: the project's name, typed by the user as confirmation
    confirm_name: str = Field(min_length=1, max_length=120)


def _plan(db: DbSession, project_id: int) -> project_delete.DeletionPlan:
    try:
        return project_delete.plan(db, project_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Content project not found") from exc


def _preview(plan: project_delete.DeletionPlan) -> DeletionPreviewOut:
    return DeletionPreviewOut(
        id=plan.project_id,
        name=plan.project_name,
        can_delete=not plan.blockers,
        blockers=plan.blockers,
        items=[DeletionItem(key=k, label=lbl, count=n) for k, lbl, n in plan.summary()],
        kept=[DeletionItem(key=k, label=lbl, count=n) for k, lbl, n in plan.kept_summary()],
        published=plan.published,
    )


@router.get("/{project_id}/deletion", response_model=DeletionPreviewOut)
def deletion_preview(project_id: int, _: Admin, db: DbSession) -> DeletionPreviewOut:
    """What deleting the topic area would remove, shown before the user confirms."""
    return _preview(_plan(db, project_id))


@router.post("/{project_id}/delete", status_code=204)
def delete_project(project_id: int, body: DeleteIn, admin: Admin, db: DbSession) -> None:
    """Delete the topic area and everything in it; the name must be typed as confirmation."""
    plan = _plan(db, project_id)
    if " ".join(body.confirm_name.split()).casefold() != plan.project_name.casefold():
        raise HTTPException(422, detail="Der eingegebene Name stimmt nicht überein.")
    if plan.blockers:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=plan.blockers[0])
    project = _get(db, project_id)
    before = _snapshot(project)
    project_delete.execute(db, plan)
    audit.record(
        db,
        "project.delete",
        user_id=admin.id,
        entity_type="content_projects",
        entity_id=project_id,
        before=before,
        after={"deleted": {k: n for k, _, n in plan.summary()}, "kept": dict(plan.kept)},
    )
    db.commit()


class TopicSuggestionOut(BaseModel):
    name: str
    description: str
    subtopics: list[str]
    audience: str
    tone: str
    reason: str
    facts: list[str]
    examples: list[str]
    score: int


class TopicSuggestionsOut(BaseModel):
    live: bool
    #: invented example numbers (development without live data)
    sample: bool
    suggestions: list[TopicSuggestionOut]
    sources: list[str]
    hint: str | None
    errors: list[str]
    generated_at: str
    provider: str


@router.post("/suggestions", response_model=TopicSuggestionsOut)
def suggest_topics(admin: Admin, db: DbSession, settings: AppSettings) -> TopicSuggestionsOut:
    """Five topic areas from current trends (YouTube charts, Wikipedia), with numbers."""
    result = topic_suggest.suggest(db, settings, get_redis(), user_id=admin.id)
    db.commit()  # AI call log
    return TopicSuggestionsOut.model_validate(result.as_dict())
