"""Material and rights management (Phase 6).

Roles follow the safety direction used elsewhere: an operator may register
material, record licenses, upload evidence and *block* sources; only an
admin may approve licenses, maintain publisher policies or *unblock*.
Every change is written to the audit log; changes that affect rights send
the affected material back to the rights check.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from api.deps import Admin, AppSettings, DbSession, Operator, Viewer, csrf_protect
from core.enums import (
    AssetKind,
    Language,
    LicenseStatus,
    MaterialStatus,
    PlatformCode,
    PolicyStatus,
    SourceType,
)
from models.production import GameplayFile
from models.rights import (
    Asset,
    Creator,
    License,
    LicenseDocument,
    PublisherPolicy,
    RightsCheck,
    Source,
)
from models.trends import Game
from services import audit, media, rights, storage
from services.trends import slugify

router = APIRouter(tags=["rights"], dependencies=[Depends(csrf_protect)])


def _404(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{what} not found")


def _get[T](db: DbSession, model: type[T], obj_id: int, what: str) -> T:
    obj = db.get(model, obj_id)
    if obj is None:
        raise _404(what)
    return obj


def _dump(obj: Any, fields: list[str]) -> dict[str, Any]:
    out = {}
    for f in fields:
        v = getattr(obj, f)
        out[f] = v.isoformat() if isinstance(v, date | datetime) else getattr(v, "value", v)
    return out


# --- creators -----------------------------------------------------------------


class CreatorIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contact: str | None = Field(default=None, max_length=320)
    notes: str | None = Field(default=None, max_length=5000)


class CreatorOut(CreatorIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_blocked: bool


@router.get("/creators", response_model=list[CreatorOut])
def list_creators(_: Viewer, db: DbSession) -> list[Creator]:
    return list(db.scalars(select(Creator).order_by(Creator.name)))


@router.post("/creators", response_model=CreatorOut, status_code=201)
def create_creator(body: CreatorIn, user: Operator, db: DbSession) -> Creator:
    creator = Creator(**body.model_dump())
    db.add(creator)
    db.flush()
    audit.record(
        db,
        "creator.create",
        user_id=user.id,
        entity_type="creators",
        entity_id=creator.id,
        after=body.model_dump(),
    )
    db.commit()
    return creator


def _set_block(db: DbSession, obj: Creator | Source, blocked: bool, user_id: int) -> list[int]:
    obj.is_blocked = blocked
    kind = "creator" if isinstance(obj, Creator) else "source"
    audit.record(
        db,
        f"{kind}.{'block' if blocked else 'unblock'}",
        user_id=user_id,
        entity_type=f"{kind}s",
        entity_id=obj.id,
        before={"is_blocked": not blocked},
        after={"is_blocked": blocked},
    )
    source_ids = (
        [s.id for s in db.scalars(select(Source).where(Source.creator_id == obj.id))]
        if isinstance(obj, Creator)
        else [obj.id]
    )
    moved = rights.request_recheck(
        db, rights.materials_for_source(db, source_ids), f"user:{user_id}"
    )
    db.commit()
    return moved


@router.post("/creators/{creator_id}/block")
def block_creator(creator_id: int, user: Operator, db: DbSession) -> dict[str, Any]:
    creator = _get(db, Creator, creator_id, "Creator")
    return {"rechecked": _set_block(db, creator, True, user.id)}


@router.post("/creators/{creator_id}/unblock")
def unblock_creator(creator_id: int, admin: Admin, db: DbSession) -> dict[str, Any]:
    creator = _get(db, Creator, creator_id, "Creator")
    return {"rechecked": _set_block(db, creator, False, admin.id)}


# --- sources ------------------------------------------------------------------


class SourceIn(BaseModel):
    creator_id: int | None = None
    type: SourceType
    name: str = Field(min_length=1, max_length=200)
    url: HttpUrl | None = None
    provenance_notes: str | None = Field(default=None, max_length=5000)


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    creator_id: int | None
    type: SourceType
    name: str
    url: str | None
    provenance_notes: str | None
    is_blocked: bool


@router.get("/sources", response_model=list[SourceOut])
def list_sources(_: Viewer, db: DbSession) -> list[Source]:
    return list(db.scalars(select(Source).order_by(Source.name)))


@router.post("/sources", response_model=SourceOut, status_code=201)
def create_source(body: SourceIn, user: Operator, db: DbSession) -> Source:
    if body.creator_id is not None and db.get(Creator, body.creator_id) is None:
        raise _404("Creator")
    data = body.model_dump(mode="json")
    source = Source(**{**data, "type": body.type})
    db.add(source)
    db.flush()
    audit.record(
        db, "source.create", user_id=user.id, entity_type="sources", entity_id=source.id, after=data
    )
    db.commit()
    return source


@router.post("/sources/{source_id}/block")
def block_source(source_id: int, user: Operator, db: DbSession) -> dict[str, Any]:
    source = _get(db, Source, source_id, "Source")
    return {"rechecked": _set_block(db, source, True, user.id)}


@router.post("/sources/{source_id}/unblock")
def unblock_source(source_id: int, admin: Admin, db: DbSession) -> dict[str, Any]:
    source = _get(db, Source, source_id, "Source")
    return {"rechecked": _set_block(db, source, False, admin.id)}


# --- licenses -----------------------------------------------------------------

LICENSE_FIELDS = [
    "valid_from",
    "valid_until",
    "allows_commercial_use",
    "allows_editing",
    "allows_short_form",
    "allows_monetization",
    "music_cleared",
    "allowed_platforms",
    "allowed_languages",
    "restrictions",
    "publisher_permission",
]


class LicenseIn(BaseModel):
    """Every permission defaults to False: nothing is assumed (deny by default)."""

    valid_from: date | None = None
    valid_until: date | None = None
    allows_commercial_use: bool = False
    allows_editing: bool = False
    allows_short_form: bool = False
    allows_monetization: bool = False
    music_cleared: bool = False
    allowed_platforms: list[PlatformCode] = Field(default_factory=list)
    allowed_languages: list[Language] = Field(default_factory=list)
    restrictions: str | None = Field(default=None, max_length=5000)
    publisher_permission: bool = False


class LicenseCreate(LicenseIn):
    source_id: int


class LicenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    status: LicenseStatus
    valid_from: date | None
    valid_until: date | None
    allows_commercial_use: bool
    allows_editing: bool
    allows_short_form: bool
    allows_monetization: bool
    music_cleared: bool
    allowed_platforms: list[str]
    allowed_languages: list[str]
    restrictions: str | None
    publisher_permission: bool
    document_uri: str | None
    verified_by_user_id: int | None
    verified_at: datetime | None
    documents: int = 0


def _license_out(db: DbSession, lic: License) -> LicenseOut:
    out = LicenseOut.model_validate(lic)
    out.documents = (
        db.scalar(
            select(func.count(LicenseDocument.id)).where(LicenseDocument.license_id == lic.id)
        )
        or 0
    )
    return out


def _license(db: DbSession, license_id: int) -> License:
    lic = db.get(License, license_id)
    if lic is None:
        raise _404("License")
    return lic


@router.get("/licenses", response_model=list[LicenseOut])
def list_licenses(_: Viewer, db: DbSession) -> list[LicenseOut]:
    return [_license_out(db, lic) for lic in db.scalars(select(License).order_by(License.id))]


@router.get("/licenses/{license_id}", response_model=LicenseOut)
def get_license(license_id: int, _: Viewer, db: DbSession) -> LicenseOut:
    return _license_out(db, _license(db, license_id))


@router.post("/licenses", response_model=LicenseOut, status_code=201)
def create_license(body: LicenseCreate, user: Operator, db: DbSession) -> LicenseOut:
    if db.get(Source, body.source_id) is None:
        raise _404("Source")
    if body.valid_from and body.valid_until and body.valid_until < body.valid_from:
        raise HTTPException(422, detail="valid_until must not be before valid_from")
    lic = License(**body.model_dump(mode="json"), status=LicenseStatus.PENDING)
    lic.valid_from, lic.valid_until = body.valid_from, body.valid_until
    db.add(lic)
    db.flush()
    audit.record(
        db,
        "license.create",
        user_id=user.id,
        entity_type="licenses",
        entity_id=lic.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return _license_out(db, lic)


@router.patch("/licenses/{license_id}", response_model=LicenseOut)
def update_license(license_id: int, body: LicenseIn, user: Operator, db: DbSession) -> LicenseOut:
    """Edit license terms. An approved license falls back to *pending* and must be re-approved."""
    lic = _license(db, license_id)
    if body.valid_from and body.valid_until and body.valid_until < body.valid_from:
        raise HTTPException(422, detail="valid_until must not be before valid_from")
    before = _dump(lic, [*LICENSE_FIELDS, "status"])
    data = body.model_dump(mode="json")
    for key in LICENSE_FIELDS:
        setattr(lic, key, data[key])
    lic.valid_from, lic.valid_until = body.valid_from, body.valid_until
    if lic.status == LicenseStatus.APPROVED:
        lic.status = LicenseStatus.PENDING
        lic.verified_by_user_id = None
        lic.verified_at = None
    audit.record(
        db,
        "license.update",
        user_id=user.id,
        entity_type="licenses",
        entity_id=lic.id,
        before=before,
        after=_dump(lic, [*LICENSE_FIELDS, "status"]),
    )
    rights.request_recheck(db, rights.materials_for_license(db, lic.id), f"user:{user.id}")
    db.commit()
    return _license_out(db, lic)


def _set_license_status(
    db: DbSession, lic: License, new: LicenseStatus, user_id: int, note: str | None = None
) -> LicenseOut:
    before = lic.status.value
    lic.status = new
    if new == LicenseStatus.APPROVED:
        lic.verified_by_user_id = user_id
        lic.verified_at = datetime.now(UTC)
    audit.record(
        db,
        f"license.{new.value}",
        user_id=user_id,
        entity_type="licenses",
        entity_id=lic.id,
        before={"status": before},
        after={"status": new.value},
        message=note,
    )
    rights.request_recheck(db, rights.materials_for_license(db, lic.id), f"user:{user_id}")
    db.commit()
    return _license_out(db, lic)


@router.post("/licenses/{license_id}/approve", response_model=LicenseOut)
def approve_license(license_id: int, admin: Admin, db: DbSession) -> LicenseOut:
    """The admin confirms that the uploaded evidence supports the recorded terms."""
    lic = _license(db, license_id)
    if lic.status not in (LicenseStatus.PENDING, LicenseStatus.REJECTED):
        raise HTTPException(409, detail=f"License is {lic.status.value}")
    if not lic.document_uri:
        raise HTTPException(409, detail="Upload the license document first")
    if lic.valid_until and lic.valid_until < datetime.now(UTC).date():
        raise HTTPException(409, detail="License period has already ended")
    return _set_license_status(db, lic, LicenseStatus.APPROVED, admin.id)


class StatusNote(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


@router.post("/licenses/{license_id}/reject", response_model=LicenseOut)
def reject_license(
    license_id: int, admin: Admin, db: DbSession, body: StatusNote | None = None
) -> LicenseOut:
    return _set_license_status(
        db, _license(db, license_id), LicenseStatus.REJECTED, admin.id, body.note if body else None
    )


@router.post("/licenses/{license_id}/revoke", response_model=LicenseOut)
def revoke_license(
    license_id: int, user: Operator, db: DbSession, body: StatusNote | None = None
) -> LicenseOut:
    """Revoking is the safe direction, so operators may do it."""
    return _set_license_status(
        db, _license(db, license_id), LicenseStatus.REVOKED, user.id, body.note if body else None
    )


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    license_id: int
    version: int
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_by_user_id: int | None
    uploaded_at: datetime


@router.get("/licenses/{license_id}/documents", response_model=list[DocumentOut])
def list_documents(license_id: int, _: Viewer, db: DbSession) -> list[LicenseDocument]:
    _license(db, license_id)
    return list(
        db.scalars(
            select(LicenseDocument)
            .where(LicenseDocument.license_id == license_id)
            .order_by(LicenseDocument.version)
        )
    )


@router.post("/licenses/{license_id}/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    license_id: int,
    user: Operator,
    db: DbSession,
    settings: AppSettings,
    file: Annotated[UploadFile, File()],
) -> LicenseDocument:
    lic = _license(db, license_id)
    data = await file.read(settings.max_document_bytes + 1)
    try:
        stored = storage.store_document(
            settings, data, file.content_type or "", f"licenses/{lic.id}"
        )
    except storage.StorageError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    version = (
        db.scalar(
            select(func.max(LicenseDocument.version)).where(LicenseDocument.license_id == lic.id)
        )
        or 0
    ) + 1
    doc = LicenseDocument(
        license_id=lic.id,
        version=version,
        filename=(file.filename or "document")[:255],
        content_type=file.content_type or "",
        size_bytes=stored.size,
        sha256=stored.sha256,
        storage_uri=stored.uri,
        uploaded_by_user_id=user.id,
    )
    db.add(doc)
    lic.document_uri = stored.uri
    db.flush()
    audit.record(
        db,
        "license.document",
        user_id=user.id,
        entity_type="licenses",
        entity_id=lic.id,
        after={"version": version, "sha256": stored.sha256},
    )
    db.commit()
    return doc


@router.get("/licenses/{license_id}/documents/{doc_id}/file")
def download_document(
    license_id: int, doc_id: int, _: Viewer, db: DbSession, settings: AppSettings
) -> FileResponse:
    doc = db.get(LicenseDocument, doc_id)
    if doc is None or doc.license_id != license_id:
        raise _404("Document")
    try:
        path = storage.resolve(settings, doc.storage_uri)
    except storage.StorageError as exc:
        raise _404("Document") from exc
    if not path.is_file():
        raise _404("Document file")
    return FileResponse(path, media_type=doc.content_type, filename=doc.filename)


# --- games and publisher policies ---------------------------------------------


class GameIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    categories: list[str] = Field(default_factory=list, max_length=10)
    publisher: str | None = Field(default=None, max_length=200)
    steam_app_id: int | None = Field(default=None, ge=1)


class GameCreated(BaseModel):
    id: int
    name: str
    slug: str


@router.post("/games", response_model=GameCreated, status_code=201)
def create_game(body: GameIn, user: Operator, db: DbSession) -> GameCreated:
    game = Game(**body.model_dump(), slug=slugify(body.name))
    db.add(game)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, detail="A game with this name already exists") from exc
    audit.record(
        db,
        "game.create",
        user_id=user.id,
        entity_type="games",
        entity_id=game.id,
        after=body.model_dump(),
    )
    db.commit()
    return GameCreated(id=game.id, name=game.name, slug=game.slug)


class PolicyIn(BaseModel):
    status: PolicyStatus
    publisher: str | None = Field(default=None, max_length=200)
    notes: str = Field(min_length=1, max_length=5000)
    policy_url: HttpUrl | None = None


class PolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    game_id: int
    game: str = ""
    status: PolicyStatus
    publisher: str | None
    notes: str
    policy_url: str | None
    checked_at: date | None
    checked_by_user_id: int | None


@router.get("/policies", response_model=list[PolicyOut])
def list_policies(_: Viewer, db: DbSession) -> list[PolicyOut]:
    rows = db.execute(
        select(PublisherPolicy, Game.name)
        .join(Game, Game.id == PublisherPolicy.game_id)
        .order_by(Game.name)
    ).all()
    return [PolicyOut.model_validate(p).model_copy(update={"game": name}) for p, name in rows]


@router.put("/games/{game_id}/policy", response_model=PolicyOut)
def set_policy(game_id: int, body: PolicyIn, admin: Admin, db: DbSession) -> PolicyOut:
    game = db.get(Game, game_id)
    if game is None:
        raise _404("Game")
    policy = db.scalar(select(PublisherPolicy).where(PublisherPolicy.game_id == game_id))
    before = _dump(policy, ["status", "notes"]) if policy else None
    if policy is None:
        policy = PublisherPolicy(game_id=game_id, status=body.status, notes=body.notes)
        db.add(policy)
    data = body.model_dump(mode="json")
    policy.status = body.status
    policy.publisher = data["publisher"]
    policy.notes = data["notes"]
    policy.policy_url = data["policy_url"]
    policy.checked_at = datetime.now(UTC).date()
    policy.checked_by_user_id = admin.id
    game.publisher_policy_notes = body.notes
    game.publisher_policy_url = data["policy_url"]
    if body.publisher:
        game.publisher = body.publisher
    db.flush()
    audit.record(
        db,
        "policy.set",
        user_id=admin.id,
        entity_type="publisher_policies",
        entity_id=policy.id,
        before=before,
        after=data,
    )
    rights.request_recheck(db, rights.materials_for_game(db, game_id), f"user:{admin.id}")
    db.commit()
    return PolicyOut.model_validate(policy).model_copy(update={"game": game.name})


# --- material -----------------------------------------------------------------


class MaterialIn(BaseModel):
    """Register licensed gameplay. The file itself is uploaded/probed in Phase 7."""

    source_id: int
    license_id: int
    game_id: int | None = None
    title: str | None = Field(default=None, max_length=300)
    storage_uri: str = Field(min_length=1, max_length=1000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_s: float | None = Field(default=None, gt=0)


class MaterialOut(BaseModel):
    id: int
    title: str | None
    status: MaterialStatus
    game_id: int | None
    game: str | None
    source_id: int
    source: str
    license_id: int
    storage_uri: str
    duration_s: float | None
    created_at: datetime
    error_message: str | None
    last_check: dict[str, Any] | None


def _material_out(db: DbSession, m: GameplayFile) -> MaterialOut:
    asset = db.get(Asset, m.asset_id)
    assert asset is not None
    source = db.get(Source, asset.source_id)
    game = db.get(Game, m.game_id) if m.game_id else None
    check = db.scalar(
        select(RightsCheck)
        .where(RightsCheck.gameplay_file_id == m.id)
        .order_by(RightsCheck.id.desc())
        .limit(1)
    )
    return MaterialOut(
        id=m.id,
        title=asset.title,
        status=m.status,
        game_id=m.game_id,
        game=game.name if game else None,
        source_id=asset.source_id,
        source=source.name if source else "?",
        license_id=asset.license_id,
        storage_uri=m.storage_uri,
        duration_s=m.duration_s,
        created_at=m.created_at,
        error_message=m.error_message,
        last_check=None
        if check is None
        else {
            "id": check.id,
            "checked_at": check.checked_at.isoformat(),
            "approved": check.approved,
            "checks": check.checks,
            "missing": check.missing,
            "denied": check.denied,
        },
    )


@router.get("/materials", response_model=list[MaterialOut])
def list_materials(
    _: Viewer,
    db: DbSession,
    status_filter: Annotated[MaterialStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[MaterialOut]:
    q = select(GameplayFile).order_by(GameplayFile.id.desc()).limit(limit)
    if status_filter is not None:
        q = q.where(GameplayFile.status == status_filter)
    return [_material_out(db, m) for m in db.scalars(q)]


@router.get("/materials/{material_id}", response_model=MaterialOut)
def get_material(material_id: int, _: Viewer, db: DbSession) -> MaterialOut:
    m = db.get(GameplayFile, material_id)
    if m is None:
        raise _404("Material")
    return _material_out(db, m)


@router.post("/materials", response_model=MaterialOut, status_code=201)
def register_material(body: MaterialIn, user: Operator, db: DbSession) -> MaterialOut:
    lic = _license(db, body.license_id)
    if lic.source_id != body.source_id:
        raise HTTPException(422, detail="License does not belong to this source")
    if body.game_id is not None and db.get(Game, body.game_id) is None:
        raise _404("Game")
    if db.scalar(select(GameplayFile.id).where(GameplayFile.sha256 == body.sha256)):
        raise HTTPException(409, detail="This file is already registered")
    asset = Asset(
        source_id=body.source_id,
        license_id=body.license_id,
        game_id=body.game_id,
        kind=AssetKind.VIDEO,
        title=body.title,
        storage_uri=body.storage_uri,
        sha256=body.sha256,
        duration_s=body.duration_s,
    )
    db.add(asset)
    db.flush()
    material = GameplayFile(
        asset_id=asset.id,
        game_id=body.game_id,
        storage_uri=body.storage_uri,
        sha256=body.sha256,
        duration_s=body.duration_s,
    )
    db.add(material)
    db.flush()
    audit.record(
        db,
        "material.register",
        user_id=user.id,
        entity_type="gameplay_files",
        entity_id=material.id,
        after=body.model_dump(),
    )
    db.commit()
    return _material_out(db, material)


VIDEO_TYPES = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-matroska": ".mkv"}


@router.post("/materials/upload", response_model=MaterialOut, status_code=201)
def upload_material(
    user: Operator,
    db: DbSession,
    settings: AppSettings,
    file: Annotated[UploadFile, File()],
    source_id: Annotated[int, Form()],
    license_id: Annotated[int, Form()],
    game_id: Annotated[int | None, Form()] = None,
    title: Annotated[str | None, Form(max_length=300)] = None,
) -> MaterialOut:
    """Upload a licensed gameplay file. It is checked with ffprobe before it is stored."""
    lic = _license(db, license_id)
    if lic.source_id != source_id:
        raise HTTPException(422, detail="License does not belong to this source")
    if game_id is not None and db.get(Game, game_id) is None:
        raise _404("Game")
    suffix = VIDEO_TYPES.get(file.content_type or "")
    if suffix is None:
        raise HTTPException(422, detail="Only MP4, MOV or MKV video files are accepted")
    tmp = storage.work_dir(settings) / f"upload-{uuid4().hex}{suffix}"
    try:
        size = 0
        with tmp.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(413, detail="File too large")
                out.write(chunk)
        try:
            probe = media.probe(settings, tmp)
        except media.MediaError as exc:
            raise HTTPException(422, detail="Not a readable video file") from exc
        issues = media.technical_issues(settings, probe)
        if issues:
            raise HTTPException(422, detail="Technische Prüfung: " + "; ".join(issues))
        digest = storage.sha256_file(tmp)
        if db.scalar(select(GameplayFile.id).where(GameplayFile.sha256 == digest)):
            raise HTTPException(409, detail="This file is already registered")
        stored = storage.store_path(settings, tmp, "materials", suffix)
    finally:
        tmp.unlink(missing_ok=True)
    asset = Asset(
        source_id=source_id,
        license_id=license_id,
        game_id=game_id,
        kind=AssetKind.VIDEO,
        title=title,
        storage_uri=stored.uri,
        sha256=stored.sha256,
        duration_s=probe.duration_s,
    )
    db.add(asset)
    db.flush()
    material = GameplayFile(
        asset_id=asset.id,
        game_id=game_id,
        storage_uri=stored.uri,
        sha256=stored.sha256,
        duration_s=probe.duration_s,
        width=probe.width,
        height=probe.height,
        fps=probe.fps,
        video_codec=probe.video_codec,
        audio_codec=probe.audio_codec,
    )
    db.add(material)
    db.flush()
    audit.record(
        db,
        "material.upload",
        user_id=user.id,
        entity_type="gameplay_files",
        entity_id=material.id,
        after={"sha256": stored.sha256, "size": stored.size, "probe": probe.as_dict()},
    )
    db.commit()
    return _material_out(db, material)


@router.get("/rights/criteria")
def list_criteria(_: Viewer) -> list[dict[str, str]]:
    return [{"key": k, "label": label} for k, label in rights.CRITERIA]
