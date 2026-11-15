"""Resumable uploads in parts, independent of what the file is for.

Large files cannot go through Cloudflare in one request (100 MB per request on the
free plan), and a dropped connection must not mean starting over. The protocol:

1. ``create``   -> session with ``id``, ``chunk_bytes`` and ``received_bytes = 0``
2. ``append``   -> one part at ``offset == received_bytes`` (otherwise a conflict
   that tells the client where to continue); optional SHA-256 per part
3. ``status``   -> ``received_bytes`` to resume after an interruption
4. ``complete`` -> checks size (and the declared SHA-256), then hands the file to
   the consumer registered for ``purpose``; idempotent
5. ``cancel``   -> deletes the partial file

Consumers (``register_consumer``) decide what happens with the finished file:
``material`` registers licensed gameplay (api/rights.py); further consumers such as a
media library plug in the same way. Partial files live below ``MEDIA_ROOT/tmp/uploads``
and are removed when a session ends or expires (``purge_expired``).
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import UploadStatus
from models.uploads import UploadSession
from services import audit, storage

log = logging.getLogger(__name__)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
#: Partial files without an open session are deleted once they are this old.
STRAY_MIN_AGE_S = 3600


class UploadError(Exception):
    """Request cannot be served; ``status`` is the HTTP status the API answers with."""

    def __init__(self, status: int, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.extra = extra


@dataclass(frozen=True)
class Consumer:
    """What a finished upload is for.

    ``validate(db, settings, user_id, params)`` checks the fields before any byte is
    sent and returns the normalised params. ``accept(db, settings, session, path)``
    takes the complete file (it may move or delete it) and returns a JSON-able result.
    Raising :class:`UploadError` in either marks the request or the session as failed.
    """

    allowed_types: dict[str, str]  # content type -> file suffix
    validate: Callable[[Session, Settings, int, dict[str, Any]], dict[str, Any]]
    accept: Callable[[Session, Settings, UploadSession, Path], dict[str, Any]]
    max_bytes: Callable[[Settings], int] = field(default=lambda s: s.max_upload_bytes)
    #: Called with the result after the completed upload was committed (e.g. to queue
    #: follow-up work). Errors are logged and never undo the upload.
    after_commit: Callable[[dict[str, Any]], None] | None = None


_CONSUMERS: dict[str, Consumer] = {}


def register_consumer(purpose: str, consumer: Consumer) -> None:
    _CONSUMERS[purpose] = consumer


def consumer_for(purpose: str) -> Consumer:
    try:
        return _CONSUMERS[purpose]
    except KeyError:
        raise UploadError(422, f"Unknown upload purpose '{purpose}'") from None


def upload_dir(settings: Settings) -> Path:
    path = storage.work_dir(settings) / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def part_path(settings: Settings, session: UploadSession) -> Path:
    return upload_dir(settings) / f"{session.id}.part"


def _now() -> datetime:
    return datetime.now(UTC)


def _safe_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name.strip()
    return (base or "upload")[:255]


def create(
    db: Session,
    settings: Settings,
    *,
    user_id: int,
    purpose: str,
    filename: str,
    size_bytes: int,
    content_type: str,
    params: dict[str, Any] | None = None,
    sha256: str | None = None,
) -> UploadSession:
    consumer = consumer_for(purpose)
    if content_type not in consumer.allowed_types:
        allowed = ", ".join(sorted(consumer.allowed_types))
        raise UploadError(422, f"File type not accepted (allowed: {allowed})")
    if size_bytes <= 0:
        raise UploadError(422, "Empty file")
    if size_bytes > consumer.max_bytes(settings):
        raise UploadError(413, "File too large")
    if sha256 is not None and not _SHA256.match(sha256.lower()):
        raise UploadError(422, "sha256 must be 64 hex characters")
    clean = consumer.validate(db, settings, user_id, dict(params or {}))
    session = UploadSession(
        id=uuid.uuid4().hex,
        user_id=user_id,
        purpose=purpose,
        filename=_safe_name(filename),
        content_type=content_type,
        size_bytes=size_bytes,
        received_bytes=0,
        chunk_bytes=settings.upload_chunk_bytes,
        expected_sha256=sha256.lower() if sha256 else None,
        status=UploadStatus.UPLOADING,
        params=clean,
        expires_at=_now() + timedelta(hours=settings.upload_session_ttl_hours),
    )
    db.add(session)
    db.flush()
    part_path(settings, session).touch()
    audit.record(
        db,
        "upload.create",
        user_id=user_id,
        entity_type="upload_sessions",
        after={"id": session.id, "purpose": purpose, "size": size_bytes},
    )
    return session


def get(db: Session, upload_id: str, user_id: int, *, lock: bool = False) -> UploadSession:
    """The caller's own session; anything else looks like it does not exist."""
    query = select(UploadSession).where(UploadSession.id == upload_id)
    if lock:
        query = query.with_for_update()
    session = db.scalar(query)
    if session is None or session.user_id != user_id:
        raise UploadError(404, "Upload not found")
    return session


def _require_open(session: UploadSession) -> None:
    if session.status != UploadStatus.UPLOADING:
        raise UploadError(409, f"Upload is {session.status.value}")
    if session.expires_at <= _now():
        raise UploadError(410, "Upload expired")


def append(
    db: Session,
    settings: Settings,
    session: UploadSession,
    offset: int,
    data: bytes,
    chunk_sha256: str | None = None,
) -> UploadSession:
    """Write one part at ``offset``. The session row must be locked by the caller."""
    _require_open(session)
    if offset != session.received_bytes:
        raise UploadError(
            409, "Offset does not match the received bytes", received_bytes=session.received_bytes
        )
    if not data:
        raise UploadError(422, "Empty part")
    if len(data) > session.chunk_bytes:
        raise UploadError(413, f"Part larger than {session.chunk_bytes} bytes")
    if offset + len(data) > session.size_bytes:
        raise UploadError(413, "Part goes beyond the declared file size")
    if chunk_sha256 is not None and hashlib.sha256(data).hexdigest() != chunk_sha256.lower():
        raise UploadError(422, "Part checksum mismatch", received_bytes=session.received_bytes)
    path = part_path(settings, session)
    # Seek + truncate: a part written before a crash but never committed is overwritten.
    with path.open("r+b" if path.exists() else "w+b") as fh:
        fh.seek(offset)
        fh.write(data)
        fh.truncate()
    session.received_bytes = offset + len(data)
    # Activity keeps the session alive.
    session.expires_at = _now() + timedelta(hours=settings.upload_session_ttl_hours)
    db.flush()
    return session


def complete(db: Session, settings: Settings, session: UploadSession) -> UploadSession:
    """Hand the finished file to its consumer. Safe to call again (returns the state)."""
    if session.status in (UploadStatus.COMPLETED, UploadStatus.PROCESSING):
        return session
    _require_open(session)
    if session.received_bytes != session.size_bytes:
        raise UploadError(409, "Upload is not complete yet", received_bytes=session.received_bytes)
    path = part_path(settings, session)
    if not path.is_file() or path.stat().st_size != session.size_bytes:
        _fail(db, settings, session, "Partial file missing or wrong size")
        return session
    if session.expected_sha256 and storage.sha256_file(path) != session.expected_sha256:
        _fail(db, settings, session, "SHA-256 of the file does not match")
        return session
    session.status = UploadStatus.PROCESSING
    db.flush()
    consumer = consumer_for(session.purpose)
    try:
        # Savepoint: a failing consumer leaves no half-written rows behind.
        with db.begin_nested():
            result = consumer.accept(db, settings, session, path)
    except UploadError as exc:
        _fail(db, settings, session, exc.detail)
        return session
    except Exception:
        log.exception("upload consumer failed", extra={"upload": session.id})
        _fail(db, settings, session, "Processing failed")
        return session
    session.status = UploadStatus.COMPLETED
    session.result = result
    path.unlink(missing_ok=True)
    audit.record(
        db,
        "upload.complete",
        user_id=session.user_id,
        entity_type="upload_sessions",
        after={"id": session.id, "purpose": session.purpose, "result": result},
    )
    db.flush()
    return session


def run_after_commit(session: UploadSession) -> None:
    """Follow-up of the consumer once the completed upload is committed."""
    if session.status != UploadStatus.COMPLETED or not session.result:
        return
    hook = consumer_for(session.purpose).after_commit
    if hook is None:
        return
    try:
        hook(dict(session.result))
    except Exception:
        log.exception("upload follow-up failed", extra={"upload": session.id})


def _fail(db: Session, settings: Settings, session: UploadSession, message: str) -> None:
    session.status = UploadStatus.FAILED
    session.error_message = message
    part_path(settings, session).unlink(missing_ok=True)
    db.flush()


def cancel(db: Session, settings: Settings, session: UploadSession) -> UploadSession:
    if session.status in (UploadStatus.UPLOADING, UploadStatus.FAILED):
        session.status = UploadStatus.CANCELLED
        part_path(settings, session).unlink(missing_ok=True)
        db.flush()
    return session


def purge_expired(db: Session, settings: Settings) -> int:
    """Remove expired unfinished sessions and stray partial files; returns the count."""
    now = _now()
    expired = db.scalars(
        select(UploadSession).where(
            UploadSession.status == UploadStatus.UPLOADING, UploadSession.expires_at <= now
        )
    ).all()
    for session in expired:
        session.status = UploadStatus.CANCELLED
        session.error_message = "expired"
        part_path(settings, session).unlink(missing_ok=True)
    open_ids = set(
        db.scalars(
            select(UploadSession.id).where(UploadSession.status == UploadStatus.UPLOADING)
        ).all()
    )
    stray = 0
    cutoff = now.timestamp() - STRAY_MIN_AGE_S
    for path in upload_dir(settings).glob("*.part"):
        # Age check: a session created a moment ago may not be committed yet.
        if path.stem not in open_ids and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            stray += 1
    db.flush()
    if expired or stray:
        log.info("uploads purged", extra={"expired": len(expired), "stray_files": stray})
    return len(expired) + stray
