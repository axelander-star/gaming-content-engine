"""Media library and own production (extension phase E7).

The library holds own uploads (rights confirmed per file) and videos the own
production generated. The original file is never changed; the 9:16 rendition
and the preview image are stored next to it. Everything belongs to exactly one
content project.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import Language, LibraryKind, LibraryOrigin, LibraryStatus, ProductionStatus
from database.base import Base, IdMixin, TimestampMixin, str_enum


class LibraryItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "library_items"
    __table_args__ = (
        UniqueConstraint(
            "content_project_id", "original_sha256", name="uq_library_items_project_sha"
        ),
    )

    content_project_id: Mapped[int] = mapped_column(
        ForeignKey("content_projects.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[LibraryKind] = mapped_column(str_enum(LibraryKind, "library_kind"))
    origin: Mapped[LibraryOrigin] = mapped_column(str_enum(LibraryOrigin, "library_origin"))
    status: Mapped[LibraryStatus] = mapped_column(
        str_enum(LibraryStatus, "library_status"),
        default=LibraryStatus.PROCESSING,
        server_default=LibraryStatus.PROCESSING.value,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    #: The file as uploaded or generated; never modified.
    original_uri: Mapped[str] = mapped_column(String(1000))
    original_sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    duration_s: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    video_codec: Mapped[str | None] = mapped_column(String(32))
    audio_codec: Mapped[str | None] = mapped_column(String(32))
    #: ``portrait``, ``landscape`` or ``square`` (videos and images).
    orientation: Mapped[str | None] = mapped_column(String(16))
    #: 9:16 version (video: MP4 1080×1920 or 720×1280, image: JPEG).
    rendition_uri: Mapped[str | None] = mapped_column(String(1000))
    #: layout, size, render seconds, real-time factor or why there is none.
    rendition: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    thumb_uri: Mapped[str | None] = mapped_column(String(1000))
    render_seconds: Mapped[float | None] = mapped_column(Float)
    #: Upload: confirmation text, who and when. Generated: production, voice, images.
    rights: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    tags: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    note: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    #: Uploaded video originals are removed after ``LIBRARY_ORIGINAL_RETENTION_DAYS``
    #: (operator decision 16.11.2026); the 9:16 version stays for posts.
    original_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: A6: a short cut out of a long video points to that video.
    parent_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("library_items.id", ondelete="SET NULL"), index=True
    )
    #: A6: splitting a long video into shorts: ``queued``, ``running``, ``done``, ``failed``.
    split_state: Mapped[str | None] = mapped_column(String(16), index=True)
    #: Wanted count and length, result (new items) or error of the last split.
    split_info: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")


class OwnProduction(IdMixin, TimestampMixin, Base):
    """A video made without third-party footage: script, voice, picture/text, subtitles."""

    __tablename__ = "own_productions"

    content_project_id: Mapped[int] = mapped_column(
        ForeignKey("content_projects.id", ondelete="RESTRICT"), index=True
    )
    idea_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ideas.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    language: Mapped[Language] = mapped_column(str_enum(Language, "language"))
    status: Mapped[ProductionStatus] = mapped_column(
        str_enum(ProductionStatus, "production_status"),
        default=ProductionStatus.DRAFT,
        server_default=ProductionStatus.DRAFT.value,
        index=True,
    )
    #: [{"headline", "text", "image_item_id"}] – one picture with on-screen text each.
    segments: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    #: ``mock``, ``claude`` or ``manual``.
    script_source: Mapped[str] = mapped_column(String(32))
    ai_call_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ai_calls.id", ondelete="SET NULL")
    )
    voice_provider: Mapped[str | None] = mapped_column(String(64))
    duration_s: Mapped[float | None] = mapped_column(Float)
    render_seconds: Mapped[float | None] = mapped_column(Float)
    #: Timeline, subtitle files and findings of the last render.
    result: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    output_item_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("library_items.id", ondelete="SET NULL")
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    rendered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
