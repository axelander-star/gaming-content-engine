"""Media library and own production (extension phase E7).

Library files come in through the resumable upload (purpose ``library``) with a
rights confirmation per file. Productions are drafted (script by the AI layer or
by hand), edited and rendered by the ``own_production`` agent. Nothing here
publishes: finished videos wait in the library for the approval center (E8).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import AppSettings, DbSession, Operator, Viewer, csrf_protect
from core.config import Settings
from core.enums import (
    ContentProjectStatus,
    IdeaStatus,
    Language,
    LibraryKind,
    LibraryOrigin,
    LibraryStatus,
    ProductionStatus,
)
from models.library import LibraryItem, OwnProduction
from models.projects import ContentProject
from models.research import Idea
from models.uploads import UploadSession
from services import ai, audit, library, own_production, splitter, storage, uploads
from services.controls import effective_controls
from services.orchestrator import submit
from services.queue import get_redis

log = logging.getLogger(__name__)

router = APIRouter(tags=["library"], dependencies=[Depends(csrf_protect)])


def _project(db: Session, project_id: int, *, active: bool = True) -> ContentProject:
    project = db.get(ContentProject, project_id)
    if project is None or project.status == ContentProjectStatus.ARCHIVED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Themenbereich nicht gefunden")
    if active and project.status != ContentProjectStatus.ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"{project.name} ist pausiert")
    return project


def _project_names(db: Session) -> dict[int, str]:
    return {pid: name for pid, name in db.execute(select(ContentProject.id, ContentProject.name))}


# --- library -------------------------------------------------------------------------


class LibraryItemOut(BaseModel):
    id: int
    project_id: int
    project: str
    kind: LibraryKind
    origin: LibraryOrigin
    status: LibraryStatus
    title: str
    filename: str | None
    content_type: str
    size_bytes: int
    duration_s: float | None
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    orientation: str | None
    has_rendition: bool
    has_thumb: bool
    rendition: dict[str, Any]
    render_seconds: float | None
    rights: dict[str, Any]
    tags: list[str]
    note: str | None
    error_message: str | None
    archived: bool
    #: False once the original was removed after the retention period (16.11.2026)
    has_original: bool
    original_deleted_at: datetime | None
    created_at: datetime
    #: A6: the long video this short was cut from, and the state of splitting this one
    parent_item_id: int | None = None
    split_state: str | None = None
    split_info: dict[str, Any] = Field(default_factory=dict)
    #: A6: why it cannot be split (``None`` = can be split) and the suggested count/length
    split_problem: str | None = None
    split_suggestion: dict[str, Any] | None = None


def _item_out(item: LibraryItem, project: str) -> LibraryItemOut:
    return LibraryItemOut(
        id=item.id,
        project_id=item.content_project_id,
        project=project,
        kind=item.kind,
        origin=item.origin,
        status=item.status,
        title=item.title,
        filename=item.filename,
        content_type=item.content_type,
        size_bytes=item.size_bytes,
        duration_s=item.duration_s,
        width=item.width,
        height=item.height,
        fps=item.fps,
        video_codec=item.video_codec,
        audio_codec=item.audio_codec,
        orientation=item.orientation,
        has_rendition=item.rendition_uri is not None,
        has_thumb=item.thumb_uri is not None,
        rendition=dict(item.rendition or {}),
        render_seconds=item.render_seconds,
        rights=dict(item.rights or {}),
        tags=[str(t) for t in item.tags or []],
        note=item.note,
        error_message=item.error_message,
        archived=item.archived_at is not None,
        has_original=item.original_deleted_at is None,
        original_deleted_at=item.original_deleted_at,
        created_at=item.created_at,
        parent_item_id=item.parent_item_id,
        split_state=item.split_state,
        split_info=dict(item.split_info or {}),
        split_problem=splitter.check(item),
        split_suggestion=(
            splitter.suggestion(item.duration_s or 0) if item.kind == LibraryKind.VIDEO else None
        ),
    )


class LibraryInfoOut(BaseModel):
    rights_statement: str
    allowed_types: dict[str, str]
    max_rendition_s: float
    #: originals of uploaded videos are deleted after this many days (0 = never)
    original_retention_days: int


@router.get("/library/info", response_model=LibraryInfoOut)
def library_info(_: Viewer, settings: AppSettings) -> LibraryInfoOut:
    return LibraryInfoOut(
        rights_statement=library.RIGHTS_STATEMENT,
        allowed_types=library.ALLOWED_TYPES,
        max_rendition_s=settings.library_max_rendition_s,
        original_retention_days=settings.library_original_retention_days,
    )


@router.get("/library", response_model=list[LibraryItemOut])
def list_library(
    _: Viewer,
    db: DbSession,
    project_id: int | None = Query(default=None),
    kind: Annotated[LibraryKind | None, Query()] = None,
    origin: Annotated[LibraryOrigin | None, Query()] = None,
    item_status: Annotated[LibraryStatus | None, Query(alias="status")] = None,
    archived: bool = Query(default=False),
) -> list[LibraryItemOut]:
    query = select(LibraryItem).order_by(LibraryItem.id.desc()).limit(300)
    if project_id is not None:
        query = query.where(LibraryItem.content_project_id == project_id)
    if kind is not None:
        query = query.where(LibraryItem.kind == kind)
    if origin is not None:
        query = query.where(LibraryItem.origin == origin)
    if item_status is not None:
        query = query.where(LibraryItem.status == item_status)
    query = query.where(
        LibraryItem.archived_at.is_not(None) if archived else LibraryItem.archived_at.is_(None)
    )
    names = _project_names(db)
    return [_item_out(i, names.get(i.content_project_id, "?")) for i in db.scalars(query)]


def _item(db: Session, item_id: int) -> LibraryItem:
    item = db.get(LibraryItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Datei nicht gefunden")
    return item


@router.get("/library/{item_id}", response_model=LibraryItemOut)
def get_library_item(item_id: int, _: Viewer, db: DbSession) -> LibraryItemOut:
    item = _item(db, item_id)
    return _item_out(item, _project_names(db).get(item.content_project_id, "?"))


@router.get("/library/{item_id}/file")
def library_file(
    item_id: int,
    _: Viewer,
    db: DbSession,
    settings: AppSettings,
    which: Literal["original", "rendition", "thumb"] = Query(default="rendition"),
) -> FileResponse:
    item = _item(db, item_id)
    uri = {"original": item.original_uri, "rendition": item.rendition_uri, "thumb": item.thumb_uri}[
        which
    ]
    if which == "original" and item.original_deleted_at is not None:
        raise HTTPException(
            status.HTTP_410_GONE, detail="Original nach Ablauf der Aufbewahrungsfrist gelöscht"
        )
    if uri is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Diese Fassung gibt es nicht")
    try:
        path = storage.resolve(settings, uri)
    except storage.StorageError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Datei fehlt") from exc
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Datei fehlt")
    if which == "thumb" or (
        which == "rendition" and item.kind == LibraryKind.IMAGE and uri != item.original_uri
    ):
        media_type = "image/jpeg"
    elif which == "rendition" and item.kind == LibraryKind.VIDEO:
        media_type = "video/mp4"
    else:
        media_type = item.content_type
    name = f"mediathek-{item.id}-{which}{path.suffix}"
    return FileResponse(path, media_type=media_type, filename=name)


class LibraryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=300)
    note: str | None = Field(default=None, max_length=2000)
    tags: list[Annotated[str, Field(min_length=1, max_length=40)]] | None = Field(
        default=None, max_length=20
    )


@router.patch("/library/{item_id}", response_model=LibraryItemOut)
def update_library_item(
    item_id: int, body: LibraryPatch, user: Operator, db: DbSession
) -> LibraryItemOut:
    item = _item(db, item_id)
    before = {"title": item.title, "note": item.note, "tags": item.tags}
    fields = body.model_dump(exclude_unset=True)
    if body.title is not None:
        item.title = " ".join(body.title.split())
    if "note" in fields:
        item.note = (body.note or "").strip() or None
    if body.tags is not None:
        item.tags = sorted({" ".join(t.split()) for t in body.tags})
    audit.record(
        db,
        "library.updated",
        user_id=user.id,
        entity_type="library_items",
        entity_id=item.id,
        before=before,
        after={"title": item.title, "note": item.note, "tags": item.tags},
    )
    db.commit()
    return _item_out(item, _project_names(db).get(item.content_project_id, "?"))


def _in_use(db: Session, item: LibraryItem) -> list[str]:
    """Productions that still use ``item`` as a picture (not done or failed)."""
    open_states = (ProductionStatus.DRAFT, ProductionStatus.QUEUED, ProductionStatus.RENDERING)
    rows = db.scalars(
        select(OwnProduction).where(
            OwnProduction.content_project_id == item.content_project_id,
            OwnProduction.status.in_(open_states),
        )
    )
    return [
        p.title
        for p in rows
        if any(isinstance(s, dict) and s.get("image_item_id") == item.id for s in p.segments)
    ]


@router.post("/library/{item_id}/archive", response_model=LibraryItemOut)
def archive_library_item(item_id: int, user: Operator, db: DbSession) -> LibraryItemOut:
    """Hide a file from the library. Files stay on disk; restoring is possible."""
    item = _item(db, item_id)
    users = _in_use(db, item)
    if users:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"Wird noch verwendet in: {', '.join(users[:3])}"
        )
    item.archived_at = item.archived_at or datetime.now(UTC)
    audit.record(
        db, "library.archived", user_id=user.id, entity_type="library_items", entity_id=item.id
    )
    db.commit()
    return _item_out(item, _project_names(db).get(item.content_project_id, "?"))


@router.post("/library/{item_id}/restore", response_model=LibraryItemOut)
def restore_library_item(item_id: int, user: Operator, db: DbSession) -> LibraryItemOut:
    item = _item(db, item_id)
    if item.original_deleted_at is not None and item.rendition_uri is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Original nach Ablauf der Frist gelöscht, keine 9:16-Fassung: "
            "nicht mehr nutzbar",
        )
    item.archived_at = None
    audit.record(
        db, "library.restored", user_id=user.id, entity_type="library_items", entity_id=item.id
    )
    db.commit()
    return _item_out(item, _project_names(db).get(item.content_project_id, "?"))


@router.post("/library/{item_id}/reprocess", response_model=LibraryItemOut)
def reprocess_library_item(
    item_id: int,
    user: Operator,
    db: DbSession,
    redis: Annotated[Redis, Depends(get_redis)],
) -> LibraryItemOut:
    item = _item(db, item_id)
    if item.status != LibraryStatus.FAILED:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Nur fehlgeschlagene Dateien")
    if item.original_deleted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Original bereits gelöscht")
    item.status = LibraryStatus.PROCESSING
    item.error_message = None
    audit.record(
        db, "library.reprocess", user_id=user.id, entity_type="library_items", entity_id=item.id
    )
    db.commit()
    _queue_item(item.id, redis)
    return _item_out(item, _project_names(db).get(item.content_project_id, "?"))


class SplitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int | None = Field(default=None, ge=1, le=splitter.MAX_COUNT)
    length_s: float | None = Field(default=None, ge=splitter.MIN_LENGTH_S, le=splitter.MAX_LENGTH_S)


@router.post("/library/{item_id}/split", response_model=LibraryItemOut)
def split_library_item(
    item_id: int,
    body: SplitIn,
    user: Operator,
    db: DbSession,
    redis: Annotated[Redis, Depends(get_redis)],
) -> LibraryItemOut:
    """Cut a long video into shorts (A6); runs in the background."""
    item = _item(db, item_id)
    try:
        splitter.request(db, item, count=body.count, length_s=body.length_s, user_id=user.id)
    except splitter.SplitError as exc:
        raise HTTPException(exc.status_code, detail=str(exc)) from exc
    audit.record(
        db,
        "library.split",
        user_id=user.id,
        entity_type="library_items",
        entity_id=item.id,
        after=dict(item.split_info or {}),
    )
    db.commit()
    _queue_item(item.id, redis)
    return _item_out(item, _project_names(db).get(item.content_project_id, "?"))


def _queue_item(item_id: int, redis: Redis | None = None) -> None:
    payload = {"entity_type": "library_items", "entity_id": item_id}
    try:
        submit("media_library", payload, connection=redis)
    except Exception:  # the sweep of the scheduler picks the file up later
        log.exception("could not queue library item", extra={"item": item_id})


# --- upload consumer "library" --------------------------------------------------------


class LibraryUploadParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int
    title: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=2000)
    tags: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(
        default_factory=list, max_length=20
    )
    #: Must be true: "own recording or own creation" (``library.RIGHTS_STATEMENT``).
    rights_confirmed: bool = False


def _validate_library_upload(
    db: Session, settings: Settings, user_id: int, params: dict[str, Any]
) -> dict[str, Any]:
    try:
        clean = LibraryUploadParams.model_validate(params)
    except ValidationError as exc:
        raise uploads.UploadError(422, "Ungültige Angaben: " + str(exc.errors())) from exc
    if not clean.rights_confirmed:
        raise uploads.UploadError(422, "Bitte bestätigen, dass es eine eigene Aufnahme ist")
    try:
        _project(db, clean.project_id)
    except HTTPException as exc:
        raise uploads.UploadError(exc.status_code, str(exc.detail)) from exc
    return clean.model_dump()


def _accept_library_upload(
    db: Session, settings: Settings, session: UploadSession, path: Path
) -> dict[str, Any]:
    p = LibraryUploadParams.model_validate(session.params)
    try:
        _project(db, p.project_id)
        item = library.add_upload(
            db,
            settings,
            project_id=p.project_id,
            path=path,
            filename=session.filename,
            content_type=session.content_type,
            title=" ".join((p.title or "").split()) or None,
            note=(p.note or "").strip() or None,
            tags=sorted({" ".join(t.split()) for t in p.tags}),
            user_id=session.user_id,
        )
    except HTTPException as exc:
        raise uploads.UploadError(exc.status_code, str(exc.detail)) from exc
    except library.LibraryError as exc:
        raise uploads.UploadError(exc.status, exc.detail) from exc
    audit.record(
        db,
        "library.upload",
        user_id=session.user_id,
        entity_type="library_items",
        entity_id=item.id,
        after={"sha256": item.original_sha256, "kind": item.kind.value, "rights": item.rights},
    )
    return {"library_item_id": item.id, "kind": item.kind.value}


def _after_library_upload(result: dict[str, Any]) -> None:
    item_id = result.get("library_item_id")
    if isinstance(item_id, int):
        _queue_item(item_id)


uploads.register_consumer(
    "library",
    uploads.Consumer(
        allowed_types=library.ALLOWED_TYPES,
        validate=_validate_library_upload,
        accept=_accept_library_upload,
        after_commit=_after_library_upload,
    ),
)


# --- own production ------------------------------------------------------------------


class SegmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(default="", max_length=own_production.HEADLINE_MAX)
    text: str = Field(min_length=1, max_length=own_production.TEXT_MAX)
    image_item_id: int | None = None


class ProductionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int
    title: str | None = Field(default=None, max_length=own_production.TITLE_MAX)
    topic: str | None = Field(default=None, max_length=300)
    idea_id: int | None = None
    language: Language = Language.DE
    #: Without segments the script is drafted by the AI layer from idea or topic.
    segments: list[SegmentIn] | None = None


class ProductionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=own_production.TITLE_MAX)
    language: Language | None = None
    segments: list[SegmentIn] | None = None


class ProductionOut(BaseModel):
    id: int
    project_id: int
    project: str
    idea_id: int | None
    title: str
    language: Language
    status: ProductionStatus
    segments: list[dict[str, Any]]
    script_source: str
    voice_provider: str | None
    duration_s: float | None
    render_seconds: float | None
    result: dict[str, Any]
    output_item_id: int | None
    error_message: str | None
    created_at: datetime
    rendered_at: datetime | None


def _prod_out(db: Session, prod: OwnProduction) -> ProductionOut:
    result = {k: v for k, v in (prod.result or {}).items() if not k.endswith("_uri")}
    return ProductionOut(
        id=prod.id,
        project_id=prod.content_project_id,
        project=_project_names(db).get(prod.content_project_id, "?"),
        idea_id=prod.idea_id,
        title=prod.title,
        language=prod.language,
        status=prod.status,
        segments=list(prod.segments or []),
        script_source=prod.script_source,
        voice_provider=prod.voice_provider,
        duration_s=prod.duration_s,
        render_seconds=prod.render_seconds,
        result=result,
        output_item_id=prod.output_item_id,
        error_message=prod.error_message,
        created_at=prod.created_at,
        rendered_at=prod.rendered_at,
    )


def _production_error(exc: own_production.ProductionError) -> HTTPException:
    return HTTPException(exc.status, detail=exc.detail)


@router.get("/productions", response_model=list[ProductionOut])
def list_productions(
    _: Viewer, db: DbSession, project_id: int | None = Query(default=None)
) -> list[ProductionOut]:
    query = select(OwnProduction).order_by(OwnProduction.id.desc()).limit(100)
    if project_id is not None:
        query = query.where(OwnProduction.content_project_id == project_id)
    return [_prod_out(db, p) for p in db.scalars(query)]


def _production(db: Session, production_id: int, *, lock: bool = False) -> OwnProduction:
    query = select(OwnProduction).where(OwnProduction.id == production_id)
    prod = db.scalar(query.with_for_update() if lock else query)
    if prod is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Produktion nicht gefunden")
    return prod


@router.get("/productions/{production_id}", response_model=ProductionOut)
def get_production(production_id: int, _: Viewer, db: DbSession) -> ProductionOut:
    return _prod_out(db, _production(db, production_id))


@router.post("/productions", response_model=ProductionOut, status_code=201)
def create_production(
    body: ProductionIn, user: Operator, db: DbSession, settings: AppSettings
) -> ProductionOut:
    project = _project(db, body.project_id)
    project_id = project.id
    idea: Idea | None = None
    if body.idea_id is not None:
        idea = db.get(Idea, body.idea_id)
        if idea is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Idee nicht gefunden")
        if idea.content_project_id != project_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="Die Idee gehört zu einem anderen Themenbereich"
            )
        if idea.status == IdeaStatus.REJECTED:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Die Idee wurde verworfen")
    topic = " ".join((body.topic or (idea.title if idea else "") or body.title or "").split())
    pitch = idea.pitch if idea else ""
    call_id: int | None = None
    try:
        if body.segments is not None:
            segments = own_production.clean_segments(
                [s.model_dump() for s in body.segments], settings.production_max_segments
            )
            title, source = body.title or topic, "manual"
        else:
            if len(topic) < 3:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Thema, Idee oder Abschnitte angeben",
                )
            try:
                draft = own_production.draft_script(
                    db,
                    settings,
                    project,
                    topic=topic,
                    pitch=pitch,
                    language=body.language,
                    user_id=user.id,
                )
            except ai.AIBlockedError as exc:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, detail=f"KI nicht verfügbar: {exc.reason}"
                ) from exc
            except (ai.AIRefusedError, ai.AIFailedError) as exc:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
            segments, source, call_id = draft.segments, draft.provider, draft.call_id
            title = body.title or draft.title
        own_production.check_images(db, project_id, segments)
    except own_production.ProductionError as exc:
        raise _production_error(exc) from exc
    if not title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Titel fehlt")
    prod = OwnProduction(
        content_project_id=project_id,
        idea_id=idea.id if idea else None,
        title=" ".join(title.split())[: own_production.TITLE_MAX],
        language=body.language,
        status=ProductionStatus.DRAFT,
        segments=segments,
        script_source=source,
        ai_call_id=call_id,
        created_by_user_id=user.id,
    )
    db.add(prod)
    db.flush()
    audit.record(
        db,
        "production.created",
        user_id=user.id,
        entity_type="own_productions",
        entity_id=prod.id,
        after={"title": prod.title, "script": source, "segments": len(segments)},
    )
    db.commit()
    return _prod_out(db, prod)


BUSY = (ProductionStatus.QUEUED, ProductionStatus.RENDERING)


class TranslateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language


@router.post(
    "/productions/{production_id}/translate", response_model=ProductionOut, status_code=201
)
def translate_production(
    production_id: int,
    body: TranslateIn,
    user: Operator,
    db: DbSession,
    settings: AppSettings,
) -> ProductionOut:
    """Second language version of a production (A6): same pictures, new text; a draft."""
    prod = db.get(OwnProduction, production_id)
    if prod is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Produktion nicht gefunden")
    try:
        copy = own_production.translate(db, settings, prod, body.language, user.id)
    except own_production.ProductionError as exc:
        raise _production_error(exc) from exc
    except ai.AIBlockedError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"KI nicht verfügbar: {exc.reason}"
        ) from exc
    except (ai.AIRefusedError, ai.AIFailedError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    audit.record(
        db,
        "production.translated",
        user_id=user.id,
        entity_type="own_productions",
        entity_id=copy.id,
        after={"from": prod.id, "language": body.language.value},
    )
    db.commit()
    return _prod_out(db, copy)


@router.patch("/productions/{production_id}", response_model=ProductionOut)
def update_production(
    production_id: int,
    body: ProductionPatch,
    user: Operator,
    db: DbSession,
    settings: AppSettings,
) -> ProductionOut:
    prod = _production(db, production_id, lock=True)
    if prod.status in BUSY:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Produktion wird gerade gerendert")
    if body.segments is not None:
        try:
            segments = own_production.clean_segments(
                [s.model_dump() for s in body.segments], settings.production_max_segments
            )
            own_production.check_images(db, prod.content_project_id, segments)
        except own_production.ProductionError as exc:
            raise _production_error(exc) from exc
        prod.segments = segments
        if prod.script_source != "manual":
            prod.script_source = f"{prod.script_source}+manual"[:32]
    if body.title is not None:
        prod.title = " ".join(body.title.split())
    if body.language is not None:
        prod.language = body.language
    prod.status = ProductionStatus.DRAFT  # a finished video stays in the library
    audit.record(
        db,
        "production.updated",
        user_id=user.id,
        entity_type="own_productions",
        entity_id=prod.id,
        after={"title": prod.title, "segments": len(prod.segments)},
    )
    db.commit()
    return _prod_out(db, prod)


@router.post("/productions/{production_id}/render", response_model=ProductionOut)
def render_production(
    production_id: int,
    user: Operator,
    db: DbSession,
    settings: AppSettings,
    redis: Annotated[Redis, Depends(get_redis)],
) -> ProductionOut:
    if effective_controls(db, settings).emergency_stop:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Not-Aus ist aktiv")
    prod = _production(db, production_id, lock=True)
    if prod.status in BUSY:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Produktion läuft schon")
    _project(db, prod.content_project_id)
    try:
        own_production.check_images(db, prod.content_project_id, prod.segments)
    except own_production.ProductionError as exc:
        raise _production_error(exc) from exc
    prod.status = ProductionStatus.QUEUED
    prod.error_message = None
    audit.record(
        db, "production.render", user_id=user.id, entity_type="own_productions", entity_id=prod.id
    )
    db.commit()
    payload = {"entity_type": "own_productions", "entity_id": prod.id}
    try:
        submit("own_production", payload, priority=False, connection=redis)
    except Exception as exc:
        prod.status = ProductionStatus.DRAFT
        db.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="Warteschlange nicht erreichbar"
        ) from exc
    return _prod_out(db, prod)


@router.delete("/productions/{production_id}", status_code=204)
def delete_production(production_id: int, user: Operator, db: DbSession) -> None:
    """Delete the draft. A finished video stays in the library."""
    prod = _production(db, production_id, lock=True)
    if prod.status in BUSY:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Produktion wird gerade gerendert")
    audit.record(
        db,
        "production.deleted",
        user_id=user.id,
        entity_type="own_productions",
        entity_id=prod.id,
        before={"title": prod.title},
    )
    db.delete(prod)
    db.commit()


@router.get("/productions/{production_id}/subtitles")
def production_subtitles(
    production_id: int,
    _: Viewer,
    db: DbSession,
    settings: AppSettings,
    fmt: Literal["srt", "vtt"] = Query(default="srt"),
) -> FileResponse:
    prod = _production(db, production_id)
    uri = (prod.result or {}).get(f"{fmt}_uri")
    if not isinstance(uri, str):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Noch keine Untertitel")
    try:
        path = storage.resolve(settings, uri)
    except storage.StorageError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Datei fehlt") from exc
    media_type = "text/vtt" if fmt == "vtt" else "application/x-subrip"
    return FileResponse(path, media_type=media_type, filename=f"produktion-{prod.id}.{fmt}")
