"""Trend alarm (Ausbau A11): a fast-rising topic with drafts ready to approve."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, IdMixin, TimestampMixin


class TrendAlarm(IdMixin, TimestampMixin, Base):
    __tablename__ = "trend_alarms"

    content_project_id: Mapped[int] = mapped_column(
        ForeignKey("content_projects.id", ondelete="CASCADE"), index=True
    )
    #: One alarm per signal, e.g. ``yt:VIDEO_ID`` (the same video never alarms twice).
    signal_key: Mapped[str] = mapped_column(String(120), unique=True)
    #: ``youtube_chart`` (YouTube trending list) or ``competitor`` (competitor radar).
    source: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(500))
    creator: Mapped[str | None] = mapped_column(String(200))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: views, views_per_hour, likes, comments, outlier, campaign, region …
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    score: Mapped[int] = mapped_column(Integer)
    #: Plain-language facts for the push and the dashboard.
    facts: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    #: drafting, ready, approved, dismissed, expired, failed
    status: Mapped[str] = mapped_column(String(16), default="drafting", index=True)
    #: [{"angle": "...", "production_id": 1}]
    drafts: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    approved_production_id: Mapped[int | None] = mapped_column(BigInteger)
    #: Approved by the autopilot (no person) for at least one channel.
    autopilot: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    error: Mapped[str | None] = mapped_column(Text)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
