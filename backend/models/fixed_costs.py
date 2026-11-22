"""Recurring fixed costs entered by the operator (server, domain, subscriptions, …)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, IdMixin, TimestampMixin

#: Allowed values, checked by the API.
FIXED_COST_CATEGORIES = ("server", "domain", "subscription", "storage", "backup", "other")
FIXED_COST_CURRENCIES = ("EUR", "USD")
FIXED_COST_INTERVALS = ("month", "year")


class FixedCost(IdMixin, TimestampMixin, Base):
    """One recurring cost item, e.g. "Contabo Cloud VPS 8, 13.33 EUR per month".

    ``in_budget`` decides whether the item counts against the engine budget
    (and therefore the brake on paid calls). Personal subscriptions such as a
    Claude Pro plan are shown in the totals but usually stay out of the budget,
    because the engine cannot use them.
    """

    __tablename__ = "fixed_costs"
    __table_args__ = (CheckConstraint("amount >= 0", name="amount_non_negative"),)

    name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str | None] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(16), default="other")
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    interval: Mapped[str] = mapped_column(String(8), default="month")
    in_budget: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    note: Mapped[str | None] = mapped_column(String(300))
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
