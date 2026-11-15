"""Publishing jobs and resulting posts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.enums import PublishingJobStatus, PublishingMode
from database.base import Base, IdMixin, TimestampMixin, str_enum
from models.production import Variant


class PublishingJob(IdMixin, TimestampMixin, Base):
    """One planned publication of a variant on a channel.

    ``idempotency_key`` is unique so a retried job can never create a second post.
    """

    __tablename__ = "publishing_jobs"
    __table_args__ = (
        # Variant and channel must belong to the job's content project.
        ForeignKeyConstraint(
            ["variant_id", "content_project_id"],
            ["variants.id", "variants.content_project_id"],
            name="fk_publishing_jobs_variant_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["channel_id", "content_project_id"],
            ["channels.id", "channels.content_project_id"],
            name="fk_publishing_jobs_channel_project",
            ondelete="RESTRICT",
        ),
    )

    variant_id: Mapped[int] = mapped_column(
        ForeignKey("variants.id", ondelete="RESTRICT"), index=True
    )
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="RESTRICT"), index=True
    )
    content_project_id: Mapped[int] = mapped_column(
        ForeignKey("content_projects.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[PublishingJobStatus] = mapped_column(
        str_enum(PublishingJobStatus, "publishing_job_status"),
        default=PublishingJobStatus.PENDING,
        index=True,
    )
    mode: Mapped[PublishingMode] = mapped_column(
        str_enum(PublishingMode, "publishing_mode"), default=PublishingMode.MOCK
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    decided_by_decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_decisions.id", ondelete="SET NULL")
    )

    variant: Mapped[Variant] = relationship(foreign_keys=[variant_id])


class Post(IdMixin, TimestampMixin, Base):
    """A publication that exists (or, in mock mode, would exist) on a platform."""

    __tablename__ = "posts"
    __table_args__ = (
        # Protection against duplicate publications (PROJECT_SPEC section 15).
        UniqueConstraint("variant_id", "channel_id", name="uq_posts_variant_channel"),
        ForeignKeyConstraint(
            ["variant_id", "content_project_id"],
            ["variants.id", "variants.content_project_id"],
            name="fk_posts_variant_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["channel_id", "content_project_id"],
            ["channels.id", "channels.content_project_id"],
            name="fk_posts_channel_project",
            ondelete="RESTRICT",
        ),
    )

    publishing_job_id: Mapped[int] = mapped_column(
        ForeignKey("publishing_jobs.id", ondelete="RESTRICT"), unique=True
    )
    variant_id: Mapped[int] = mapped_column(ForeignKey("variants.id", ondelete="RESTRICT"))
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="RESTRICT"), index=True
    )
    content_project_id: Mapped[int] = mapped_column(
        ForeignKey("content_projects.id", ondelete="RESTRICT"), index=True
    )
    external_post_id: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(1000))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    publishing_job: Mapped[PublishingJob] = relationship()


class StrategyVersion(IdMixin, Base):
    """Publishing strategy of one channel; every change is a new version (rollback).

    ``posts_per_day`` is the amount the Publishing Strategy Agent decided for the
    channel; it always lies within the channel's safety bounds.
    """

    __tablename__ = "strategy_versions"
    __table_args__ = (
        UniqueConstraint("channel_id", "version", name="uq_strategy_versions_channel_version"),
    )

    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    #: Local calendar day (channel time zone) the decision was made for.
    planned_for: Mapped[date] = mapped_column(Date)
    posts_per_day: Mapped[int] = mapped_column(Integer)
    #: Posting window, preferred hours, format weights and other plan parameters.
    params: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    reasons: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    #: Measured inputs (baselines, recent performance, quality, supply).
    inputs: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    created_by: Mapped[str] = mapped_column(String(64))  # agent name or user:<id>
    rolled_back_to: Mapped[int | None] = mapped_column(Integer)
