"""Editorial planning (extension phase E4, calendar view in E6).

The plan says *which topic area is on which day* and which topic gets the focus.
How many posts a channel gets stays with the Publishing Strategy Agent.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, Text, UniqueConstraint, func
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
