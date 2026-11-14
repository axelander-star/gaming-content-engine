"""Production chain: gameplay files -> scenes -> clips -> variants (+ scripts, audio, QC)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.enums import Language, MaterialStatus, VideoStatus
from database.base import Base, FailureMixin, IdMixin, TimestampMixin, str_enum


class GameplayFile(IdMixin, TimestampMixin, FailureMixin, Base):
    """Raw gameplay material. Status follows the material workflow."""

    __tablename__ = "gameplay_files"

    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), index=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("games.id", ondelete="SET NULL"))
    status: Mapped[MaterialStatus] = mapped_column(
        str_enum(MaterialStatus, "material_status"), default=MaterialStatus.DISCOVERED, index=True
    )
    storage_uri: Mapped[str] = mapped_column(String(1000))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    duration_s: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    video_codec: Mapped[str | None] = mapped_column(String(32))
    audio_codec: Mapped[str | None] = mapped_column(String(32))

    scenes: Mapped[list[Scene]] = relationship(back_populates="gameplay_file")


class Scene(IdMixin, TimestampMixin, Base):
    __tablename__ = "scenes"
    __table_args__ = (CheckConstraint("end_s > start_s", name="end_after_start"),)

    gameplay_file_id: Mapped[int] = mapped_column(
        ForeignKey("gameplay_files.id", ondelete="CASCADE"), index=True
    )
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    score: Mapped[float | None] = mapped_column(Float)
    tags: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    scores: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")

    gameplay_file: Mapped[GameplayFile] = relationship(back_populates="scenes")


class Clip(IdMixin, TimestampMixin, Base):
    """Language-independent cut of a scene (vertical, no voiceover yet)."""

    __tablename__ = "clips"

    scene_id: Mapped[int] = mapped_column(ForeignKey("scenes.id", ondelete="RESTRICT"), index=True)
    storage_uri: Mapped[str | None] = mapped_column(String(1000))
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    fingerprint: Mapped[str | None] = mapped_column(Text)
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)

    scene: Mapped[Scene] = relationship()


class Variant(IdMixin, TimestampMixin, FailureMixin, Base):
    """A finished video for one channel and language. Follows the video workflow."""

    __tablename__ = "variants"
    __table_args__ = (
        UniqueConstraint(
            "clip_id", "channel_id", "variant_label", name="uq_variants_clip_chan_lbl"
        ),
    )

    clip_id: Mapped[int] = mapped_column(ForeignKey("clips.id", ondelete="RESTRICT"), index=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="RESTRICT"), index=True
    )
    language: Mapped[Language] = mapped_column(str_enum(Language, "language"))
    variant_label: Mapped[str] = mapped_column(String(8))  # A, B, C, D ...
    video_format: Mapped[str | None] = mapped_column(String(64))
    hook_type: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[VideoStatus] = mapped_column(
        str_enum(VideoStatus, "video_status"), default=VideoStatus.SCENE_SELECTED, index=True
    )
    storage_uri: Mapped[str | None] = mapped_column(String(1000))
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    fingerprint: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    quality_score: Mapped[float | None] = mapped_column(Float)

    clip: Mapped[Clip] = relationship()


class Script(IdMixin, TimestampMixin, Base):
    __tablename__ = "scripts"

    variant_id: Mapped[int] = mapped_column(
        ForeignKey("variants.id", ondelete="CASCADE"), index=True
    )
    language: Mapped[Language] = mapped_column(str_enum(Language, "language"))
    hook: Mapped[str | None] = mapped_column(Text)
    voiceover_text: Mapped[str | None] = mapped_column(Text)
    call_to_action: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class Voiceover(IdMixin, TimestampMixin, Base):
    __tablename__ = "voiceovers"

    variant_id: Mapped[int] = mapped_column(
        ForeignKey("variants.id", ondelete="CASCADE"), index=True
    )
    script_id: Mapped[int | None] = mapped_column(ForeignKey("scripts.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(64))
    voice_id: Mapped[str | None] = mapped_column(String(128))
    storage_uri: Mapped[str | None] = mapped_column(String(1000))
    duration_s: Mapped[float | None] = mapped_column(Float)
    commercial_use_cleared: Mapped[bool] = mapped_column(Boolean, default=False)


class Subtitle(IdMixin, TimestampMixin, Base):
    __tablename__ = "subtitles"

    variant_id: Mapped[int] = mapped_column(
        ForeignKey("variants.id", ondelete="CASCADE"), index=True
    )
    language: Mapped[Language] = mapped_column(str_enum(Language, "language"))
    format: Mapped[str] = mapped_column(String(8))  # srt | vtt
    storage_uri: Mapped[str | None] = mapped_column(String(1000))
    burned_in: Mapped[bool] = mapped_column(Boolean, default=False)


class QualityCheck(IdMixin, Base):
    __tablename__ = "quality_checks"

    variant_id: Mapped[int] = mapped_column(
        ForeignKey("variants.id", ondelete="CASCADE"), index=True
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    passed: Mapped[bool] = mapped_column(Boolean)
    score: Mapped[float | None] = mapped_column(Float)
    checks: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    reasons: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
