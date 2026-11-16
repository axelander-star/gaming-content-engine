"""Cut a long video of the media library into shorts (Ausbau A6).

The operator picks a long own video (a stream, a let's play, a recorded talk) and
says how many shorts of which length. The Media Library agent then

1. rates every window of the wanted length with the same local signals as the
   clip pipeline (motion, loudness, shot changes; :mod:`services.analysis`),
2. takes the best windows that do not overlap, snapped to shot changes,
3. renders each as 9:16 MP4 (crop around the action or blurred full frame,
   :mod:`services.render`) and stores it as a new library video that points to
   the long one (``parent_item_id``).

All local with FFmpeg and OpenCV: no cost. The shorts are ordinary library videos:
the approval center prepares them for the channels, nothing is posted by itself.
Only videos of the operator (uploads with rights confirmation, or own productions)
can be split; the shorts carry that confirmation over.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import LibraryKind, LibraryOrigin, LibraryStatus
from models.library import LibraryItem
from services import analysis, library, media, render, storage

MIN_SOURCE_S = 60.0
MIN_LENGTH_S = 10.0
MAX_LENGTH_S = 90.0
MAX_COUNT = 10
BUSY = ("queued", "running")


class SplitError(ValueError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def suggestion(duration_s: float) -> dict[str, Any]:
    """Default count and length: about one short per two minutes, 3 to 8."""
    count = max(3, min(8, int(duration_s // 120)))
    return {"count": count, "length_s": 30.0}


def check(item: LibraryItem) -> str | None:
    """Why this item cannot be split, or ``None``."""
    if item.kind != LibraryKind.VIDEO:
        return "Nur Videos lassen sich zerlegen"
    if item.archived_at is not None:
        return "Das Video ist archiviert"
    if item.status != LibraryStatus.READY:
        return "Das Video ist noch nicht fertig verarbeitet"
    if item.parent_item_id is not None:
        return "Das ist schon ein Ausschnitt"
    if item.original_deleted_at is not None:
        return "Das Original wurde nach der Aufbewahrungsfrist gelöscht"
    if (item.duration_s or 0) < MIN_SOURCE_S:
        return f"Erst ab {MIN_SOURCE_S:.0f} Sekunden lohnt sich das Zerlegen"
    return None


def request(
    session: Session,
    item: LibraryItem,
    *,
    count: int | None = None,
    length_s: float | None = None,
    user_id: int | None = None,
) -> LibraryItem:
    problem = check(item)
    if problem:
        raise SplitError(problem)
    if item.split_state in BUSY:
        raise SplitError("Das Zerlegen läuft schon", 409)
    default = suggestion(item.duration_s or 0)
    count = default["count"] if count is None else count
    length = float(default["length_s"] if length_s is None else length_s)
    if not 1 <= count <= MAX_COUNT:
        raise SplitError(f"1 bis {MAX_COUNT} Shorts")
    if not MIN_LENGTH_S <= length <= MAX_LENGTH_S:
        raise SplitError(f"Länge {MIN_LENGTH_S:.0f} bis {MAX_LENGTH_S:.0f} Sekunden")
    if count * length > (item.duration_s or 0):
        raise SplitError("So viele Shorts dieser Länge passen nicht in das Video")
    item.split_state = "queued"
    item.split_info = {
        "count": count,
        "length_s": length,
        "requested_by": user_id,
        "requested_at": datetime.now(UTC).isoformat(),
    }
    session.flush()
    return item


def pending(session: Session, limit: int = 1) -> list[LibraryItem]:
    return list(
        session.scalars(
            select(LibraryItem)
            .where(LibraryItem.split_state == "queued", LibraryItem.archived_at.is_(None))
            .order_by(LibraryItem.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )


def children(session: Session, item_id: int) -> list[LibraryItem]:
    return list(
        session.scalars(
            select(LibraryItem)
            .where(LibraryItem.parent_item_id == item_id)
            .order_by(LibraryItem.id)
        )
    )


def _clock(seconds: float) -> str:
    m, s = divmod(round(seconds), 60)
    return f"{m}:{s:02d}"


def run(session: Session, settings: Settings, item: LibraryItem) -> dict[str, Any]:
    """Find the best windows and render them; never raises for media errors."""
    info = dict(item.split_info or {})
    count = int(info.get("count") or 3)
    length = float(info.get("length_s") or 30.0)
    item.split_state = "running"
    session.flush()
    began = time.monotonic()
    try:
        problem = check(item)
        if problem:
            raise SplitError(problem)
        src = storage.resolve(settings, item.original_uri)
        probe = media.probe(settings, src)
        tuned = settings.model_copy(
            update={
                "clip_target_s": length,
                "clip_min_s": max(MIN_LENGTH_S, length * 0.7),
                "clip_max_s": min(MAX_LENGTH_S + 10, length * 1.3),
            }
        )
        features = analysis.extract(settings, src, probe)
        found = analysis.find_scenes(tuned, features, limit=count)
        if not found:
            raise SplitError("Keine passenden Stellen gefunden")
        made = []
        for n, cand in enumerate(sorted(found, key=lambda c: c.start_s), start=1):
            result = render.render(
                settings,
                src,
                probe,
                cand.start_s,
                cand.end_s,
                cand.focus_x,
                cand.spread,
                folder="library/video",
            )
            short = _store(session, settings, item, result, n, cand)
            made.append(
                {
                    "item_id": short.id,
                    "start_s": cand.start_s,
                    "end_s": cand.end_s,
                    "score": cand.score,
                    "layout": result.plan.layout,
                }
            )
    except (SplitError, media.MediaError, render.RenderError, storage.StorageError) as exc:
        item.split_state = "failed"
        item.split_info = {**info, "error": str(exc)[:500]}
        session.flush()
        return {"item_id": item.id, "status": "failed", "error": str(exc)[:500]}
    took = round(time.monotonic() - began, 1)
    item.split_state = "done"
    item.split_info = {**info, "made": made, "seconds": took, "error": None}
    session.flush()
    return {"item_id": item.id, "status": "done", "made": made, "seconds": took}


def _store(
    session: Session,
    settings: Settings,
    parent: LibraryItem,
    result: render.RenderResult,
    n: int,
    cand: analysis.Candidate,
) -> LibraryItem:
    existing = session.scalar(
        select(LibraryItem).where(
            LibraryItem.content_project_id == parent.content_project_id,
            LibraryItem.original_sha256 == result.stored.sha256,
        )
    )
    if existing is not None:  # same window cut before: reuse it
        return existing
    path = storage.resolve(settings, result.stored.uri)
    out = result.probe
    short = LibraryItem(
        content_project_id=parent.content_project_id,
        kind=LibraryKind.VIDEO,
        # made by the engine from the operator's own video; kept like own productions
        origin=LibraryOrigin.GENERATED,
        status=LibraryStatus.READY,
        title=f"{parent.title} – Teil {n}"[:300],
        filename=None,
        content_type="video/mp4",
        original_uri=result.stored.uri,
        original_sha256=result.stored.sha256,
        size_bytes=result.stored.size,
        duration_s=out.duration_s,
        width=out.width,
        height=out.height,
        fps=out.fps,
        video_codec=out.video_codec,
        audio_codec=out.audio_codec,
        orientation=library.orientation(out.width, out.height),
        rendition_uri=result.stored.uri,
        rendition={
            "width": out.width,
            "height": out.height,
            "layout": result.plan.layout,
            "cut": [cand.start_s, cand.end_s],
        },
        thumb_uri=library.make_thumb(settings, path, LibraryKind.VIDEO, out.duration_s),
        render_seconds=result.render_seconds,
        rights={
            **(parent.rights or {}),
            "cut_from": parent.id,
            "origin": parent.origin.value,
        },
        tags=list(parent.tags or []),
        note=f"Ausschnitt {_clock(cand.start_s)}–{_clock(cand.end_s)} aus „{parent.title}“"[:2000],
        uploaded_by_user_id=parent.uploaded_by_user_id,
        parent_item_id=parent.id,
    )
    session.add(short)
    session.flush()
    return short
