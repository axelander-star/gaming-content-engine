"""Platforms and publishing channels (platform x language)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.enums import ChannelAuthStatus, Language, PlatformCode
from database.base import Base, IdMixin, TimestampMixin, str_enum


class Platform(IdMixin, TimestampMixin, Base):
    __tablename__ = "platforms"

    code: Mapped[PlatformCode] = mapped_column(str_enum(PlatformCode, "platform_code"), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    channels: Mapped[list[Channel]] = relationship(back_populates="platform")


class Channel(IdMixin, TimestampMixin, Base):
    """A publishing target with its own language, strategy and limits.

    ``min_posts_per_day`` / ``max_posts_per_day`` are *safety bounds*, never a
    target. ``max_posts_per_day`` defaults to 0, which blocks publishing until
    the operator configures the channel. The actual amount is decided by the
    Publishing Strategy Agent (PROJECT_SPEC section 3).
    """

    __tablename__ = "channels"
    __table_args__ = (
        UniqueConstraint("platform_id", "language", "name", name="uq_channels_platform_lang_name"),
        CheckConstraint("min_posts_per_day >= 0", name="min_posts_non_negative"),
        CheckConstraint("max_posts_per_day >= min_posts_per_day", name="max_gte_min"),
        CheckConstraint("min_interval_minutes >= 0", name="interval_non_negative"),
    )

    platform_id: Mapped[int] = mapped_column(ForeignKey("platforms.id", ondelete="RESTRICT"))
    language: Mapped[Language] = mapped_column(str_enum(Language, "language"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    external_channel_id: Mapped[str | None] = mapped_column(String(200))
    auth_status: Mapped[ChannelAuthStatus] = mapped_column(
        str_enum(ChannelAuthStatus, "channel_auth_status"),
        default=ChannelAuthStatus.NOT_CONNECTED,
    )
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    min_posts_per_day: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_posts_per_day: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    min_interval_minutes: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    audience_notes: Mapped[str | None] = mapped_column(Text)
    strategy: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")

    platform: Mapped[Platform] = relationship(back_populates="channels")
