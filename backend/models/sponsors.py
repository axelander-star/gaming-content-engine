"""Brand inquiries in the sponsor inbox (Ausbau A9).

The operator pastes or forwards a brand's mail; the engine sorts it, checks for
red flags, suggests a price from the channels' own numbers and writes a reply
draft. Nothing is ever sent: the operator copies the draft into his mail program.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import Language
from database.base import Base, IdMixin, TimestampMixin, str_enum


class SponsorInquiry(IdMixin, TimestampMixin, Base):
    __tablename__ = "sponsor_inquiries"

    content_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("content_projects.id", ondelete="SET NULL"), index=True
    )
    brand: Mapped[str] = mapped_column(String(200))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    subject: Mapped[str | None] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    language: Mapped[Language] = mapped_column(str_enum(Language, "language"))
    #: sponsoring | product_test | affiliate | other | spam
    category: Mapped[str] = mapped_column(String(20), index=True)
    #: new | replied | won | declined | archived
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    #: Warnings: unpaid, upfront fee, gambling, crypto ... (shown before answering)
    flags: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    fit_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    price_eur: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    #: How the price came about (views, CPM, posts) for the dashboard.
    price_basis: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    draft: Mapped[str] = mapped_column(Text, default="")
    draft_source: Mapped[str] = mapped_column(String(32), default="template")
    note: Mapped[str | None] = mapped_column(Text)
