"""Games and detected trends."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import Language
from database.base import Base, IdMixin, TimestampMixin, str_enum


class Game(IdMixin, TimestampMixin, Base):
    __tablename__ = "games"

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    categories: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    publisher: Mapped[str | None] = mapped_column(String(200))
    steam_app_id: Mapped[int | None]
    twitch_game_id: Mapped[str | None] = mapped_column(String(64))
    # Publisher policy for commercial use; never assumed to be permissive.
    publisher_policy_notes: Mapped[str | None] = mapped_column(Text)
    publisher_policy_url: Mapped[str | None] = mapped_column(String(500))
    # Game Intelligence (Phase 5): audience, modes, video ideas, own performance.
    profile: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    profiled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Trend(IdMixin, TimestampMixin, Base):
    __tablename__ = "trends"

    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(64))  # youtube | twitch | steam | internal ...
    language: Mapped[Language | None] = mapped_column(str_enum(Language, "language"))
    score: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audience: Mapped[str | None] = mapped_column(String(64))
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class TrendReport(IdMixin, Base):
    """Trend report of one research run for one language (Trend Research agent)."""

    __tablename__ = "trend_reports"

    language: Mapped[Language] = mapped_column(str_enum(Language, "language"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    agent_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    sources: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    summary: Mapped[str] = mapped_column(Text)
    items: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    by_audience: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
