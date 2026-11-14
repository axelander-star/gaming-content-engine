"""Performance metrics per post and aggregated snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import MetricWindow
from database.base import Base, IdMixin, str_enum


class Metric(IdMixin, Base):
    """Metrics of one post at one measurement window.

    Every value is nullable because platforms expose different metrics; the
    strategy agent only uses values that were actually delivered.
    """

    __tablename__ = "metrics"
    __table_args__ = (Index("ix_metrics_post_window", "post_id", "measure_window"),)

    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    measure_window: Mapped[MetricWindow] = mapped_column(str_enum(MetricWindow, "metric_window"))
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    views: Mapped[int | None] = mapped_column(BigInteger)
    watch_time_s: Mapped[float | None] = mapped_column(Float)
    avg_view_duration_s: Mapped[float | None] = mapped_column(Float)
    retention_pct: Mapped[float | None] = mapped_column(Float)
    completion_rate: Mapped[float | None] = mapped_column(Float)
    replays: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    shares: Mapped[int | None] = mapped_column(BigInteger)
    saves: Mapped[int | None] = mapped_column(BigInteger)
    followers_gained: Mapped[int | None] = mapped_column(BigInteger)
    raw: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")


class AnalyticsSnapshot(IdMixin, Base):
    """Aggregated report (per channel, game, format, ...) for a period."""

    __tablename__ = "analytics_snapshots"

    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(String(64))  # channel | game | format | hook | ...
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    data: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")


class LearningVersion(IdMixin, Base):
    """What the Learning Agent derived from the results; every change is a version.

    ``weights`` holds factors per game, format and hook (1.0 = neutral, bounded to
    0.8–1.2). A new version starts as ``trial`` and is only kept (``active``) if
    the posts chosen with it do not perform worse; otherwise it is
    ``rolled_back`` and the previous version applies again.
    """

    __tablename__ = "learning_versions"

    version: Mapped[int] = mapped_column(Integer, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(
        String(16), index=True
    )  # trial|active|rolled_back|superseded
    weights: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    reasons: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    #: Group statistics the weights are based on, and the baseline for the trial.
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    trial_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evaluation: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    created_by: Mapped[str] = mapped_column(String(64))
    rolled_back_to: Mapped[int | None] = mapped_column(Integer)
