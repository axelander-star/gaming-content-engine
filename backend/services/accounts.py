"""Account overview (A2): every channel with status, reach, revenue and a recommendation.

Built for many accounts (100+): all figures come from a handful of grouped
queries, never one query per channel.

Figures per channel
-------------------
* reach: posts, views, interactions and new followers of posts published in the
  last 30 days and in the 30 days before (latest measurement per post);
* revenue: entries of the operator (YouTube payout, affiliate, sponsors, ...) plus
  an *estimate* for submitted Content Rewards clips (views x CPM, capped per clip)
  until the real payout is entered;
* recommendation: whether the channel is new, growing, stable, declining, idle,
  or whether pausing it is worth considering.

"Pause" is only ever a suggestion. It needs ``ACCOUNT_REVIEW_DAYS`` (default 90,
decision of the operator 16.11.2026) since the first post, at least three posts
in that time, no revenue and clearly fewer views per post than the other
channels of the same topic area (or than ``ACCOUNT_MIN_VIEWS_PER_POST`` if there
is nothing to compare with). The operator decides.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import (
    ChannelAuthStatus,
    PlatformCode,
    RevenueSource,
    SubmissionStatus,
)
from models.analytics import Metric
from models.campaigns import Campaign, CampaignSubmission
from models.channels import Channel, Platform
from models.projects import ContentProject
from models.publishing import Post
from models.revenue import RevenueEntry

USD_TO_EUR = Decimal(
    "0.92"
)  # rough conversion for estimates only; real payouts are entered in euro
_CENT = Decimal("0.01")

STATUS_LABELS = {
    "setup": "Noch verbinden",
    "paused": "Pausiert",
    "new": "Anlaufphase",
    "growing": "Wächst",
    "stable": "Stabil",
    "declining": "Lässt nach",
    "idle": "Keine Beiträge",
    "pause_suggested": "Pausieren erwägen",
}


@dataclass
class Window:
    posts: int = 0
    views: int = 0
    interactions: int = 0
    followers: int = 0


@dataclass
class Account:
    channel_id: int
    name: str
    platform: PlatformCode
    language: str
    project_id: int
    project: str
    auth_status: ChannelAuthStatus
    is_paused: bool
    handle: str | None
    first_post_at: datetime | None
    last_post_at: datetime | None
    total_posts: int
    current: Window
    previous: Window
    review: Window
    revenue_30d: Decimal
    revenue_review: Decimal
    revenue_by_source: dict[str, Decimal]
    estimate_30d: Decimal
    status: str = "new"
    reasons: list[str] = field(default_factory=list)

    @property
    def views_per_post(self) -> float | None:
        return self.review.views / self.review.posts if self.review.posts else None

    @property
    def engagement(self) -> float | None:
        return self.current.interactions / self.current.views if self.current.views else None

    @property
    def trend(self) -> float | None:
        if not self.previous.views:
            return None
        return (self.current.views - self.previous.views) / self.previous.views

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "name": self.name,
            "platform": self.platform,
            "language": self.language,
            "project_id": self.project_id,
            "project": self.project,
            "auth_status": self.auth_status,
            "is_paused": self.is_paused,
            "handle": self.handle,
            "first_post_at": self.first_post_at,
            "last_post_at": self.last_post_at,
            "total_posts": self.total_posts,
            "posts_30d": self.current.posts,
            "views_30d": self.current.views,
            "views_prev_30d": self.previous.views,
            "followers_30d": self.current.followers,
            "engagement_30d": self.engagement,
            "trend_30d": self.trend,
            "views_per_post": self.views_per_post,
            "revenue_30d": self.revenue_30d,
            "revenue_review": self.revenue_review,
            "revenue_by_source": self.revenue_by_source,
            "estimate_30d": self.estimate_30d,
            "status": self.status,
            "status_label": STATUS_LABELS[self.status],
            "reasons": self.reasons,
        }


def _latest_metrics() -> Any:
    """Subquery: the newest measurement of every post."""
    ranked = select(
        Metric.post_id,
        Metric.views,
        Metric.likes,
        Metric.comments,
        Metric.shares,
        Metric.saves,
        Metric.followers_gained,
        func.row_number()
        .over(partition_by=Metric.post_id, order_by=(Metric.measured_at.desc(), Metric.id.desc()))
        .label("rn"),
    ).subquery()
    return select(ranked).where(ranked.c.rn == 1).subquery()


def _windows(session: Session, start: datetime, end: datetime) -> dict[int, Window]:
    m = _latest_metrics()
    inter = (
        func.coalesce(m.c.likes, 0)
        + func.coalesce(m.c.comments, 0)
        + func.coalesce(m.c.shares, 0)
        + func.coalesce(m.c.saves, 0)
    )
    rows = session.execute(
        select(
            Post.channel_id,
            func.count(Post.id),
            func.coalesce(func.sum(m.c.views), 0),
            func.coalesce(func.sum(inter), 0),
            func.coalesce(func.sum(m.c.followers_gained), 0),
        )
        .select_from(Post)
        .outerjoin(m, m.c.post_id == Post.id)
        .where(Post.published_at >= start, Post.published_at < end)
        .group_by(Post.channel_id)
    ).all()
    return {int(cid): Window(int(n), int(views), int(i), int(f)) for cid, n, views, i, f in rows}


def _revenue(session: Session, since: datetime) -> dict[int, dict[str, Decimal]]:
    rows = session.execute(
        select(RevenueEntry.channel_id, RevenueEntry.source, func.sum(RevenueEntry.amount_eur))
        .where(RevenueEntry.period_end >= since.date())
        .group_by(RevenueEntry.channel_id, RevenueEntry.source)
    ).all()
    out: dict[int, dict[str, Decimal]] = defaultdict(dict)
    for cid, source, amount in rows:
        out[int(cid)][RevenueSource(source).value] = Decimal(amount or 0)
    return out


def _campaign_estimates(session: Session, since: datetime) -> dict[int, Decimal]:
    """Content Rewards: views x CPM of submitted clips, capped per clip (euro, rounded)."""
    m = _latest_metrics()
    rows = session.execute(
        select(
            CampaignSubmission.channel_id,
            m.c.views,
            Campaign.cpm_usd,
            Campaign.max_payout_per_clip_usd,
            Campaign.min_views,
        )
        .join(Campaign, Campaign.id == CampaignSubmission.campaign_id)
        .outerjoin(m, m.c.post_id == CampaignSubmission.post_id)
        .where(
            CampaignSubmission.status == SubmissionStatus.SUBMITTED,
            CampaignSubmission.posted_at >= since,
        )
    ).all()
    out: dict[int, Decimal] = defaultdict(Decimal)
    for cid, views, cpm, cap, min_views in rows:
        if not views or cpm is None or (min_views and views < min_views):
            continue
        usd = Decimal(views) / 1000 * Decimal(cpm)
        if cap is not None:
            usd = min(usd, Decimal(cap))
        out[int(cid)] += (usd * USD_TO_EUR).quantize(_CENT)
    return out


def _post_span(session: Session) -> dict[int, tuple[datetime | None, datetime | None, int]]:
    rows = session.execute(
        select(
            Post.channel_id,
            func.min(Post.published_at),
            func.max(Post.published_at),
            func.count(Post.id),
        )
        .where(Post.published_at.is_not(None))
        .group_by(Post.channel_id)
    ).all()
    return {int(cid): (first, last, int(n)) for cid, first, last, n in rows}


_CONNECTED = (ChannelAuthStatus.AUTHORIZED, ChannelAuthStatus.CONNECTED_RESTRICTED)


def assess(acc: Account, project_median: float | None, settings: Settings, now: datetime) -> None:
    """Set ``status`` and German ``reasons`` of one account."""
    days = settings.account_review_days
    if acc.auth_status not in _CONNECTED:
        acc.status = "setup"
        acc.reasons.append("Der Kanal ist noch nicht mit der Plattform verbunden.")
        return
    if acc.is_paused:
        acc.status = "paused"
        return
    if acc.first_post_at is None:
        acc.status = "new"
        acc.reasons.append("Noch kein Beitrag veröffentlicht.")
        return
    age = (now - acc.first_post_at).days
    if age < days:
        acc.status = "new"
        acc.reasons.append(f"Erster Beitrag vor {age} Tagen, bewertet wird ab {days} Tagen.")
        return
    if acc.review.posts == 0:
        acc.status = "idle"
        acc.reasons.append(f"In den letzten {days} Tagen kein Beitrag.")
        return
    vpp = acc.views_per_post or 0.0
    if project_median:
        limit = project_median * settings.account_weak_share
        weak = vpp < limit
        compare = (
            f"{round(vpp)} Aufrufe je Beitrag, im Themenbereich üblich sind {round(project_median)}"
        )
    else:
        limit = float(settings.account_min_views_per_post)
        weak = vpp < limit
        compare = f"{round(vpp)} Aufrufe je Beitrag, Untergrenze {round(limit)}"
    if acc.review.posts >= 3 and acc.revenue_review == 0 and weak:
        acc.status = "pause_suggested"
        acc.reasons.append(f"Seit {days} Tagen ohne Einnahmen und schwach: {compare}.")
        acc.reasons.append("Vorschlag: pausieren und die Produktion auf stärkere Kanäle lenken.")
        return
    trend = acc.trend
    if trend is not None and trend >= 0.2:
        acc.status = "growing"
        acc.reasons.append(f"Aufrufe +{round(trend * 100)} % gegenüber den 30 Tagen davor.")
    elif trend is not None and trend <= -0.3:
        acc.status = "declining"
        acc.reasons.append(f"Aufrufe {round(trend * 100)} % gegenüber den 30 Tagen davor.")
    else:
        acc.status = "stable"
    if acc.revenue_review > 0:
        acc.reasons.append(f"{acc.revenue_review:.2f} € Einnahmen in {days} Tagen.")


def overview(session: Session, settings: Settings, now: datetime | None = None) -> list[Account]:
    now = now or datetime.now(UTC)
    days = settings.account_review_days
    d30, d60, dreview = (
        now - timedelta(days=30),
        now - timedelta(days=60),
        now - timedelta(days=days),
    )
    current = _windows(session, d30, now)
    previous = _windows(session, d60, d30)
    review = _windows(session, dreview, now)
    rev30 = _revenue(session, d30)
    rev_review = _revenue(session, dreview)
    est30 = _campaign_estimates(session, d30)
    spans = _post_span(session)

    rows = session.execute(
        select(Channel, Platform.code, ContentProject.name)
        .join(Platform, Platform.id == Channel.platform_id)
        .join(ContentProject, ContentProject.id == Channel.content_project_id)
        .order_by(ContentProject.name, Platform.code, Channel.language, Channel.name)
    ).all()
    accounts: list[Account] = []
    for ch, code, project in rows:
        first, last, total = spans.get(ch.id, (None, None, 0))
        by_source = rev30.get(ch.id, {})
        accounts.append(
            Account(
                channel_id=ch.id,
                name=ch.name,
                platform=PlatformCode(code),
                language=ch.language.value,
                project_id=ch.content_project_id,
                project=project,
                auth_status=ch.auth_status,
                is_paused=ch.is_paused,
                handle=(ch.strategy or {}).get("handle"),
                first_post_at=first,
                last_post_at=last,
                total_posts=total,
                current=current.get(ch.id, Window()),
                previous=previous.get(ch.id, Window()),
                review=review.get(ch.id, Window()),
                revenue_30d=sum(by_source.values(), Decimal(0)),
                revenue_review=sum(rev_review.get(ch.id, {}).values(), Decimal(0)),
                revenue_by_source=by_source,
                estimate_30d=est30.get(ch.id, Decimal(0)),
            )
        )
    medians: dict[int, float | None] = {}
    per_project: dict[int, list[float]] = defaultdict(list)
    for a in accounts:
        if a.views_per_post is not None and a.review.posts >= 3:
            per_project[a.project_id].append(a.views_per_post)
    for pid, values in per_project.items():
        # a median needs other channels to compare with
        medians[pid] = statistics.median(values) if len(values) >= 3 else None
    for a in accounts:
        assess(a, medians.get(a.project_id), settings, now)
    return accounts


def summary(accounts: list[Account]) -> dict[str, Any]:
    by_status: dict[str, int] = defaultdict(int)
    projects: dict[int, dict[str, Any]] = {}
    for a in accounts:
        by_status[a.status] += 1
        p = projects.setdefault(
            a.project_id,
            {
                "project_id": a.project_id,
                "project": a.project,
                "channels": 0,
                "views_30d": 0,
                "revenue_30d": Decimal(0),
                "estimate_30d": Decimal(0),
            },
        )
        p["channels"] += 1
        p["views_30d"] += a.current.views
        p["revenue_30d"] += a.revenue_30d
        p["estimate_30d"] += a.estimate_30d
    return {
        "channels": len(accounts),
        "connected": sum(1 for a in accounts if a.auth_status in _CONNECTED),
        "views_30d": sum(a.current.views for a in accounts),
        "views_prev_30d": sum(a.previous.views for a in accounts),
        "followers_30d": sum(a.current.followers for a in accounts),
        "revenue_30d": sum((a.revenue_30d for a in accounts), Decimal(0)),
        "estimate_30d": sum((a.estimate_30d for a in accounts), Decimal(0)),
        "by_status": dict(by_status),
        "projects": sorted(projects.values(), key=lambda p: (-p["revenue_30d"], p["project"])),
        "top_revenue": [
            a.channel_id
            for a in sorted(accounts, key=lambda a: a.revenue_30d + a.estimate_30d, reverse=True)
            if a.revenue_30d + a.estimate_30d > 0
        ][:5],
    }
