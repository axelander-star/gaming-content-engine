"""Viewer comments and reply drafts (A3)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import CommentKind, CommentStatus, PlatformCode
from database.base import Base, IdMixin, TimestampMixin, str_enum


class Comment(IdMixin, TimestampMixin, Base):
    __tablename__ = "comments"
    __table_args__ = (
        UniqueConstraint("channel_id", "external_id", name="uq_comments_channel_external"),
    )

    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"))
    platform: Mapped[PlatformCode] = mapped_column(str_enum(PlatformCode, "platform_code"))
    #: Id at the platform; for pasted TikTok comments a generated ``manual-...`` id.
    external_id: Mapped[str] = mapped_column(String(200))
    author: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    like_count: Mapped[int | None] = mapped_column(BigInteger)
    written_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kind: Mapped[CommentKind] = mapped_column(
        str_enum(CommentKind, "comment_kind"), default=CommentKind.OTHER
    )
    status: Mapped[CommentStatus] = mapped_column(
        str_enum(CommentStatus, "comment_status"), default=CommentStatus.NEW, index=True
    )
    #: Why the reply waits for the operator (German), if it does.
    review_reason: Mapped[str | None] = mapped_column(String(300))
    reply_text: Mapped[str | None] = mapped_column(Text)
    reply_source: Mapped[str | None] = mapped_column(String(32))
    reply_external_id: Mapped[str | None] = mapped_column(String(200))
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reply_is_mock: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    decided_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
