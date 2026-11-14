"""Agent 16: Analytics (PROJECT_SPEC sections 3, 6 and 12, Phase 14).

A sweep over all posts of the last days:

* measures each post at its windows (1 h, 6 h, 24 h, 48 h, 7 days) through
  :mod:`services.metrics` and stores a ``metrics`` row per window,
* moves the variant ``PUBLISHED`` → ``ANALYTICS_PENDING`` → ``ANALYZED`` (after
  the 7-day window),
* once per channel and day writes a report (``analytics_snapshots``) with the
  channel's development and its strong and weak videos, judged against the
  channel's own average at the same age (:func:`services.strategy.assess`).

Test posts get synthetic numbers and are never mixed with real ones.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from agents.base import Agent, AgentContext, AgentResult
from core.enums import ChannelAuthStatus, MetricWindow, NotificationLevel, VideoStatus
from models.access import Notification
from models.analytics import AnalyticsSnapshot, Metric
from models.channels import Channel
from models.production import Variant
from models.publishing import Post
from services import metrics, platform, strategy, workflow

ACTOR = "analytics"
STRONG = 1.5  # at least this much above the channel average = strong video
WEAK = 0.6  # at most this = weak video
REPORT_SCOPE = "channel_daily"


class AnalyticsAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        s, settings = ctx.session, ctx.settings
        now = datetime.now(UTC)
        horizon = now - metrics.LAST_WINDOW - metrics.tolerance(metrics.LAST_WINDOW)
        posts = s.scalars(
            select(Post)
            .where(Post.published_at.is_not(None), Post.published_at >= horizon)
            .order_by(Post.published_at)
            .limit(settings.analytics_batch_size)
        ).all()
        measured = 0
        problems: dict[int, str] = {}
        blocked_channels: set[int] = set()
        for post in posts:
            if post.channel_id in blocked_channels:
                continue
            done = set(s.scalars(select(Metric.measure_window).where(Metric.post_id == post.id)))
            assert post.published_at is not None
            window = metrics.due_window(post.published_at, done, now)
            if window is None:
                continue
            channel = s.get(Channel, post.channel_id)
            variant = s.get(Variant, post.variant_id)
            assert channel is not None and variant is not None
            try:
                snap = metrics.fetch(s, settings, channel, post, window, variant.quality_score)
            except platform.AuthExpiredError as exc:
                blocked_channels.add(channel.id)
                problems[post.id] = str(exc)
                if channel.auth_status == ChannelAuthStatus.AUTHORIZED:
                    channel.auth_status = ChannelAuthStatus.EXPIRED
                    s.add(
                        Notification(
                            level=NotificationLevel.WARNING,
                            title=f"{channel.name}: Verbindung abgelaufen",
                            body=f"Statistiken nicht abrufbar: {exc}"[:2000],
                        )
                    )
                continue
            except (platform.PlatformError, platform.NotConfiguredError) as exc:
                problems[post.id] = str(exc)[:300]
                continue
            if snap.empty():
                problems[post.id] = str(snap.raw.get("unavailable") or "keine Zahlen geliefert")
                continue
            s.add(self._metric(post, window, snap, now))
            measured += 1
            self._advance(s, variant, window)
        s.flush()
        reports = self._reports(ctx, now)
        info = {
            "posts_checked": len(posts),
            "measured": measured,
            "reports": reports,
            "problems": {str(k): v for k, v in list(problems.items())[:20]},
        }
        if measured or reports or problems:
            ctx.decide(
                "measured",
                info,
                f"{measured} Messungen gespeichert, {len(reports)} Tagesberichte, "
                f"{len(problems)} Posts ohne Zahlen.",
            )
        return AgentResult(output=info)

    @staticmethod
    def _metric(post: Post, window: MetricWindow, snap: metrics.Snapshot, now: datetime) -> Metric:
        return Metric(
            post_id=post.id,
            measure_window=window,
            measured_at=now,
            views=snap.views,
            likes=snap.likes,
            comments=snap.comments,
            shares=snap.shares,
            saves=snap.saves,
            watch_time_s=snap.watch_time_s,
            avg_view_duration_s=snap.avg_view_duration_s,
            retention_pct=snap.retention_pct,
            followers_gained=snap.followers_gained,
            raw=snap.raw,
        )

    @staticmethod
    def _advance(s: Any, variant: Variant, window: MetricWindow) -> None:
        if variant.status == VideoStatus.PUBLISHED:
            workflow.transition(s, variant, VideoStatus.ANALYTICS_PENDING, actor=ACTOR)
        if window == MetricWindow.D7 and variant.status == VideoStatus.ANALYTICS_PENDING:
            workflow.transition(s, variant, VideoStatus.ANALYZED, actor=ACTOR)

    def _reports(self, ctx: AgentContext, now: datetime) -> list[int]:
        """One report per channel and day (UTC) for channels with posts."""
        s = ctx.session
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        done = set(
            s.scalars(
                select(AnalyticsSnapshot.channel_id).where(
                    AnalyticsSnapshot.scope == REPORT_SCOPE, AnalyticsSnapshot.period_end >= day
                )
            )
        )
        channel_ids = s.scalars(select(Post.channel_id).distinct()).all()
        created = []
        for channel_id in channel_ids:
            if channel_id in done:
                continue
            include_mock = ctx.settings.publishing_mode != "live"
            posts = strategy.load_history(s, channel_id, include_mock=include_mock)
            if not posts:
                continue
            s.add(
                AnalyticsSnapshot(
                    channel_id=channel_id,
                    scope=REPORT_SCOPE,
                    period_start=day - timedelta(days=30),
                    period_end=now,
                    data=channel_report(posts),
                )
            )
            created.append(channel_id)
        return created


def channel_report(posts: list[strategy.PostPerf]) -> dict[str, Any]:
    """Development of a channel: judged posts, strong and weak videos, trend."""
    assessment = strategy.assess(posts)
    by_id = {p.post_id: p for p in posts}
    judged = sorted(assessment.judged, key=lambda j: j.score, reverse=True)

    def row(j: strategy.Judged) -> dict[str, Any]:
        p = by_id[j.post_id]
        return {
            "post_id": j.post_id,
            "score": round(j.score, 2),
            "window": j.window.value,
            "game": p.game,
            "format": p.video_format,
            "hook": p.hook_type,
        }

    return {
        "posts": len(posts),
        "judged": len(judged),
        "waiting": assessment.waiting,
        "recent_median": assessment.recent_median,
        "strong": [row(j) for j in judged if j.score >= STRONG][:5],
        "weak": [row(j) for j in reversed(judged) if j.score <= WEAK][:5],
        "groups": strategy.group_scores(posts, assessment),
    }
