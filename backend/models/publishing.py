"""Publishing jobs and resulting posts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.enums import PublishingJobStatus, PublishingMode
from database.base import Base, IdMixin, TimestampMixin, str_enum
from models.production import Variant


class PublishingJob(IdMixin, TimestampMixin, Base):
    """One planned publication of a variant on a channel.

    ``idempotency_key`` is unique so a retried job can never create a second post.
    """

    __tablename__ = "publishing_jobs"

    variant_id: Mapped[int] = mapped_column(
        ForeignKey("variants.id", ondelete="RESTRICT"), index=True
    )
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="RESTRICT"), index=True
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

    variant: Mapped[Variant] = relationship()


class Post(IdMixin, TimestampMixin, Base):
    """A publication that exists (or, in mock mode, would exist) on a platform."""

    __tablename__ = "posts"
    __table_args__ = (
        # Protection against duplicate publications (PROJECT_SPEC section 15).
        UniqueConstraint("variant_id", "channel_id", name="uq_posts_variant_channel"),
    )

    publishing_job_id: Mapped[int] = mapped_column(
        ForeignKey("publishing_jobs.id", ondelete="RESTRICT"), unique=True
    )
    variant_id: Mapped[int] = mapped_column(ForeignKey("variants.id", ondelete="RESTRICT"))
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="RESTRICT"), index=True
    )
    external_post_id: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(1000))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    publishing_job: Mapped[PublishingJob] = relationship()
