"""Competitor radar (Ausbau A5): channels to watch and their videos."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import PlatformCode
from database.base import Base, IdMixin, TimestampMixin, str_enum


class Competitor(IdMixin, TimestampMixin, Base):
    __tablename__ = "competitors"
    __table_args__ = (
        UniqueConstraint("content_project_id", "platform", "handle", name="uq_competitor_handle"),
    )

    content_project_id: Mapped[int] = mapped_column(
        ForeignKey("content_projects.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[PlatformCode] = mapped_column(str_enum(PlatformCode, "platform_code"))
    #: As entered, normalised: ``@name`` (YouTube handle).
    handle: Mapped[str] = mapped_column(String(120))
    external_channel_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(200))
    uploads_playlist_id: Mapped[str | None] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )


class CompetitorVideo(IdMixin, Base):
    __tablename__ = "competitor_videos"
    __table_args__ = (UniqueConstraint("competitor_id", "external_id", name="uq_competitor_video"),)

    competitor_id: Mapped[int] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    views: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    likes: Mapped[int | None] = mapped_column(Integer)
    comments: Mapped[int | None] = mapped_column(Integer)
    #: Views divided by the channel's usual views (median of its recent videos).
    outlier: Mapped[float | None] = mapped_column(Float)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    #: Passed to the idea lab as a research item once it stood out.
    research_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_items.id", ondelete="SET NULL")
    )
