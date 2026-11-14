"""Creators, sources, licenses and assets (rights evidence chain)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
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

from core.enums import AssetKind, LicenseStatus, PolicyStatus, SourceType
from database.base import Base, IdMixin, TimestampMixin, str_enum


class Creator(IdMixin, TimestampMixin, Base):
    __tablename__ = "creators"

    name: Mapped[str] = mapped_column(String(200))
    contact: Mapped[str | None] = mapped_column(String(320))
    notes: Mapped[str | None] = mapped_column(Text)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Source(IdMixin, TimestampMixin, Base):
    __tablename__ = "sources"

    creator_id: Mapped[int | None] = mapped_column(
        ForeignKey("creators.id", ondelete="RESTRICT"), index=True
    )
    type: Mapped[SourceType] = mapped_column(str_enum(SourceType, "source_type"))
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(1000))
    provenance_notes: Mapped[str | None] = mapped_column(Text)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    licenses: Mapped[list[License]] = relationship(back_populates="source")


class License(IdMixin, TimestampMixin, Base):
    """License evidence. Every permission defaults to False (deny by default)."""

    __tablename__ = "licenses"

    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[LicenseStatus] = mapped_column(
        str_enum(LicenseStatus, "license_status"), default=LicenseStatus.PENDING
    )
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    allows_commercial_use: Mapped[bool] = mapped_column(Boolean, default=False)
    allows_editing: Mapped[bool] = mapped_column(Boolean, default=False)
    allows_short_form: Mapped[bool] = mapped_column(Boolean, default=False)
    allows_monetization: Mapped[bool] = mapped_column(Boolean, default=False)
    music_cleared: Mapped[bool] = mapped_column(Boolean, default=False)
    allowed_platforms: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    allowed_languages: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    restrictions: Mapped[str | None] = mapped_column(Text)
    document_uri: Mapped[str | None] = mapped_column(String(1000))
    verified_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Explicit permission of the game's rights holder (needed for "license_required" games).
    publisher_permission: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    expiry_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source: Mapped[Source] = relationship(back_populates="licenses")


class Asset(IdMixin, TimestampMixin, Base):
    """A licensed file (video, music, ...). Always tied to a source *and* a license."""

    __tablename__ = "assets"

    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    license_id: Mapped[int] = mapped_column(
        ForeignKey("licenses.id", ondelete="RESTRICT"), index=True
    )
    game_id: Mapped[int | None] = mapped_column(ForeignKey("games.id", ondelete="SET NULL"))
    kind: Mapped[AssetKind] = mapped_column(str_enum(AssetKind, "asset_kind"))
    title: Mapped[str | None] = mapped_column(String(300))
    storage_uri: Mapped[str] = mapped_column(String(1000))
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    duration_s: Mapped[float | None] = mapped_column(Float)
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")


class PublisherPolicy(IdMixin, TimestampMixin, Base):
    """Curated commercial-use policy of a game publisher (PROJECT_SPEC section 5).

    Never assumed to be permissive: a game without a policy row is treated as
    "not checked" and blocks the rights approval.
    """

    __tablename__ = "publisher_policies"

    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), unique=True)
    status: Mapped[PolicyStatus] = mapped_column(str_enum(PolicyStatus, "policy_status"))
    publisher: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text)
    policy_url: Mapped[str | None] = mapped_column(String(500))
    checked_at: Mapped[date | None] = mapped_column(Date)
    checked_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class LicenseDocument(IdMixin, Base):
    """Uploaded license evidence. Append-only: a new upload is a new version."""

    __tablename__ = "license_documents"
    __table_args__ = (UniqueConstraint("license_id", "version", name="uq_license_doc_version"),)

    license_id: Mapped[int] = mapped_column(
        ForeignKey("licenses.id", ondelete="RESTRICT"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_uri: Mapped[str] = mapped_column(String(1000))
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RightsCheck(IdMixin, Base):
    """Result of one rights check of a gameplay file, with every criterion."""

    __tablename__ = "rights_checks"

    gameplay_file_id: Mapped[int] = mapped_column(
        ForeignKey("gameplay_files.id", ondelete="CASCADE"), index=True
    )
    license_id: Mapped[int | None] = mapped_column(ForeignKey("licenses.id", ondelete="SET NULL"))
    agent_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    approved: Mapped[bool] = mapped_column(Boolean)
    checks: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    missing: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    denied: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
