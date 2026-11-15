"""Research feeds, collected items and the idea lab (extension phase E5).

Everything here belongs to exactly one content project. Items are foreign text:
they are shown and passed to the AI as data, never as instructions.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import IdeaStatus
from database.base import Base, IdMixin, TimestampMixin, str_enum


class ResearchSource(IdMixin, TimestampMixin, Base):
    """An RSS or Atom feed a topic area watches."""

    __tablename__ = "research_sources"
    __table_args__ = (
        UniqueConstraint("content_project_id", "url", name="uq_research_sources_project_url"),
    )

    content_project_id: Mapped[int] = mapped_column(
        ForeignKey("content_projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(1000))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: ``ok``, ``error`` or ``mock`` after the last fetch.
    last_status: Mapped[str | None] = mapped_column(String(16))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_item_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class ResearchItem(IdMixin, Base):
    """One entry from a feed (title, link, short summary)."""

    __tablename__ = "research_items"
    __table_args__ = (
        UniqueConstraint("content_project_id", "guid_hash", name="uq_research_items_project_guid"),
    )

    content_project_id: Mapped[int] = mapped_column(
        ForeignKey("content_projects.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_sources.id", ondelete="SET NULL"), index=True
    )
    #: sha256 of the feed's guid or link, for de-duplication.
    guid_hash: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str | None] = mapped_column(String(1000))
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    #: Set once an idea was drafted from this item.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Idea(IdMixin, TimestampMixin, Base):
    """A video idea with sources, scores and the reasoning behind them."""

    __tablename__ = "ideas"

    content_project_id: Mapped[int] = mapped_column(
        ForeignKey("content_projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    pitch: Mapped[str] = mapped_column(Text)
    #: ``short`` (Shorts/Reels), ``explainer`` or ``long``.
    format: Mapped[str] = mapped_column(String(16))
    #: [{"title", "url", "item_id"}] – where the idea comes from.
    sources: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    trend_score: Mapped[int] = mapped_column(Integer)
    fit_score: Mapped[int] = mapped_column(Integer)
    effort_score: Mapped[int] = mapped_column(Integer)
    rights_risk: Mapped[int] = mapped_column(Integer)
    score: Mapped[int] = mapped_column(Integer, index=True)
    reasoning: Mapped[str] = mapped_column(Text)
    status: Mapped[IdeaStatus] = mapped_column(
        str_enum(IdeaStatus, "idea_status"),
        default=IdeaStatus.NEW,
        server_default=IdeaStatus.NEW.value,
        index=True,
    )
    #: ``mock`` or ``claude``.
    provider: Mapped[str] = mapped_column(String(32))
    ai_call_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ai_calls.id", ondelete="SET NULL")
    )
    agent_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    planned_for: Mapped[date | None] = mapped_column(Date)
