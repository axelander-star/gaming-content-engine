"""Agent contract shared by all 18 agents (docs/AGENTS.md).

An agent does one well-defined step. It never calls other agents directly:
it writes results to the database, records decisions and costs through the
:class:`AgentContext`, and returns an :class:`AgentResult` to the master
orchestrator, which decides what happens next.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import CostCategory
from models.control import AgentDecision, AgentRun, Cost


class CostKind(StrEnum):
    """How an agent may cause external costs (drives budget gates)."""

    LOCAL = "local"  # runs on our server only
    FREE_API = "free_api"  # external API without per-call cost (quota only)
    PAID = "paid"  # may call paid APIs (LLM, TTS, ...)


@dataclass(frozen=True)
class Stage:
    """The entity status an agent works on (its place in the pipeline)."""

    entity_type: str  # "gameplay_files" | "variants"
    status: str


@dataclass
class AgentResult:
    ok: bool = True
    output: dict[str, Any] = field(default_factory=dict)
    message: str | None = None


class BudgetExceededError(RuntimeError):
    """Raised when a paid action is refused by the budget service."""


@dataclass
class AgentContext:
    """Everything an agent may use while running. Created by the orchestrator."""

    session: Session
    settings: Settings
    run: AgentRun
    agent_name: str

    def decide(
        self,
        decision_type: str,
        decision: dict[str, Any],
        reasoning: str,
        *,
        inputs: dict[str, Any] | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
    ) -> AgentDecision:
        """Record a decision with its reasoning (business rule 10)."""
        row = AgentDecision(
            agent_run_id=self.run.id,
            agent_name=self.agent_name,
            decision_type=decision_type,
            decision=decision,
            reasoning=reasoning,
            inputs=inputs or {},
            entity_type=entity_type,
            entity_id=entity_id,
        )
        self.session.add(row)
        return row

    def authorize_cost(self, estimated_eur: Decimal, *, priority: bool = False) -> None:
        """Ask the budget service before any paid call. Raises if refused."""
        from services.budget import authorize_paid_call

        decision = authorize_paid_call(self.session, self.settings, estimated_eur, priority)
        if not decision.allowed:
            raise BudgetExceededError(decision.reason)

    def add_cost(
        self,
        amount_eur: Decimal,
        category: CostCategory,
        *,
        provider: str | None = None,
        description: str | None = None,
    ) -> None:
        """Book an actual cost against this run."""
        self.session.add(
            Cost(
                category=category,
                provider=provider,
                amount_eur=amount_eur,
                agent_run_id=self.run.id,
                description=description,
            )
        )
        self.run.cost_eur = (self.run.cost_eur or Decimal(0)) + amount_eur


class Agent(ABC):
    """Base class for an implemented agent."""

    @abstractmethod
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        """Do one step. Must be idempotent for the same payload."""
