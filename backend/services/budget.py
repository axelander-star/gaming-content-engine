"""Budget levels and authorization of paid calls (PROJECT_SPEC section 13).

The monthly budget comes from the operator settings (dashboard). Levels:

    < warn            normal         no restriction
    >= warn  (50 %)   warn           notify operator
    >= reduced (70 %) reduced        prefer local processing
    >= priority (85%) priority_only  only prioritized jobs
    >= stop (95 %)    stop_paid      no paid external calls at all
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import Settings
from models.control import Cost
from services.controls import effective_controls, get_operations


class BudgetLevel(StrEnum):
    NORMAL = "normal"
    WARN = "warn"
    REDUCED = "reduced"
    PRIORITY_ONLY = "priority_only"
    STOP_PAID = "stop_paid"


@dataclass(frozen=True)
class BudgetStatus:
    budget_eur: Decimal
    spent_eur: Decimal
    used_pct: float
    level: BudgetLevel


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reason: str
    status: BudgetStatus


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def spent_this_month(session: Session, now: datetime | None = None) -> Decimal:
    total = session.scalar(
        select(func.coalesce(func.sum(Cost.amount_eur), 0)).where(
            Cost.incurred_at >= month_start(now)
        )
    )
    return Decimal(total or 0)


def fixed_monthly(settings: Settings) -> Decimal:
    """Fixed monthly costs (server, backups, domain); they run even when paused."""
    return Decimal(str(settings.server_monthly_eur)) + Decimal(
        str(settings.other_fixed_monthly_eur)
    )


def level_for(used_pct: float, settings: Settings) -> BudgetLevel:
    if used_pct >= settings.budget_stop_paid_pct:
        return BudgetLevel.STOP_PAID
    if used_pct >= settings.budget_priority_only_pct:
        return BudgetLevel.PRIORITY_ONLY
    if used_pct >= settings.budget_reduced_pct:
        return BudgetLevel.REDUCED
    if used_pct >= settings.budget_warn_pct:
        return BudgetLevel.WARN
    return BudgetLevel.NORMAL


def budget_status(
    session: Session, settings: Settings, now: datetime | None = None
) -> BudgetStatus:
    budget = Decimal(str(get_operations(session).monthly_budget_eur))
    spent = spent_this_month(session, now) + fixed_monthly(settings)
    if budget <= 0:
        used = 100.0 if spent > 0 else 0.0
        level = BudgetLevel.STOP_PAID  # no budget means no paid calls
    else:
        used = float(spent / budget * 100)
        level = level_for(used, settings)
    return BudgetStatus(budget_eur=budget, spent_eur=spent, used_pct=round(used, 2), level=level)


def authorize_paid_call(
    session: Session, settings: Settings, estimated_eur: Decimal, priority: bool = False
) -> BudgetDecision:
    """Decide whether a paid external call may happen now."""
    status = budget_status(session, settings)
    controls = effective_controls(session, settings)
    if not controls.paid_api_calls_enabled:
        return BudgetDecision(False, "Paid API calls are disabled (PAID_API_CALLS_ENABLED)", status)
    if status.level == BudgetLevel.STOP_PAID:
        return BudgetDecision(False, f"Budget at {status.used_pct}% - paid calls stopped", status)
    if status.level == BudgetLevel.PRIORITY_ONLY and not priority:
        return BudgetDecision(False, f"Budget at {status.used_pct}% - priority jobs only", status)
    if status.budget_eur > 0 and status.spent_eur + estimated_eur > status.budget_eur:
        return BudgetDecision(False, "Estimated cost would exceed the monthly budget", status)
    return BudgetDecision(True, "ok", status)
