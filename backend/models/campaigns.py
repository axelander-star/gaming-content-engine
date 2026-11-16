"""Clipping campaigns (Content Rewards) and the links the operator submits by hand.

A campaign of a rights holder (streamer, brand) pays per verified view for clips
made from its material. Its brief is the license: each campaign gets its own
:class:`~models.rights.Source` (type ``campaign``) and :class:`~models.rights.License`,
so the rights evaluation, the expiry sweep and the block list work as for every
other source. Clips go only to the channels chosen for the campaign.

There is no official API for clippers, so nothing is submitted automatically: every
published campaign clip becomes a :class:`CampaignSubmission` that the operator
submits on the campaign page within the submission window and then ticks off.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import CampaignStatus, SubmissionStatus
from database.base import Base, IdMixin, TimestampMixin, str_enum


class Campaign(IdMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"

    content_project_id: Mapped[int] = mapped_column(
        ForeignKey("content_projects.id", ondelete="RESTRICT"), index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), unique=True
    )
    license_id: Mapped[int] = mapped_column(ForeignKey("licenses.id", ondelete="RESTRICT"))
    game_id: Mapped[int | None] = mapped_column(ForeignKey("games.id", ondelete="SET NULL"))
    #: Where the campaign comes from, e.g. ``content_rewards``.
    provider: Mapped[str] = mapped_column(String(32), default="content_rewards")
    name: Mapped[str] = mapped_column(String(200))
    #: Campaign page; the operator submits the links there.
    url: Mapped[str] = mapped_column(String(1000))
    status: Mapped[CampaignStatus] = mapped_column(
        str_enum(CampaignStatus, "campaign_status"),
        default=CampaignStatus.ACTIVE,
        server_default=CampaignStatus.ACTIVE.value,
        index=True,
    )
    #: Paid per 1,000 verified views (US dollars, before the platform fee).
    cpm_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    min_views: Mapped[int | None] = mapped_column(Integer)
    max_payout_per_clip_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    #: Platform codes the campaign counts (``youtube``, ``tiktok``, ...).
    platforms: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    #: Languages of the clips the campaign accepts (``de``, ``en``).
    languages: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    #: Channels that are connected to the campaign; clips go only there.
    channel_ids: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    #: Hashtags the brief requires (without ``#``).
    required_hashtags: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    #: Required paid-content disclosure, put at the start of the post text.
    disclosure: Mapped[str | None] = mapped_column(String(300))
    #: Other text the brief requires (credit, @mention, link).
    required_text: Mapped[str | None] = mapped_column(String(500))
    min_duration_s: Mapped[int | None] = mapped_column(Integer)
    max_duration_s: Mapped[int | None] = mapped_column(Integer)
    #: Minutes after posting within which the link must be submitted.
    submission_window_min: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    ends_on: Mapped[date | None] = mapped_column(Date)
    #: The brief as copied from the campaign page (rules, banned content).
    brief: Mapped[str | None] = mapped_column(Text)
    #: Links to the campaign material (streams, folders) from the brief.
    material_links: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )


class CampaignSubmission(IdMixin, TimestampMixin, Base):
    """One published campaign clip whose link the operator submits by hand."""

    __tablename__ = "campaign_submissions"

    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="RESTRICT"), index=True
    )
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="RESTRICT"), unique=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("variants.id", ondelete="RESTRICT"))
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="RESTRICT"))
    #: Public link of the post; empty for drafts (e.g. TikTok inbox) until entered.
    post_url: Mapped[str | None] = mapped_column(String(1000))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Submit before this time (posted_at + window); empty while the link is missing.
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[SubmissionStatus] = mapped_column(
        str_enum(SubmissionStatus, "submission_status"),
        default=SubmissionStatus.OPEN,
        server_default=SubmissionStatus.OPEN.value,
        index=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(String(500))
