"""Resumable uploads in parts (protocol in services/uploads.py and docs/UPLOADS.md)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from api.deps import AppSettings, DbSession, Operator, csrf_protect
from core.enums import UploadStatus
from models.uploads import UploadSession
from services import uploads

router = APIRouter(prefix="/uploads", tags=["uploads"], dependencies=[Depends(csrf_protect)])

OFFSET_HEADER = "Upload-Offset"


class UploadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: str = Field(min_length=1, max_length=32)
    filename: str = Field(min_length=1, max_length=1000)
    size_bytes: int = Field(gt=0)
    content_type: str = Field(min_length=1, max_length=100)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)


class UploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    purpose: str
    filename: str
    content_type: str
    size_bytes: int
    received_bytes: int
    chunk_bytes: int
    status: UploadStatus
    result: dict[str, Any] | None
    error_message: str | None
    expires_at: datetime
    created_at: datetime


def _raise(exc: uploads.UploadError) -> NoReturn:
    headers = {}
    if "received_bytes" in exc.extra:
        headers[OFFSET_HEADER] = str(exc.extra["received_bytes"])
    raise HTTPException(exc.status, detail=exc.detail, headers=headers or None) from exc


def _out(session: UploadSession) -> UploadOut:
    return UploadOut.model_validate(session)


@router.post("", response_model=UploadOut, status_code=201)
def create_upload(
    body: UploadCreate, user: Operator, db: DbSession, settings: AppSettings
) -> UploadOut:
    """Start an upload. Send the parts with PATCH, then call ``/complete``."""
    try:
        session = uploads.create(
            db,
            settings,
            user_id=user.id,
            purpose=body.purpose,
            filename=body.filename,
            size_bytes=body.size_bytes,
            content_type=body.content_type,
            params=body.params,
            sha256=body.sha256,
        )
    except uploads.UploadError as exc:
        # Nothing is written before the checks pass, so there is nothing to roll back.
        _raise(exc)
    db.commit()
    return _out(session)


@router.get("/{upload_id}", response_model=UploadOut)
def get_upload(upload_id: str, user: Operator, db: DbSession) -> UploadOut:
    """Current state; ``received_bytes`` is where to continue after an interruption."""
    try:
        return _out(uploads.get(db, upload_id, user.id))
    except uploads.UploadError as exc:
        _raise(exc)


async def _read_body(request: Request, limit: int) -> bytes:
    """Read the raw body, refusing more than ``limit`` bytes without buffering it all."""
    data = bytearray()
    async for piece in request.stream():
        data.extend(piece)
        if len(data) > limit:
            raise HTTPException(413, detail=f"Part larger than {limit} bytes")
    return bytes(data)


@router.patch("/{upload_id}", response_model=UploadOut)
async def append_part(
    upload_id: str,
    request: Request,
    user: Operator,
    db: DbSession,
    settings: AppSettings,
    offset: Annotated[int, Header(alias=OFFSET_HEADER, ge=0)],
    chunk_sha256: Annotated[str | None, Header(alias="X-Chunk-Sha256")] = None,
) -> UploadOut:
    """Append one part (raw bytes) at ``Upload-Offset``. A wrong offset answers 409
    with the expected offset in the ``Upload-Offset`` header."""
    data = await _read_body(request, settings.upload_chunk_bytes)

    def work() -> UploadSession:
        session = uploads.get(db, upload_id, user.id, lock=True)
        uploads.append(db, settings, session, offset, data, chunk_sha256)
        db.commit()
        return session

    try:
        session = await run_in_threadpool(work)
    except uploads.UploadError as exc:
        await run_in_threadpool(db.rollback)
        _raise(exc)
    return _out(session)


@router.post("/{upload_id}/complete", response_model=UploadOut)
def complete_upload(
    upload_id: str, user: Operator, db: DbSession, settings: AppSettings
) -> UploadOut:
    """Hand the finished file to its consumer. Idempotent: calling it again returns the
    result. ``status`` is ``COMPLETED`` (see ``result``) or ``FAILED`` (``error_message``)."""
    try:
        session = uploads.get(db, upload_id, user.id, lock=True)
        uploads.complete(db, settings, session)
    except uploads.UploadError as exc:
        db.rollback()
        _raise(exc)
    db.commit()
    return _out(session)


@router.delete("/{upload_id}", response_model=UploadOut)
def cancel_upload(
    upload_id: str, user: Operator, db: DbSession, settings: AppSettings
) -> UploadOut:
    try:
        session = uploads.get(db, upload_id, user.id, lock=True)
        uploads.cancel(db, settings, session)
    except uploads.UploadError as exc:
        db.rollback()
        _raise(exc)
    db.commit()
    return _out(session)
