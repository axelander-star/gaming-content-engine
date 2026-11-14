"""Agent 18: Budget & Cost (PROJECT_SPEC sections 6 and 13).

Computes the current budget level, records it as a decision and notifies the
operator once per month and level when the level rises above ``normal``.
The actual enforcement happens in :mod:`services.budget` and the gates.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from agents.base import Agent, AgentContext, AgentResult
from core.enums import NotificationLevel
from models.access import Notification
from models.control import AgentDecision
from services.budget import BudgetLevel, budget_status, month_start

_NOTIFY_LEVEL = {
    BudgetLevel.WARN: NotificationLevel.WARNING,
    BudgetLevel.REDUCED: NotificationLevel.WARNING,
    BudgetLevel.PRIORITY_ONLY: NotificationLevel.ERROR,
    BudgetLevel.STOP_PAID: NotificationLevel.CRITICAL,
}

_TEXT = {
    BudgetLevel.WARN: "Budgetwarnung: {pct} % des Monatsbudgets verbraucht.",
    BudgetLevel.REDUCED: "Budget bei {pct} %: Verarbeitung wird auf lokale Mittel reduziert.",
    BudgetLevel.PRIORITY_ONLY: "Budget bei {pct} %: nur noch priorisierte Aufträge.",
    BudgetLevel.STOP_PAID: "Budget bei {pct} %: keine kostenpflichtigen Aufrufe mehr.",
}


class BudgetCostAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        status = budget_status(ctx.session, ctx.settings)
        info = {
            "level": status.level.value,
            "used_pct": status.used_pct,
            "spent_eur": str(status.spent_eur),
            "budget_eur": str(status.budget_eur),
        }
        notified = False
        if status.level != BudgetLevel.NORMAL and not self._already_notified(ctx, status.level):
            pct = status.used_pct
            if status.budget_eur <= 0:
                title = "Kein Monatsbudget gesetzt: kostenpflichtige Aufrufe sind gesperrt."
            else:
                title = _TEXT[status.level].format(pct=pct)
            ctx.session.add(
                Notification(
                    level=_NOTIFY_LEVEL[status.level],
                    title=title,
                    body=f"Ausgegeben {status.spent_eur} € von {status.budget_eur} €.",
                )
            )
            notified = True
        ctx.decide(
            "budget_level",
            {**info, "notified": notified},
            f"Spent {status.spent_eur} EUR of {status.budget_eur} EUR this month "
            f"({status.used_pct} %), level {status.level.value}.",
            inputs={"thresholds": self._thresholds(ctx)},
        )
        return AgentResult(output={**info, "notified": notified})

    @staticmethod
    def _already_notified(ctx: AgentContext, level: BudgetLevel) -> bool:
        """True if this month a notification for ``level`` was already sent."""
        rows = ctx.session.scalars(
            select(AgentDecision.decision).where(
                AgentDecision.agent_name == "budget_cost",
                AgentDecision.decision_type == "budget_level",
                AgentDecision.created_at >= month_start(),
            )
        ).all()
        return any(r.get("notified") and r.get("level") == level.value for r in rows)

    @staticmethod
    def _thresholds(ctx: AgentContext) -> dict[str, int]:
        s = ctx.settings
        return {
            "warn": s.budget_warn_pct,
            "reduced": s.budget_reduced_pct,
            "priority_only": s.budget_priority_only_pct,
            "stop_paid": s.budget_stop_paid_pct,
        }
