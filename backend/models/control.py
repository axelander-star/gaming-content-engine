"""Agent runs, agent decisions and costs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import AgentRunStatus, CostCategory
from database.base import Base, IdMixin, str_enum


class AgentRun(IdMixin, Base):
    __tablename__ = "agent_runs"

    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[AgentRunStatus] = mapped_column(
        str_enum(AgentRunStatus, "agent_run_status"), default=AgentRunStatus.RUNNING
    )
    queue_job_id: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    output: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    cost_eur: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0, server_default="0")


class AgentDecision(IdMixin, Base):
    """Every important decision with its inputs and reasoning (business rule 10)."""

    __tablename__ = "agent_decisions"

    agent_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    decision_type: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    decision: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    inputs: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    reasoning: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Cost(IdMixin, Base):
    __tablename__ = "costs"

    category: Mapped[CostCategory] = mapped_column(str_enum(CostCategory, "cost_category"))
    provider: Mapped[str | None] = mapped_column(String(64))
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    unit: Mapped[str | None] = mapped_column(String(32))
    agent_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    incurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
