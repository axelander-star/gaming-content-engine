"""Agents page: status of all agents, pause/resume, runs, decisions, budget."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from redis import Redis
from sqlalchemy import func, select

from agents.registry import AgentSpec, all_specs, get_spec
from api.deps import Admin, AppSettings, DbSession, Operator, Viewer, csrf_protect
from core.enums import AgentRunStatus
from models.control import AgentDecision, AgentRun, Cost
from services import agent_control, audit
from services.budget import budget_status, month_start
from services.controls import effective_controls
from services.orchestrator import submit
from services.queue import get_redis

router = APIRouter(prefix="/agents", tags=["agents"], dependencies=[Depends(csrf_protect)])

AgentStatus = Literal["not_available", "stopped", "paused", "running", "error", "ready"]

#: Agents the operator may start by hand (they do not work on a single entity).
MANUAL_RUN = {
    "master",
    "budget_cost",
    "trend_research",
    "game_intelligence",
    "material_scout",  # material needs sweep
    "rights_license",  # license expiry sweep
    "research",
    "idea_lab",
}


class AgentOut(BaseModel):
    name: str
    number: int
    title: str
    description: str
    phase: int
    cost_kind: str
    stage: str | None
    implemented: bool
    enabled: bool
    status: AgentStatus
    can_run_manually: bool
    last_run_at: datetime | None
    last_run_status: AgentRunStatus | None
    last_error: str | None
    current_task: dict[str, Any] | None
    runs_today: int
    cost_month_eur: Decimal


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_name: str
    status: AgentRunStatus
    started_at: datetime
    finished_at: datetime | None
    input: dict[str, Any]
    output: dict[str, Any]
    error: str | None
    cost_eur: Decimal


class AgentDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_run_id: int | None
    agent_name: str
    decision_type: str
    entity_type: str | None
    entity_id: int | None
    decision: dict[str, Any]
    reasoning: str | None
    created_at: datetime


class BudgetOut(BaseModel):
    budget_eur: Decimal
    spent_eur: Decimal
    used_pct: float
    level: str
    paid_api_calls_enabled: bool


class RunQueued(BaseModel):
    agent: str
    job_id: str


class PauseBody(BaseModel):
    note: str | None = None


def _spec_or_404(name: str) -> AgentSpec:
    spec = get_spec(name)
    if spec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return spec


def _status(
    spec: AgentSpec, enabled: bool, stop: bool, last: AgentRun | None, running: bool
) -> AgentStatus:
    if not spec.implemented:
        return "not_available"
    if stop:
        return "stopped"
    if not enabled:
        return "paused"
    if running:
        return "running"
    if last is not None and last.status == AgentRunStatus.FAILED:
        return "error"
    return "ready"


def _latest_runs(db: DbSession) -> dict[str, AgentRun]:
    """Latest finished-or-running run per agent (one query)."""
    sub = (
        select(AgentRun.agent_name, func.max(AgentRun.id).label("max_id"))
        .where(AgentRun.status != AgentRunStatus.SKIPPED)
        .group_by(AgentRun.agent_name)
        .subquery()
    )
    rows = db.scalars(select(AgentRun).join(sub, AgentRun.id == sub.c.max_id)).all()
    return {r.agent_name: r for r in rows}


@router.get("", response_model=list[AgentOut])
def list_agents(_: Viewer, db: DbSession, settings: AppSettings) -> list[AgentOut]:
    stop = effective_controls(db, settings).emergency_stop
    enabled = agent_control.enabled_map(db)
    latest = _latest_runs(db)
    running = {
        r.agent_name: r
        for r in db.scalars(
            select(AgentRun).where(AgentRun.status == AgentRunStatus.RUNNING).order_by(AgentRun.id)
        )
    }
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    runs_today: dict[str, int] = {
        name: n
        for name, n in db.execute(
            select(AgentRun.agent_name, func.count())
            .where(AgentRun.started_at >= today, AgentRun.status != AgentRunStatus.SKIPPED)
            .group_by(AgentRun.agent_name)
        )
    }
    costs: dict[str, Decimal] = {
        name: total
        for name, total in db.execute(
            select(AgentRun.agent_name, func.sum(Cost.amount_eur))
            .join(AgentRun, Cost.agent_run_id == AgentRun.id)
            .where(Cost.incurred_at >= month_start())
            .group_by(AgentRun.agent_name)
        )
    }
    out = []
    for spec in all_specs():
        last = latest.get(spec.name)
        is_enabled = enabled.get(spec.name, True)
        current = running.get(spec.name)
        out.append(
            AgentOut(
                name=spec.name,
                number=spec.number,
                title=spec.title,
                description=spec.description,
                phase=spec.phase,
                cost_kind=spec.cost_kind.value,
                stage=f"{spec.stage.entity_type}:{spec.stage.status}" if spec.stage else None,
                implemented=spec.implemented,
                enabled=is_enabled,
                status=_status(spec, is_enabled, stop, last, current is not None),
                can_run_manually=spec.name in MANUAL_RUN and spec.implemented,
                last_run_at=last.started_at if last else None,
                last_run_status=last.status if last else None,
                last_error=last.error if last and last.status == AgentRunStatus.FAILED else None,
                current_task=current.input if current else None,
                runs_today=runs_today.get(spec.name, 0),
                cost_month_eur=costs.get(spec.name) or Decimal(0),
            )
        )
    return out


@router.get("/decisions", response_model=list[AgentDecisionOut])
def list_decisions(
    _: Viewer,
    db: DbSession,
    agent: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AgentDecision]:
    q = select(AgentDecision).order_by(AgentDecision.id.desc()).limit(limit)
    if agent:
        q = q.where(AgentDecision.agent_name == agent)
    return list(db.scalars(q))


@router.get("/budget", response_model=BudgetOut)
def get_budget(_: Viewer, db: DbSession, settings: AppSettings) -> BudgetOut:
    s = budget_status(db, settings)
    return BudgetOut(
        budget_eur=s.budget_eur,
        spent_eur=s.spent_eur,
        used_pct=s.used_pct,
        level=s.level.value,
        paid_api_calls_enabled=effective_controls(db, settings).paid_api_calls_enabled,
    )


@router.get("/{name}/runs", response_model=list[AgentRunOut])
def list_runs(
    name: str,
    _: Viewer,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> list[AgentRun]:
    _spec_or_404(name)
    return list(
        db.scalars(
            select(AgentRun)
            .where(AgentRun.agent_name == name)
            .order_by(AgentRun.id.desc())
            .limit(limit)
        )
    )


@router.post("/{name}/pause", status_code=status.HTTP_204_NO_CONTENT)
def pause_agent(name: str, user: Operator, db: DbSession, body: PauseBody | None = None) -> None:
    _spec_or_404(name)
    agent_control.set_enabled(db, name, False, user.id, body.note if body else None)
    db.commit()


@router.post("/{name}/resume", status_code=status.HTTP_204_NO_CONTENT)
def resume_agent(name: str, admin: Admin, db: DbSession) -> None:
    _spec_or_404(name)
    agent_control.set_enabled(db, name, True, admin.id)
    db.commit()


@router.post("/{name}/run", response_model=RunQueued, status_code=status.HTTP_202_ACCEPTED)
def run_now(
    name: str,
    admin: Admin,
    db: DbSession,
    settings: AppSettings,
    redis: Annotated[Redis, Depends(get_redis)],
) -> RunQueued:
    spec = _spec_or_404(name)
    if name not in MANUAL_RUN or not spec.implemented:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Agent cannot be run manually")
    if effective_controls(db, settings).emergency_stop:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Emergency stop is active")
    if not agent_control.is_enabled(db, name):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Agent is paused")
    payload = {"sweep": True} if spec.stage else {}
    job = submit(name, payload, priority=True, connection=redis)
    audit.record(db, "agent.run_manual", user_id=admin.id, entity_type="agents",
                 after={"agent": name, "job_id": job.id})  # fmt: skip
    db.commit()
    return RunQueued(agent=name, job_id=job.id)
