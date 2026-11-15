"""Calls of the AI layer (extension phase E3): one row per request, mock or live."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import AICallStatus
from database.base import Base, IdMixin, str_enum


class AICall(IdMixin, Base):
    """Usage and cost of one AI request.

    A live call first reserves its worst-case cost (``estimated_usd``) under the
    monthly cap; afterwards ``cost_usd`` holds the real cost from the token usage.
    """

    __tablename__ = "ai_calls"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: What the call was for, e.g. ``chat``, ``ideas``, ``title``.
    purpose: Mapped[str] = mapped_column(String(64), index=True)
    #: ``text`` (cheap model) or ``reasoning`` (chat, ideas, planning).
    tier: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    status: Mapped[AICallStatus] = mapped_column(
        str_enum(AICallStatus, "ai_call_status"), default=AICallStatus.RESERVED, index=True
    )
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    estimated_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0, server_default="0")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    request_id: Mapped[str | None] = mapped_column(String(128))
    error: Mapped[str | None] = mapped_column(Text)
    content_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("content_projects.id", ondelete="SET NULL"), index=True
    )
    agent_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    cost_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("costs.id", ondelete="SET NULL")
    )
