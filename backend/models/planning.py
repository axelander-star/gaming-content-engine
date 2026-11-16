"""Editorial planning (extension phase E4, calendar view in E6).

The plan says *which topic area is on which day* and which topic gets the focus.
How many posts a channel gets stays with the Publishing Strategy Agent.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, IdMixin, TimestampMixin


class EditorialDay(IdMixin, TimestampMixin, Base):
    """A topic area is planned for a day."""

    __tablename__ = "editorial_days"
    __table_args__ = (
        UniqueConstraint("day", "content_project_id", name="uq_editorial_days_day_project"),
    )

    day: Mapped[date] = mapped_column(Date, index=True)
    content_project_id: Mapped[int] = mapped_column(
        ForeignKey("content_projects.id", ondelete="CASCADE"), index=True
    )
    note: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    #: Set when a weekly rule put the entry here (Ausbau A5). Such entries add the
    #: area to the day without making the day exclusive.
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("plan_rules.id", ondelete="SET NULL"), index=True
    )


class PlanRule(IdMixin, TimestampMixin, Base):
    """A recurring plan entry, e.g. "every Thursday Uhren" (Ausbau A5)."""

    __tablename__ = "plan_rules"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("every_weeks BETWEEN 1 AND 4", name="every_weeks_range"),
    )

    content_project_id: Mapped[int] = mapped_column(
        ForeignKey("content_projects.id", ondelete="CASCADE"), index=True
    )
    #: 0 = Monday … 6 = Sunday.
    weekday: Mapped[int] = mapped_column(Integer)
    every_weeks: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    #: Days the operator removed by hand; the rule does not put them back.
    skipped_days: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )


class CalendarEvent(IdMixin, TimestampMixin, Base):
    """An own date for the calendar (launch, gamescom, a brand campaign …) (Ausbau A5).

    Public holidays and fixed occasions are computed in :mod:`services.events`.
    """

    __tablename__ = "calendar_events"

    name: Mapped[str] = mapped_column(String(200))
    day: Mapped[date] = mapped_column(Date, index=True)
    ends_on: Mapped[date | None] = mapped_column(Date)
    #: ``de``, ``en`` or both.
    languages: Mapped[list[Any]] = mapped_column(default=list, server_default='["de", "en"]')
    content_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("content_projects.id", ondelete="CASCADE"), index=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )


class ContentFocus(IdMixin, Base):
    """A topic that gets priority within a topic area for a period (e.g. GTA 6 this week)."""

    __tablename__ = "content_focus"

    content_project_id: Mapped[int] = mapped_column(
        ForeignKey("content_projects.id", ondelete="CASCADE"), index=True
    )
    topic: Mapped[str] = mapped_column(String(200))
    starts_on: Mapped[date] = mapped_column(Date, index=True)
    ends_on: Mapped[date] = mapped_column(Date, index=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
