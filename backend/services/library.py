"""Media library (extension phase E7): own uploads and generated videos.

* Upload: the operator confirms per file that it is an own recording or own
  creation (``RIGHTS_STATEMENT``, stored with user and time). The file is
  checked (length, resolution, format) and stored content-addressed. The
  original is never changed.
* Processing (agent ``media_library``): preview image and a 9:16 rendition next
  to the original. Videos that are already vertical keep the original as
  rendition; very long videos keep only the original.
* Every file belongs to exactly one topic area; a production can only use files
  of its own topic area.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import LibraryKind, LibraryOrigin, LibraryStatus
from models.library import LibraryItem
from services import media, render, storage

VIDEO_TYPES = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-matroska": ".mkv"}
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
AUDIO_TYPES = {
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
}
ALLOWED_TYPES = {**VIDEO_TYPES, **IMAGE_TYPES, **AUDIO_TYPES}

RIGHTS_STATEMENT = (
    "Ich habe diese Datei selbst aufgenommen oder erstellt und darf sie auf den "
    "Plattformen dieses Themenbereichs veröffentlichen. Sie enthält keine fremden "
    "Videos, Bilder oder Musik ohne Erlaubnis."
)

MIN_SIDE_PX = 240
MIN_VIDEO_S = 1.0
THUMB_WIDTH = 360
#: Width/height ratio up to which a video counts as 9:16 already (1080/1920 = 0.5625).
VERTICAL_RATIO = 0.6


class LibraryError(ValueError):
    """A library request that is not allowed (German message, HTTP status)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def kind_for(content_type: str) -> LibraryKind:
    if content_type in VIDEO_TYPES:
        return LibraryKind.VIDEO
    if content_type in IMAGE_TYPES:
        return LibraryKind.IMAGE
    if content_type in AUDIO_TYPES:
        return LibraryKind.AUDIO
    raise LibraryError(422, "Nur MP4, MOV, MKV, PNG, JPEG, WebP, MP3, WAV oder M4A")


def orientation(width: int, height: int) -> str:
    if height > width * 1.05:
        return "portrait"
    if width > height * 1.05:
        return "landscape"
    return "square"


@dataclass(frozen=True)
class Inspection:
    kind: LibraryKind
    duration_s: float | None
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None

    @property
    def orientation(self) -> str | None:
        if self.width and self.height:
            return orientation(self.width, self.height)
        return None


def inspect(settings: Settings, path: Path, kind: LibraryKind) -> Inspection:
    """Read length, resolution and format; raises :class:`LibraryError` if unusable."""
    try:
        if kind == LibraryKind.AUDIO:
            seconds = media.duration(settings, path)
            if seconds < MIN_VIDEO_S:
                raise LibraryError(422, "Audiodatei ist kürzer als eine Sekunde")
            return Inspection(kind, round(seconds, 3), None, None, None, None, None)
        p = media.probe(settings, path)
    except media.MediaError as exc:
        raise LibraryError(422, f"Datei nicht lesbar: {exc}") from exc
    if min(p.width, p.height) < MIN_SIDE_PX:
        raise LibraryError(422, f"Auflösung zu gering ({p.width}×{p.height})")
    if kind == LibraryKind.IMAGE:
        return Inspection(kind, None, p.width, p.height, None, p.video_codec, None)
    issues = []
    if p.duration_s < MIN_VIDEO_S:
        issues.append("kürzer als eine Sekunde")
    if p.duration_s > settings.max_material_s:
        issues.append(f"länger als {settings.max_material_s / 3600:.0f} Stunden")
    if p.fps and p.fps < 15:
        issues.append(f"Bildrate zu niedrig ({p.fps:.1f} fps)")
    if issues:
        raise LibraryError(422, "Video " + ", ".join(issues))
    return Inspection(kind, p.duration_s, p.width, p.height, p.fps, p.video_codec, p.audio_codec)


def _find_duplicate(session: Session, project_id: int, sha256: str) -> LibraryItem | None:
    return session.scalar(
        select(LibraryItem).where(
            LibraryItem.content_project_id == project_id,
            LibraryItem.original_sha256 == sha256,
        )
    )


def add_upload(
    session: Session,
    settings: Settings,
    *,
    project_id: int,
    path: Path,
    filename: str,
    content_type: str,
    title: str | None,
    note: str | None,
    tags: list[str],
    user_id: int,
) -> LibraryItem:
    """Check and store an uploaded file (moved into the store) as ``PROCESSING``."""
    kind = kind_for(content_type)
    if kind == LibraryKind.IMAGE and path.stat().st_size > settings.library_max_image_bytes:
        limit = settings.library_max_image_bytes // 1024**2
        raise LibraryError(422, f"Bild größer als {limit} MB")
    info = inspect(settings, path, kind)
    digest = storage.sha256_file(path)
    dup = _find_duplicate(session, project_id, digest)
    if dup is not None:
        raise LibraryError(409, f"Diese Datei ist schon in der Mediathek („{dup.title}“)")
    stored = storage.store_path(
        settings, path, f"library/{kind.value}", ALLOWED_TYPES[content_type]
    )
    item = LibraryItem(
        content_project_id=project_id,
        kind=kind,
        origin=LibraryOrigin.UPLOAD,
        status=LibraryStatus.PROCESSING,
        title=(title or Path(filename).stem or "Upload")[:300],
        filename=filename[:255],
        content_type=content_type,
        original_uri=stored.uri,
        original_sha256=stored.sha256,
        size_bytes=stored.size,
        duration_s=info.duration_s,
        width=info.width,
        height=info.height,
        fps=info.fps,
        video_codec=info.video_codec,
        audio_codec=info.audio_codec,
        orientation=info.orientation,
        rights={
            "kind": "own_upload",
            "statement": RIGHTS_STATEMENT,
            "confirmed_by_user_id": user_id,
            "confirmed_at": datetime.now(UTC).isoformat(),
        },
        tags=tags,
        note=note,
        uploaded_by_user_id=user_id,
    )
    session.add(item)
    session.flush()
    return item


# --- processing: preview and 9:16 rendition --------------------------------------------


def _tmp(settings: Settings, suffix: str) -> Path:
    return storage.work_dir(settings) / f"lib-{uuid.uuid4().hex}{suffix}"


def make_thumb(settings: Settings, src: Path, kind: LibraryKind, duration_s: float | None) -> str:
    """JPEG preview (``THUMB_WIDTH`` wide); returns its URI."""
    out = _tmp(settings, ".jpg")
    seek = [] if kind == LibraryKind.IMAGE else ["-ss", f"{min(1.0, (duration_s or 0) / 2):.2f}"]
    try:
        media.run(
            [
                settings.ffmpeg_bin,
                "-v",
                "error",
                "-y",
                *seek,
                "-i",
                str(src),
                "-frames:v",
                "1",
                "-vf",
                f"scale={THUMB_WIDTH}:-2",
                "-q:v",
                "4",
                str(out),
            ],
            timeout=120,
        )
        return storage.store_path(settings, out, "library/thumbs", ".jpg").uri
    finally:
        out.unlink(missing_ok=True)


def image_rendition(settings: Settings, src: Path) -> storage.StoredFile:
    """9:16 JPEG: the whole picture centred on a blurred copy of itself."""
    out = _tmp(settings, ".jpg")
    graph = (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "boxblur=20:2[b];"
        "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[f];"
        "[b][f]overlay=(W-w)/2:(H-h)/2,format=yuvj420p[v]"
    )
    try:
        media.run(
            [
                settings.ffmpeg_bin,
                "-v",
                "error",
                "-y",
                "-i",
                str(src),
                "-filter_complex",
                graph,
                "-map",
                "[v]",
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(out),
            ],
            timeout=120,
        )
        return storage.store_path(settings, out, "library/renditions", ".jpg")
    finally:
        out.unlink(missing_ok=True)


def _is_vertical_ready(item: LibraryItem) -> bool:
    return bool(
        item.width
        and item.height
        and item.width / item.height <= VERTICAL_RATIO
        and item.video_codec == "h264"
        and item.content_type == "video/mp4"
    )


def process(session: Session, settings: Settings, item: LibraryItem) -> dict[str, Any]:
    """Make preview and rendition; ``READY`` afterwards. Errors mark the item ``FAILED``."""
    src = storage.resolve(settings, item.original_uri)
    began = time.monotonic()
    try:
        info: dict[str, Any]
        if item.kind == LibraryKind.AUDIO:
            info = {"skipped": "Audio hat kein Bild"}
        else:
            item.thumb_uri = make_thumb(settings, src, item.kind, item.duration_s)
            if item.kind == LibraryKind.IMAGE:
                stored = image_rendition(settings, src)
                item.rendition_uri = stored.uri
                info = {
                    "width": 1080,
                    "height": 1920,
                    "layout": "blur_fit",
                    "size_bytes": stored.size,
                }
            elif _is_vertical_ready(item):
                item.rendition_uri = item.original_uri
                info = {
                    "width": item.width,
                    "height": item.height,
                    "layout": "original",
                    "note": "Schon im Hochformat, Original wird verwendet",
                }
            elif (item.duration_s or 0) > settings.library_max_rendition_s:
                minutes = settings.library_max_rendition_s / 60
                info = {
                    "skipped": f"Länger als {minutes:.0f} min: nur das Original, "
                    "die Produktion schneidet daraus"
                }
            else:
                probe = media.probe(settings, src)
                result = render.render(
                    settings,
                    src,
                    probe,
                    0.0,
                    probe.duration_s,
                    None,
                    0.0,
                    folder="library/renditions",
                )
                item.rendition_uri = result.stored.uri
                info = {
                    "width": result.probe.width,
                    "height": result.probe.height,
                    "layout": result.plan.layout,
                    "size_bytes": result.stored.size,
                    "render_seconds": result.render_seconds,
                    "realtime_factor": result.realtime_factor,
                }
    except (media.MediaError, render.RenderError, storage.StorageError) as exc:
        item.status = LibraryStatus.FAILED
        item.error_message = str(exc)[:2000]
        session.flush()
        return {"item_id": item.id, "status": "failed", "error": item.error_message}
    item.render_seconds = round(time.monotonic() - began, 2)
    item.rendition = info
    item.status = LibraryStatus.READY
    item.error_message = None
    session.flush()
    return {"item_id": item.id, "status": "ready", **info}


def pending(session: Session, limit: int = 5) -> list[LibraryItem]:
    return list(
        session.scalars(
            select(LibraryItem)
            .where(
                LibraryItem.status == LibraryStatus.PROCESSING,
                LibraryItem.archived_at.is_(None),
            )
            .order_by(LibraryItem.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )


def add_generated(
    session: Session,
    settings: Settings,
    *,
    project_id: int,
    path: Path,
    title: str,
    rights: dict[str, Any],
    render_seconds: float,
) -> LibraryItem:
    """Store a video the own production made (already 9:16) as a ready library item."""
    probe = media.probe(settings, path)
    stored = storage.store_path(settings, path, "library/video", ".mp4")
    item = _find_duplicate(session, project_id, stored.sha256)
    if item is not None:  # identical render: reuse the existing entry
        return item
    thumb = make_thumb(
        settings, storage.resolve(settings, stored.uri), LibraryKind.VIDEO, probe.duration_s
    )
    item = LibraryItem(
        content_project_id=project_id,
        kind=LibraryKind.VIDEO,
        origin=LibraryOrigin.GENERATED,
        status=LibraryStatus.READY,
        title=title[:300],
        filename=None,
        content_type="video/mp4",
        original_uri=stored.uri,
        original_sha256=stored.sha256,
        size_bytes=stored.size,
        duration_s=probe.duration_s,
        width=probe.width,
        height=probe.height,
        fps=probe.fps,
        video_codec=probe.video_codec,
        audio_codec=probe.audio_codec,
        orientation=orientation(probe.width, probe.height),
        rendition_uri=stored.uri,
        rendition={"width": probe.width, "height": probe.height, "layout": "generated"},
        thumb_uri=thumb,
        render_seconds=render_seconds,
        rights=rights,
    )
    session.add(item)
    session.flush()
    return item


def usable_image(session: Session, project_id: int, item_id: int) -> LibraryItem:
    """An image a production of ``project_id`` may use (same topic area, ready, not archived)."""
    item = session.get(LibraryItem, item_id)
    if item is None or item.archived_at is not None:
        raise LibraryError(404, f"Bild #{item_id} nicht in der Mediathek")
    if item.content_project_id != project_id:
        raise LibraryError(409, f"Bild #{item_id} gehört zu einem anderen Themenbereich")
    if item.kind != LibraryKind.IMAGE:
        raise LibraryError(422, f"Datei #{item_id} ist kein Bild")
    if item.status != LibraryStatus.READY:
        raise LibraryError(409, f"Bild #{item_id} ist noch nicht fertig verarbeitet")
    return item
