"""Revenue per channel, entered by the operator or imported (account overview, A2)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import RevenueSource
from database.base import Base, IdMixin, TimestampMixin, str_enum


class RevenueEntry(IdMixin, TimestampMixin, Base):
    """Money earned by one channel in a period, in euro.

    Platforms pay with delay and in different currencies; the operator enters
    the amount from the payout report (or an import fills it later). Estimates
    (e.g. Content Rewards before payout) are not stored here but computed.
    """

    __tablename__ = "revenue_entries"
    __table_args__ = (
        CheckConstraint("period_end >= period_start", name="period_order"),
        CheckConstraint("amount_eur >= 0", name="amount_non_negative"),
    )

    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[RevenueSource] = mapped_column(str_enum(RevenueSource, "revenue_source"))
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    note: Mapped[str | None] = mapped_column(String(300))
    is_import: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
