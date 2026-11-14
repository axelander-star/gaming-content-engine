"""Cost overview for the dashboard page "Kosten" (PROJECT_SPEC sections 8 and 13).

* variable costs: the ``costs`` table (AI, TTS, API, … booked by the agents),
* fixed costs: server and other fixed monthly costs from the settings; they count
  fully against the month because they run even when production pauses,
* storage: size of the media folder; cost only if a price per GB is set,
* API usage today: the daily quota counters,
* per video: month costs / produced videos (passed quality control) and
  / published posts; per 1,000 views only if views were measured.

Test posts (mock) and their synthetic numbers are counted separately and never
enter the cost per real post or per 1,000 views.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import Settings
from models.analytics import Metric
from models.channels import Channel
from models.control import Cost
from models.production import QualityCheck
from models.publishing import Post
from services import budget, quota

GB = 1024**3
QUOTA_SOURCES = ("youtube", "twitch", "steam", "youtube_upload")


def folder_bytes(root: Path) -> int:
    total = 0
    for base, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += (Path(base) / name).stat().st_size
            except OSError:
                continue
    return total


def _per(amount: Decimal, count: int | float) -> float | None:
    return round(float(amount) / count, 4) if count else None


def summary(
    session: Session, settings: Settings, redis: Redis | None, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    start = budget.month_start(now)
    by_category = {
        str(cat.value if hasattr(cat, "value") else cat): Decimal(total or 0)
        for cat, total in session.execute(
            select(Cost.category, func.coalesce(func.sum(Cost.amount_eur), 0))
            .where(Cost.incurred_at >= start)
            .group_by(Cost.category)
        ).all()
    }
    variable = sum(by_category.values(), Decimal(0))
    server = Decimal(str(settings.server_monthly_eur))
    other_fixed = Decimal(str(settings.other_fixed_monthly_eur))
    media = Path(settings.media_root)
    size = folder_bytes(media) if media.exists() else 0
    storage = (Decimal(size) / GB * Decimal(str(settings.storage_eur_per_gb_month))).quantize(
        Decimal("0.0001")
    )
    total = variable + server + other_fixed + storage
    status = budget.budget_status(session, settings, now)

    produced = int(
        session.scalar(
            select(func.count(func.distinct(QualityCheck.variant_id))).where(
                QualityCheck.passed.is_(True), QualityCheck.checked_at >= start
            )
        )
        or 0
    )
    posts = session.execute(
        select(Post.is_mock, func.count(Post.id))
        .where(Post.published_at >= start)
        .group_by(Post.is_mock)
    ).all()
    published = {bool(mock): int(n) for mock, n in posts}
    real_views = _views(session, start, mock=False)
    mock_views = _views(session, start, mock=True)

    usage: dict[str, int] = {}
    if redis is not None:
        names = list(QUOTA_SOURCES)
        for channel_id in session.scalars(select(Channel.id)).all():
            names += [
                f"tiktok_post_{channel_id}",
                f"instagram_post_{channel_id}",
                f"facebook_reels_{channel_id}",
            ]
        for name in names:
            try:
                value = quota.used(redis, name, now)
            except Exception:
                break
            if value:
                usage[name] = value

    return {
        "month": start.date().isoformat(),
        "budget": {
            "budget_eur": float(status.budget_eur),
            "spent_eur": float(status.spent_eur),
            "used_pct": status.used_pct,
            "level": status.level.value,
            "thresholds": {
                "warn": settings.budget_warn_pct,
                "reduced": settings.budget_reduced_pct,
                "priority_only": settings.budget_priority_only_pct,
                "stop_paid": settings.budget_stop_paid_pct,
            },
        },
        "costs": {
            "server": float(server),
            "other_fixed": float(other_fixed),
            "storage": float(storage),
            "ai": float(by_category.get("ai", 0)),
            "tts": float(by_category.get("tts", 0)),
            "api": float(by_category.get("api", 0)),
            "other": float(
                sum(
                    (v for k, v in by_category.items() if k not in ("ai", "tts", "api")), Decimal(0)
                )
            ),
            "total": float(total),
        },
        "storage": {"bytes": size, "price_per_gb": settings.storage_eur_per_gb_month},
        "videos": {
            "produced": produced,
            "published": published.get(False, 0),
            "published_test": published.get(True, 0),
            "views": real_views,
            "views_test": mock_views,
        },
        "unit_costs": {
            "per_produced": _per(total, produced),
            "per_published": _per(total, published.get(False, 0)),
            "per_1000_views": _per(total * 1000, real_views),
        },
        "api_usage_today": usage,
        "prices_configured": bool(server or other_fixed or settings.storage_eur_per_gb_month),
    }


def _views(session: Session, start: datetime, mock: bool) -> int:
    """Views of the month's posts, latest measurement per post."""
    latest = (
        select(Metric.post_id, func.max(Metric.measured_at).label("at"))
        .join(Post, Post.id == Metric.post_id)
        .where(Post.published_at >= start, Post.is_mock.is_(mock), Metric.views.is_not(None))
        .group_by(Metric.post_id)
        .subquery()
    )
    total = session.scalar(
        select(func.coalesce(func.sum(Metric.views), 0)).join(
            latest, (Metric.post_id == latest.c.post_id) & (Metric.measured_at == latest.c.at)
        )
    )
    return int(total or 0)
