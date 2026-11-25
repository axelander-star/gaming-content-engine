"""Competitor radar (Ausbau A5): what works for other channels in the same niche.

Only YouTube, only public data, only the official Data API v3 (checked against the
documentation on 16.11.2026; quota cost in brackets):

* ``channels.list?part=snippet,contentDetails&forHandle=@name`` (1 unit) finds the
  channel and its uploads playlist (``contentDetails.relatedPlaylists.uploads``);
* ``playlistItems.list?part=contentDetails&playlistId=…&maxResults=20`` (1 unit)
  lists the newest uploads;
* ``videos.list?part=snippet,statistics&id=…`` (1 unit) gives titles and views.

So one check costs 2–3 of the 10,000 free daily units. TikTok and Instagram have
no official API for other accounts' videos; they are not watched.

A video "stands out" when it has at least ``OUTLIER_FACTOR`` times the channel's
usual views (median of its recent videos). Those go to the idea lab as research
items: the idea lab does not copy them, it takes the topic as a hint.
Without ``YOUTUBE_API_KEY`` and ``TREND_SOURCES_MODE=live`` the radar shows
labelled test videos.
"""

from __future__ import annotations

import hashlib
import re
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import PlatformCode
from models.competitors import Competitor, CompetitorVideo
from models.projects import ContentProject
from models.research import ResearchItem

API = "https://www.googleapis.com/youtube/v3"
OUTLIER_FACTOR = 3.0
FRESH_DAYS = 21
MAX_VIDEOS = 20
MAX_PER_PROJECT = 30
_HANDLE = re.compile(r"^[A-Za-z0-9._-]{3,30}$")

#: Tests swap in an ``httpx.MockTransport``.
TRANSPORT: httpx.BaseTransport | None = None


class RadarError(ValueError):
    pass


def live(settings: Settings) -> bool:
    return bool(settings.youtube_api_key.get_secret_value()) and (
        settings.trend_sources_mode == "live"
    )


def normalize(raw: str) -> str:
    """``https://youtube.com/@Name``, ``@Name`` or ``Name`` -> ``@Name``."""
    text = raw.strip()
    m = re.search(r"youtube\.com/@([^/?#\s]+)", text)
    if m:
        text = m.group(1)
    text = text.lstrip("@")
    if not _HANDLE.match(text):
        raise RadarError("Bitte den YouTube-Namen mit @ angeben, z. B. @kanalname.")
    return f"@{text}"


def add(
    session: Session,
    project: ContentProject,
    raw_handle: str,
    user_id: int | None = None,
) -> Competitor:
    handle = normalize(raw_handle)
    exists = session.scalar(
        select(Competitor).where(
            Competitor.content_project_id == project.id,
            Competitor.platform == PlatformCode.YOUTUBE,
            Competitor.handle == handle,
        )
    )
    if exists is not None:
        exists.active = True
        session.flush()
        return exists
    count = len(
        session.scalars(
            select(Competitor.id).where(
                Competitor.content_project_id == project.id, Competitor.active.is_(True)
            )
        ).all()
    )
    if count >= MAX_PER_PROJECT:
        raise RadarError(f"Höchstens {MAX_PER_PROJECT} Kanäle je Themenbereich.")
    comp = Competitor(
        content_project_id=project.id,
        platform=PlatformCode.YOUTUBE,
        handle=handle,
        created_by_user_id=user_id,
    )
    session.add(comp)
    session.flush()
    return comp


# --- fetching --------------------------------------------------------------------------


@dataclass(frozen=True)
class Video:
    external_id: str
    title: str
    published_at: datetime | None
    views: int
    likes: int | None
    comments: int | None


def _get(http: httpx.Client, settings: Settings, path: str, **params: Any) -> dict[str, Any]:
    params["key"] = settings.youtube_api_key.get_secret_value()
    res = http.get(f"{API}/{path}", params=params)
    if res.status_code >= 400:
        # never put the URL in the error: it carries the API key
        reason = ""
        try:
            errors = res.json().get("error", {}).get("errors", [])
            reason = errors[0].get("reason", "") if errors else ""
        except ValueError:
            pass
        raise RadarError(f"YouTube antwortet mit {res.status_code} {reason}".strip())
    data: dict[str, Any] = res.json()
    return data


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_live(settings: Settings, comp: Competitor, client: httpx.Client) -> list[Video]:
    if not comp.uploads_playlist_id:
        data = _get(
            client, settings, "channels", part="snippet,contentDetails", forHandle=comp.handle
        )
        items = data.get("items") or []
        if not items:
            raise RadarError(f"Kanal {comp.handle} nicht gefunden")
        ch = items[0]
        comp.external_channel_id = str(ch.get("id") or "")[:64] or None
        comp.name = str((ch.get("snippet") or {}).get("title") or comp.handle)[:200]
        uploads = (ch.get("contentDetails") or {}).get("relatedPlaylists", {}).get("uploads")
        if not uploads:
            raise RadarError("Der Kanal hat keine öffentliche Upload-Liste")
        comp.uploads_playlist_id = str(uploads)[:64]
    playlist = _get(
        client, settings, "playlistItems",
        part="contentDetails", playlistId=comp.uploads_playlist_id, maxResults=MAX_VIDEOS,
    )  # fmt: skip
    ids = [
        str((i.get("contentDetails") or {}).get("videoId"))
        for i in playlist.get("items") or []
        if (i.get("contentDetails") or {}).get("videoId")
    ]
    if not ids:
        return []
    videos = _get(client, settings, "videos", part="snippet,statistics", id=",".join(ids))
    out = []
    for v in videos.get("items") or []:
        snippet, stats = v.get("snippet") or {}, v.get("statistics") or {}
        out.append(
            Video(
                external_id=str(v.get("id")),
                title=str(snippet.get("title") or "")[:300],
                published_at=_time(snippet.get("publishedAt")),
                views=_int(stats.get("viewCount")) or 0,
                likes=_int(stats.get("likeCount")),
                comments=_int(stats.get("commentCount")),
            )
        )
    return out


def fetch_mock(comp: Competitor, project: ContentProject, now: datetime) -> list[Video]:
    """Labelled test videos: one clearly stands out, so the flow can be tried."""
    comp.name = comp.name or f"Testkanal {comp.handle}"
    topics = [str(s) for s in project.subtopics or []] or [project.name]
    seed = int(hashlib.sha256(comp.handle.encode()).hexdigest()[:6], 16)
    out = []
    for i in range(8):
        topic = topics[(seed + i) % len(topics)]
        views = 1000 + (seed % 500) + i * 120
        if i == 1:
            views *= 6  # the stand-out
        out.append(
            Video(
                external_id=f"mock-{comp.id}-{i}",
                title=f"[Test] {topic}: Video {i + 1} von {comp.handle}",
                published_at=now - timedelta(days=2 + i * 3),
                views=views,
                likes=views // 25,
                comments=views // 200,
            )
        )
    return out


@dataclass
class ScanResult:
    checked: int = 0
    videos: int = 0
    outliers: int = 0
    items: int = 0
    errors: int = 0


def _store(
    session: Session, comp: Competitor, videos: list[Video], mock: bool, now: datetime
) -> list[CompetitorVideo]:
    rows = {
        v.external_id: v
        for v in session.scalars(
            select(CompetitorVideo).where(CompetitorVideo.competitor_id == comp.id)
        )
    }
    stored = []
    for v in videos:
        row = rows.get(v.external_id)
        if row is None:
            row = CompetitorVideo(
                competitor_id=comp.id, external_id=v.external_id, title=v.title, is_mock=mock
            )
            session.add(row)
        row.title = v.title or row.title
        row.published_at = v.published_at
        row.views, row.likes, row.comments = v.views, v.likes, v.comments
        row.url = None if mock else f"https://www.youtube.com/watch?v={v.external_id}"
        row.seen_at = now
        stored.append(row)
    session.flush()
    views = [r.views for r in stored if r.views > 0]
    usual = statistics.median(views) if len(views) >= 3 else None
    for r in stored:
        r.outlier = round(r.views / usual, 2) if usual else None
    return stored


def _to_research(session: Session, comp: Competitor, row: CompetitorVideo, now: datetime) -> bool:
    guid = hashlib.sha256(f"competitor:{comp.id}:{row.external_id}".encode()).hexdigest()
    exists = session.scalar(
        select(ResearchItem.id).where(
            ResearchItem.content_project_id == comp.content_project_id,
            ResearchItem.guid_hash == guid,
        )
    )
    if exists is not None:
        row.research_item_id = exists
        return False
    item = ResearchItem(
        content_project_id=comp.content_project_id,
        guid_hash=guid,
        title=f"Läuft bei {comp.name or comp.handle}: {row.title}"[:500],
        url=row.url,
        summary=(
            f"Konkurrenz-Radar: {f'{row.views:,}'.replace(',', '.')} Aufrufe, etwa "
            f"{row.outlier or 0:.1f}-mal so viel wie sonst auf diesem Kanal. Nicht nachmachen, "
            "sondern das Thema mit eigenem Blickwinkel aufgreifen."
        ),
        published_at=row.published_at,
        fetched_at=now,
        is_mock=row.is_mock,
    )
    session.add(item)
    session.flush()
    row.research_item_id = item.id
    return True


def scan(
    session: Session,
    settings: Settings,
    now: datetime | None = None,
    client: httpx.Client | None = None,
    project_id: int | None = None,
) -> ScanResult:
    """Check every active competitor; commits."""
    now = now or datetime.now(UTC)
    result = ScanResult()
    q = select(Competitor).where(Competitor.active.is_(True))
    if project_id is not None:
        q = q.where(Competitor.content_project_id == project_id)
    comps = list(session.scalars(q.order_by(Competitor.id)))
    use_live = live(settings)
    own = client is None and use_live
    http = client or (
        httpx.Client(timeout=settings.http_timeout_s, transport=TRANSPORT) if use_live else None
    )
    try:
        for comp in comps:
            project = session.get(ContentProject, comp.content_project_id)
            if project is None:
                continue
            result.checked += 1
            try:
                if use_live:
                    assert http is not None
                    videos = fetch_live(settings, comp, http)
                elif settings.sample_data_enabled:
                    videos = fetch_mock(comp, project, now)
                else:
                    videos = []  # production without a YouTube key: nothing invented
            except (RadarError, httpx.HTTPError, ValueError) as exc:
                comp.last_error = (
                    str(exc)[:500]
                    if isinstance(exc, RadarError)
                    else (f"Abruf fehlgeschlagen ({type(exc).__name__})")
                )
                comp.last_checked_at = now
                result.errors += 1
                continue
            comp.last_error = None
            comp.last_checked_at = now
            stored = _store(session, comp, videos, not use_live, now)
            result.videos += len(stored)
            for row in stored:
                fresh = row.published_at is None or row.published_at >= now - timedelta(
                    days=FRESH_DAYS
                )
                if row.outlier and row.outlier >= OUTLIER_FACTOR and fresh:
                    result.outliers += 1
                    if row.research_item_id is None and _to_research(session, comp, row, now):
                        result.items += 1
            session.flush()
    finally:
        if own and http is not None:
            http.close()
    session.commit()
    return result


def standouts(
    session: Session, project_id: int | None = None, days: int = FRESH_DAYS, limit: int = 30
) -> list[tuple[CompetitorVideo, Competitor]]:
    since = datetime.now(UTC) - timedelta(days=days)
    q = (
        select(CompetitorVideo, Competitor)
        .join(Competitor, Competitor.id == CompetitorVideo.competitor_id)
        .where(
            Competitor.active.is_(True),
            CompetitorVideo.outlier >= OUTLIER_FACTOR,
            CompetitorVideo.published_at >= since,
        )
        .order_by(CompetitorVideo.outlier.desc())
        .limit(limit)
    )
    if project_id is not None:
        q = q.where(Competitor.content_project_id == project_id)
    return [(v, c) for v, c in session.execute(q).all()]
