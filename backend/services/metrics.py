"""Post metrics per measurement window (PROJECT_SPEC sections 3 and 6, Phase 14).

Every post is measured at fixed windows after publication (1 h, 6 h, 24 h, 48 h,
7 days) so posts are compared at the same age. A window that was missed by more
than its tolerance is skipped, never filled with later numbers.

Sources (checked 14.11.2026, docs/API_INTEGRATIONS.md):

* test posts (mock): deterministic synthetic numbers, marked ``raw.mock``; they
  never mix with real posts (strategy and learning use one or the other),
* YouTube: ``videos.list part=statistics`` (views, likes, comments) and, if the
  ``yt-analytics.readonly`` scope was granted, ``youtubeanalytics/v2/reports``
  (average view duration and percentage, shares, subscribers gained),
* TikTok: ``POST /v2/video/query/`` (scope ``video.list``; only public posts have
  a post id),
* Instagram: ``GET /{media-id}/insights`` (``instagram_manage_insights``),
* Facebook: ``GET /{video-id}/video_insights`` (``read_insights``).

A missing permission or an unsupported post means "no numbers", never invented
numbers.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import MetricWindow, PlatformCode
from models.channels import Channel, ChannelCredential
from models.publishing import Post
from services import meta, platform, tiktok, youtube

WINDOWS: tuple[tuple[MetricWindow, timedelta], ...] = (
    (MetricWindow.H1, timedelta(hours=1)),
    (MetricWindow.H6, timedelta(hours=6)),
    (MetricWindow.H24, timedelta(hours=24)),
    (MetricWindow.H48, timedelta(hours=48)),
    (MetricWindow.D7, timedelta(days=7)),
)
LAST_WINDOW = WINDOWS[-1][1]

YT_ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
YT_ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
TIKTOK_VIDEO_QUERY = f"{tiktok.API}/video/query/"
TIKTOK_LIST_SCOPE = "video.list"
IG_INSIGHTS_SCOPE = "instagram_manage_insights"
FB_INSIGHTS_SCOPE = "read_insights"
IG_METRICS = "views,reach,likes,comments,shares,saved,ig_reels_avg_watch_time"
FB_METRICS = (
    "fb_reels_total_plays,post_video_avg_time_watched,post_video_social_actions,"
    "post_video_followers,post_impressions_unique"
)


def tolerance(delta: timedelta) -> timedelta:
    """How late a window may still be measured (at least 2 h, else a quarter)."""
    return max(timedelta(hours=2), delta / 4)


def due_window(
    published_at: datetime, measured: set[MetricWindow], now: datetime
) -> MetricWindow | None:
    """The latest elapsed, not yet measured window that is still within tolerance."""
    age = now - published_at
    for window, delta in reversed(WINDOWS):
        if age < delta:
            continue
        if window in measured:
            return None  # a later window exists, earlier ones are history
        return window if age <= delta + tolerance(delta) else None
    return None


@dataclass
class Snapshot:
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    watch_time_s: float | None = None
    avg_view_duration_s: float | None = None
    retention_pct: float | None = None
    followers_gained: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def empty(self) -> bool:
        return all(
            getattr(self, f) is None
            for f in ("views", "likes", "comments", "shares", "saves", "avg_view_duration_s")
        )


# --- test posts ---------------------------------------------------------------------

_GROWTH = {
    MetricWindow.H1: 0.06,
    MetricWindow.H6: 0.25,
    MetricWindow.H24: 0.6,
    MetricWindow.H48: 0.8,
    MetricWindow.D7: 1.0,
}


def mock_snapshot(post_id: int, window: MetricWindow, quality: float | None) -> Snapshot:
    """Deterministic test numbers: same post and window, same values."""
    rnd = random.Random(post_id * 7919)  # noqa: S311 - test numbers, not security
    base = rnd.lognormvariate(7.0, 0.8) * (0.6 + (quality or 0.7))
    views = int(base * _GROWTH.get(window, 1.0))
    retention = round(min(95.0, 30 + rnd.random() * 40 + 10 * (quality or 0.7)), 1)
    return Snapshot(
        views=views,
        likes=int(views * (0.03 + rnd.random() * 0.05)),
        comments=int(views * rnd.random() * 0.006),
        shares=int(views * rnd.random() * 0.01),
        saves=int(views * rnd.random() * 0.008),
        avg_view_duration_s=round(8 + rnd.random() * 20, 1),
        retention_pct=retention,
        followers_gained=int(views * rnd.random() * 0.004),
        raw={"mock": True},
    )


# --- live sources -------------------------------------------------------------------


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _youtube(session: Session, settings: Settings, cred: ChannelCredential, post: Post) -> Snapshot:
    token = youtube.access_token(session, settings, cred)
    auth = {"Authorization": f"Bearer {token}"}
    with youtube.http_client(30) as client:
        res = client.get(
            f"{youtube.API}/videos",
            params={"part": "statistics", "id": post.external_post_id},
            headers=auth,
        )
        if res.status_code >= 400:
            youtube._raise_for(res, "Statistik")
        items = youtube._json(res).get("items") or []
        stats = (items[0].get("statistics") or {}) if items else {}
        snap = Snapshot(
            views=_int(stats.get("viewCount")),
            likes=_int(stats.get("likeCount")),
            comments=_int(stats.get("commentCount")),
            raw={"statistics": stats},
        )
        if YT_ANALYTICS_SCOPE not in (cred.scopes or []) or post.published_at is None:
            return snap
        res = client.get(
            YT_ANALYTICS_URL,
            params={
                "ids": "channel==MINE",
                "startDate": post.published_at.date().isoformat(),
                "endDate": datetime.now(UTC).date().isoformat(),
                "metrics": "averageViewDuration,averageViewPercentage,shares,subscribersGained",
                "filters": f"video=={post.external_post_id}",
            },
            headers=auth,
        )
    if res.status_code < 400:
        rows = youtube._json(res).get("rows") or []
        if rows:  # no rows = data not available yet (it lags behind)
            duration, percentage, shares, subs = (rows[0] + [None] * 4)[:4]
            snap.avg_view_duration_s = _float(duration)
            snap.retention_pct = _float(percentage)
            snap.shares = _int(shares)
            snap.followers_gained = _int(subs)
            snap.raw["analytics"] = rows[0]
    return snap


def _tiktok(session: Session, settings: Settings, cred: ChannelCredential, post: Post) -> Snapshot:
    if TIKTOK_LIST_SCOPE not in (cred.scopes or []) or not (post.external_post_id or "").isdigit():
        return Snapshot(raw={"unavailable": "no public post id or video.list scope"})
    token = tiktok.access_token(session, settings, cred)
    with platform.http_client(30) as client:
        res = client.post(
            TIKTOK_VIDEO_QUERY,
            params={"fields": "id,view_count,like_count,comment_count,share_count"},
            json={"filters": {"video_ids": [post.external_post_id]}},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
    videos = tiktok._check(res, "Statistik").get("videos") or []
    v = videos[0] if videos else {}
    return Snapshot(
        views=_int(v.get("view_count")),
        likes=_int(v.get("like_count")),
        comments=_int(v.get("comment_count")),
        shares=_int(v.get("share_count")),
        raw={"video": v},
    )


def _insight_values(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in payload.get("data") or []:
        values = item.get("values") or []
        if values:
            out[str(item.get("name"))] = values[0].get("value")
        elif item.get("total_value"):
            out[str(item.get("name"))] = (item.get("total_value") or {}).get("value")
    return out


def _instagram(settings: Settings, cred: ChannelCredential, post: Post) -> Snapshot:
    if IG_INSIGHTS_SCOPE not in (cred.scopes or []):
        return Snapshot(raw={"unavailable": "instagram_manage_insights missing"})
    data = meta._get(
        f"{post.external_post_id}/insights",
        {"metric": IG_METRICS, "access_token": meta.page_token(settings, cred)},
        "Statistik",
    )
    v = _insight_values(data)
    avg_ms = _float(v.get("ig_reels_avg_watch_time"))
    return Snapshot(
        views=_int(v.get("views")),
        likes=_int(v.get("likes")),
        comments=_int(v.get("comments")),
        shares=_int(v.get("shares")),
        saves=_int(v.get("saved")),
        avg_view_duration_s=avg_ms / 1000 if avg_ms is not None else None,
        raw={"insights": v},
    )


def _facebook(settings: Settings, cred: ChannelCredential, post: Post) -> Snapshot:
    if FB_INSIGHTS_SCOPE not in (cred.scopes or []):
        return Snapshot(raw={"unavailable": "read_insights missing"})
    data = meta._get(
        f"{post.external_post_id}/video_insights",
        {"metric": FB_METRICS, "access_token": meta.page_token(settings, cred)},
        "Statistik",
    )
    v = _insight_values(data)
    avg_ms = _float(v.get("post_video_avg_time_watched"))
    return Snapshot(
        views=_int(v.get("fb_reels_total_plays")),
        avg_view_duration_s=avg_ms / 1000 if avg_ms is not None else None,
        followers_gained=_int(v.get("post_video_followers")),
        raw={"insights": v},
    )


def fetch(
    session: Session,
    settings: Settings,
    channel: Channel,
    post: Post,
    window: MetricWindow,
    quality: float | None,
) -> Snapshot:
    """Numbers of ``post`` now. Raises the errors of :mod:`services.platform`."""
    if post.is_mock:
        return mock_snapshot(post.id, window, quality)
    cred = session.scalar(
        select(ChannelCredential).where(ChannelCredential.channel_id == channel.id)
    )
    if cred is None:
        raise platform.AuthExpiredError("Kanal ist nicht verbunden")
    code = PlatformCode(channel.platform.code)
    try:
        if code == PlatformCode.YOUTUBE:
            return _youtube(session, settings, cred, post)
        if code == PlatformCode.TIKTOK:
            return _tiktok(session, settings, cred, post)
        if code == PlatformCode.INSTAGRAM:
            return _instagram(settings, cred, post)
        return _facebook(settings, cred, post)
    except httpx.HTTPError as exc:
        raise platform.TransientError(f"Statistik nicht erreichbar: {type(exc).__name__}") from exc
