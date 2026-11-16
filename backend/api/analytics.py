"""Analytics, learning versions and costs (Phase 14)."""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from api.deps import Admin, AppSettings, DbSession, Viewer, csrf_protect
from models.analytics import AnalyticsSnapshot, LearningVersion, Metric
from models.channels import Channel
from models.production import Variant
from models.publishing import Post
from services import audit, costs, learning, strategy, winners
from services.queue import get_redis

router = APIRouter(tags=["analytics"], dependencies=[Depends(csrf_protect)])

GROUPS = ("platform", "language", "channel", "game", "format", "hook", "hour")


def _optional_redis() -> Redis | None:
    try:
        return get_redis()
    except Exception:
        return None


def _rate(num: float, den: float) -> float | None:
    return round(num / den, 4) if den else None


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 2) if values else None


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    views = [r["views"] for r in rows if r["views"] is not None]
    inter = sum(
        (r["likes"] or 0) + (r["comments"] or 0) + (r["shares"] or 0)
        for r in rows
        if r["views"] is not None
    )
    return {
        "posts": len(rows),
        "measured": len(views),
        "views": sum(views),
        "median_views": statistics.median(views) if views else None,
        "engagement_rate": _rate(inter, sum(views)),
        "retention_pct": _mean([r["retention"] for r in rows if r["retention"] is not None]),
        "avg_view_duration_s": _mean([r["duration"] for r in rows if r["duration"] is not None]),
        "followers_gained": sum(r["followers"] or 0 for r in rows),
    }


@router.get("/analytics/overview")
def overview(
    _: Viewer,
    db: DbSession,
    settings: AppSettings,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    platform: str | None = None,
    language: str | None = None,
    game: str | None = None,
    video_format: Annotated[str | None, Query(alias="format")] = None,
    hook: str | None = None,
    hour: Annotated[int | None, Query(ge=0, le=23)] = None,
) -> dict[str, Any]:
    """Performance of the posts published in the last ``days``, filtered."""
    since = datetime.now(UTC) - timedelta(days=days)
    live = settings.publishing_mode == "live"
    query = (
        select(Post, Variant, Channel)
        .join(Variant, Variant.id == Post.variant_id)
        .join(Channel, Channel.id == Post.channel_id)
        .options(joinedload(Channel.platform))
        .where(Post.published_at.is_not(None), Post.published_at >= since)
    )
    if live:
        query = query.where(Post.is_mock.is_(False))
    records = db.execute(query).all()
    games = strategy.games_for_clips(db, [v.clip_id for _, v, _c in records])
    latest: dict[int, Metric] = {}
    for metric in db.scalars(
        select(Metric)
        .where(Metric.post_id.in_([p.id for p, _v, _c in records]))
        .order_by(Metric.measured_at)
    ):
        latest[metric.post_id] = metric  # last one wins
    rows: list[dict[str, Any]] = []
    for post, variant, channel in records:
        assert post.published_at is not None
        m = latest.get(post.id)
        row = {
            "post_id": post.id,
            "title": variant.title,
            "url": post.url,
            "is_mock": post.is_mock,
            "published_at": post.published_at.isoformat(),
            "day": post.published_at.date().isoformat(),
            "platform": channel.platform.code.value,
            "language": channel.language.value,
            "channel": channel.name,
            "game": games.get(variant.clip_id) if variant.clip_id else None,
            "format": variant.video_format,
            "hook": variant.hook_type,
            "hour": post.published_at.hour,
            "window": m.measure_window.value if m else None,
            "views": m.views if m else None,
            "likes": m.likes if m else None,
            "comments": m.comments if m else None,
            "shares": m.shares if m else None,
            "retention": m.retention_pct if m else None,
            "duration": m.avg_view_duration_s if m else None,
            "followers": m.followers_gained if m else None,
        }
        rows.append(row)
    options = {g: sorted({str(r[g]) for r in rows if r[g] is not None}) for g in GROUPS}
    wanted = {
        "platform": platform,
        "language": language,
        "game": game,
        "format": video_format,
        "hook": hook,
    }
    rows = [r for r in rows if all(v is None or r[k] == v for k, v in wanted.items())]
    if hour is not None:
        rows = [r for r in rows if r["hour"] == hour]

    timeline: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        timeline[r["day"]].append(r)
    by_group: dict[str, list[dict[str, Any]]] = {}
    for g in ("game", "format", "channel", "hook", "hour", "platform"):
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            if r[g] is not None:
                buckets[str(r[g])].append(r)
        by_group[g] = sorted(
            ({"key": k, **_summarize(v)} for k, v in buckets.items()),
            key=lambda x: -(x["views"] or 0),
        )
    measured = [r for r in rows if r["views"] is not None]
    ranked = sorted(measured, key=lambda r: r["views"], reverse=True)
    keep = ("post_id", "title", "url", "channel", "game", "format", "views", "window", "is_mock")
    return {
        "days": days,
        "test_data": any(r["is_mock"] for r in rows),
        "totals": _summarize(rows),
        "timeline": [{"day": d, **_summarize(v)} for d, v in sorted(timeline.items())],
        "groups": by_group,
        "top": [{k: r[k] for k in keep} for r in ranked[:5]],
        "weak": [{k: r[k] for k in keep} for r in ranked[-5:][::-1]] if len(ranked) > 5 else [],
        "options": options,
    }


@router.get("/analytics/reports")
def reports(_: Viewer, db: DbSession) -> list[dict[str, Any]]:
    """Latest daily report per channel."""
    rows = db.execute(
        select(AnalyticsSnapshot, Channel.name)
        .join(Channel, Channel.id == AnalyticsSnapshot.channel_id)
        .where(AnalyticsSnapshot.scope == "channel_daily")
        .order_by(AnalyticsSnapshot.created_at.desc())
        .limit(200)
    ).all()
    seen: set[int] = set()
    out = []
    for snap, name in rows:
        if snap.channel_id in seen:
            continue
        seen.add(snap.channel_id or 0)
        out.append(
            {
                "channel_id": snap.channel_id,
                "channel": name,
                "created_at": snap.created_at.isoformat(),
                **snap.data,
            }
        )
    return out


class LearningOut(BaseModel):
    version: int
    status: str
    created_at: datetime
    weights: dict[str, Any]
    reasons: list[str]
    trial_until: datetime | None
    evaluation: dict[str, Any]
    created_by: str
    rolled_back_to: int | None
    baseline: float | None = None


def _learning_out(v: LearningVersion) -> LearningOut:
    return LearningOut(
        version=v.version,
        status=v.status,
        created_at=v.created_at,
        weights=v.weights or {},
        reasons=[str(r) for r in v.reasons or []],
        trial_until=v.trial_until,
        evaluation=v.evaluation or {},
        created_by=v.created_by,
        rolled_back_to=v.rolled_back_to,
        baseline=(v.evidence or {}).get("baseline"),
    )


@router.get("/analytics/learning", response_model=list[LearningOut])
def learning_versions(_: Viewer, db: DbSession) -> list[LearningOut]:
    rows = db.scalars(select(LearningVersion).order_by(LearningVersion.version.desc()).limit(50))
    return [_learning_out(v) for v in rows]


@router.post("/analytics/learning/{version}/rollback", response_model=LearningOut)
def learning_rollback(version: int, admin: Admin, db: DbSession) -> LearningOut:
    try:
        restored = learning.rollback(db, version, admin.id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Version not found") from exc
    audit.record(
        db,
        "learning.rollback",
        user_id=admin.id,
        entity_type="learning_versions",
        entity_id=restored.id,
        after={"version": restored.version, "to": version},
    )
    db.commit()
    return _learning_out(restored)


class HooksOut(BaseModel):
    tests: list[dict[str, Any]]
    balance: list[dict[str, Any]]
    winners: list[dict[str, Any]]
    winner_score: float
    recycle_after_days: int


@router.get("/analytics/hooks", response_model=HooksOut)
def hook_report(_: Viewer, db: DbSession, settings: AppSettings) -> HooksOut:
    """A7: hook A/B tests per clip and channel, wins per hook type, recent winners."""
    scored = winners.scored_posts(db, include_mock=settings.publishing_mode != "live")
    tests = winners.hook_tests(scored)
    recycled = {
        int(v.concept["recycle_of"]): v
        for v in db.scalars(
            select(Variant).where(Variant.concept["recycle_of"].as_integer().is_not(None))
        )
    }
    best = sorted((x for x in scored if x.score >= winners.WINNER_SCORE), key=lambda x: -x.score)[
        :20
    ]
    return HooksOut(
        tests=[t.as_dict() for t in tests[:50]],
        balance=[b.as_dict() for b in winners.balance(tests)],
        winners=[
            {
                "post_id": x.post.id,
                "variant_id": x.variant.id,
                "title": x.variant.title,
                "channel": x.channel.name,
                "score": round(x.score, 2),
                "hook_type": x.variant.hook_type,
                "published_at": x.post.published_at,
                "recycled_variant_id": recycled[x.variant.id].id
                if x.variant.id in recycled
                else None,
                "new_hook": recycled[x.variant.id].hook_type if x.variant.id in recycled else None,
            }
            for x in best
        ],
        winner_score=winners.WINNER_SCORE,
        recycle_after_days=winners.RECYCLE_AFTER_DAYS,
    )


@router.get("/costs/summary")
def cost_summary(
    _: Viewer,
    db: DbSession,
    settings: AppSettings,
    redis: Annotated[Redis | None, Depends(_optional_redis)],
) -> dict[str, Any]:
    return costs.summary(db, settings, redis)
