"""Phase 4: agent registry, budget, gates, orchestrator, master and scheduler."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from redis import Redis
from rq import SimpleWorker
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents import registry
from agents.base import Agent, AgentContext, AgentResult, CostKind
from agents.master import MasterOrchestratorAgent
from core.config import Settings, get_settings
from core.enums import (
    AgentRunStatus,
    CostCategory,
    LicenseStatus,
    MaterialStatus,
    NotificationLevel,
    VideoStatus,
)
from models import AgentDecision, AgentRun, Cost, Notification, QualityCheck
from services import agent_control, budget, gates, orchestrator, workflow
from services.controls import update_operations, update_runtime_controls
from services.queue import get_queue
from tests.factories import Chain, build_chain

pytestmark = pytest.mark.integration


def make_settings(**changes: Any) -> Settings:
    return get_settings().model_copy(update=changes)


class AdvanceAgent(Agent):
    """Fake production agent: moves the variant one step forward."""

    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        variant = gates.load_entity(ctx.session, "variants", payload["entity_id"])
        assert variant is not None
        workflow.transition(ctx.session, variant, VideoStatus.EDITING, actor=ctx.agent_name)
        ctx.decide("cut", {"ok": True}, "test", entity_type="variants", entity_id=variant.id)
        return AgentResult(output={"variant": variant.id})


class BrokenAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        raise ValueError("ffmpeg exploded")


class PaidAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        ctx.authorize_cost(Decimal("1.00"))
        ctx.add_cost(Decimal("1.00"), CostCategory.AI, provider="test")
        return AgentResult()


def payload_for(chain: Chain) -> dict[str, Any]:
    return {"entity_type": "variants", "entity_id": chain.variant.id, "status": "SCENE_SELECTED"}


def ready_chain(db: Session) -> Chain:
    chain = build_chain(db)
    chain.gameplay_file.status = MaterialStatus.ANALYZED
    db.flush()
    return chain


# --- registry ---------------------------------------------------------------


def test_registry_lists_all_20_agents() -> None:
    specs = registry.all_specs()
    assert [s.number for s in specs] == list(range(1, 21))
    assert {s.name for s in specs if s.implemented} == {
        "master",
        "budget_cost",
        "trend_research",
        "game_intelligence",
        "material_scout",
        "rights_license",
        "gameplay_analysis",
        "clip_production",
        "creative_director",
        "script_hook",
        "localization",
        "voice",
        "subtitle",
        "quality_control",
        "publishing_strategy",
        "publishing",
        "analytics",
        "learning",
        "research",
        "idea_lab",
    }
    stages = [s.stage.status for s in registry.stage_specs() if s.stage]
    assert stages[0] == "DISCOVERED" and "SCHEDULED" in stages


# --- budget -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("pct", "level"),
    [
        (0, budget.BudgetLevel.NORMAL),
        (50, budget.BudgetLevel.WARN),
        (70, budget.BudgetLevel.REDUCED),
        (85, budget.BudgetLevel.PRIORITY_ONLY),
        (95, budget.BudgetLevel.STOP_PAID),
        (120, budget.BudgetLevel.STOP_PAID),
    ],
)
def test_budget_levels(pct: float, level: budget.BudgetLevel) -> None:
    assert budget.level_for(pct, get_settings()) == level


def add_spend(db: Session, eur: str) -> None:
    db.add(Cost(category=CostCategory.AI, amount_eur=Decimal(eur)))
    db.flush()


def test_budget_status_and_authorization(db: Session) -> None:
    update_operations(db, None, {"monthly_budget_eur": 50})
    add_spend(db, "30")
    status = budget.budget_status(db, get_settings())
    assert status.used_pct == 60.0 and status.level == budget.BudgetLevel.WARN

    # Paid calls are disabled by default: always refused.
    refused = budget.authorize_paid_call(db, get_settings(), Decimal("1"))
    assert not refused.allowed and "disabled" in refused.reason

    paid = make_settings(paid_api_calls_enabled=True)
    assert budget.authorize_paid_call(db, paid, Decimal("1")).allowed
    assert not budget.authorize_paid_call(db, paid, Decimal("25")).allowed  # over budget

    add_spend(db, "14")  # 88 % -> priority only
    assert not budget.authorize_paid_call(db, paid, Decimal("1")).allowed
    assert budget.authorize_paid_call(db, paid, Decimal("1"), priority=True).allowed
    add_spend(db, "4")  # 96 % -> stop
    assert not budget.authorize_paid_call(db, paid, Decimal("0.01"), priority=True).allowed


def test_zero_budget_stops_paid_calls(db: Session) -> None:
    update_operations(db, None, {"monthly_budget_eur": 0})
    assert budget.budget_status(db, get_settings()).level == budget.BudgetLevel.STOP_PAID


def test_costs_from_previous_month_do_not_count(db: Session) -> None:
    update_operations(db, None, {"monthly_budget_eur": 50})
    last_month = budget.month_start() - timedelta(days=1)
    db.add(Cost(category=CostCategory.AI, amount_eur=Decimal(40), incurred_at=last_month))
    db.flush()
    assert budget.spent_this_month(db) == 0


# --- gates ------------------------------------------------------------------


def spec(name: str) -> registry.AgentSpec:
    s = registry.get_spec(name)
    assert s is not None
    return s


def test_gates_block_unimplemented_paused_and_emergency(db: Session) -> None:
    chain = ready_chain(db)
    settings = get_settings()
    with registry.override("clip_production", None) as missing:
        assert gates.check(db, settings, missing, payload_for(chain)).code == "not_implemented"

    with registry.override("clip_production", AdvanceAgent) as patched:
        assert gates.check(db, settings, patched, payload_for(chain)).allowed
        agent_control.set_enabled(db, "clip_production", False, None)
        assert gates.check(db, settings, patched, payload_for(chain)).code == "agent_paused"
        agent_control.set_enabled(db, "clip_production", True, None)
        update_runtime_controls(db, None, emergency_stop=True)
        assert gates.check(db, settings, patched, payload_for(chain)).code == "emergency_stop"


def test_gates_check_entity_status_and_rights(db: Session) -> None:
    chain = build_chain(db)  # source material not yet ANALYZED
    settings = get_settings()
    with registry.override("clip_production", AdvanceAgent) as patched:
        assert gates.check(db, settings, patched, payload_for(chain)).code == "rights"
        chain.gameplay_file.status = MaterialStatus.ANALYZED
        chain.license.valid_until = date.today() - timedelta(days=1)
        db.flush()
        result = gates.check(db, settings, patched, payload_for(chain))
        assert result.code == "rights" and "Abgelaufen" in result.reason
        chain.license.valid_until = None
        chain.license.status = LicenseStatus.REVOKED
        db.flush()
        assert gates.check(db, settings, patched, payload_for(chain)).code == "rights"
        chain.license.status = LicenseStatus.APPROVED
        chain.variant.status = VideoStatus.EDITING
        db.flush()
        assert gates.check(db, settings, patched, payload_for(chain)).code == "wrong_status"
        bad = {"entity_type": "variants", "entity_id": 999_999}
        assert gates.check(db, settings, patched, bad).code == "entity_missing"
        assert gates.check(db, settings, patched, {}).code == "bad_payload"


def test_quality_gate_before_publishing(db: Session) -> None:
    chain = ready_chain(db)
    chain.variant.status = VideoStatus.READY_TO_PUBLISH
    db.flush()
    payload = {"entity_type": "variants", "entity_id": chain.variant.id}
    with registry.override("publishing_strategy", AdvanceAgent) as patched:
        assert gates.check(db, get_settings(), patched, payload).code == "quality"
        db.add(QualityCheck(variant_id=chain.variant.id, passed=True, score=0.5))
        db.flush()
        assert gates.check(db, get_settings(), patched, payload).code == "quality"  # below 0.7
        chain.variant.quality_score = 0.9
        db.flush()
        assert gates.check(db, get_settings(), patched, payload).allowed


def test_channel_gate_for_publishing(db: Session) -> None:
    chain = ready_chain(db)
    chain.variant.status = VideoStatus.SCHEDULED
    chain.variant.quality_score = 0.9
    db.add(QualityCheck(variant_id=chain.variant.id, passed=True, score=0.9))
    chain.channel.is_paused = True
    db.flush()
    payload = {"entity_type": "variants", "entity_id": chain.variant.id}
    with registry.override("publishing", AdvanceAgent) as patched:
        assert gates.check(db, get_settings(), patched, payload).code == "channel"
        chain.channel.is_paused = False
        db.flush()
        assert gates.check(db, get_settings(), patched, payload).allowed  # mock mode
        live = make_settings(publishing_mode="live")
        result = gates.check(db, live, patched, payload)
        assert result.code == "channel" and "not allowed" in result.reason


def test_daily_production_limit(db: Session) -> None:
    chain = ready_chain(db)
    update_operations(db, None, {"max_daily_production_jobs": 1})
    db.add(AgentRun(agent_name="clip_production", status=AgentRunStatus.SUCCEEDED))
    db.flush()
    with registry.override("clip_production", AdvanceAgent) as patched:
        assert gates.check(db, get_settings(), patched, payload_for(chain)).code == "daily_limit"


def test_paid_agent_blocked_by_budget_only_when_paid_calls_possible(db: Session) -> None:
    update_operations(db, None, {"monthly_budget_eur": 10})
    add_spend(db, "10")
    with registry.override("trend_research", PaidAgent, cost_kind=CostKind.PAID) as p:
        assert gates.check(db, get_settings(), p, {}).allowed  # mock providers only
        paid = make_settings(paid_api_calls_enabled=True)
        assert gates.check(db, paid, p, {}).code == "budget_stop"


# --- orchestrator -----------------------------------------------------------


def test_run_agent_success_advances_pipeline(db: Session) -> None:
    chain = ready_chain(db)
    with registry.override("clip_production", AdvanceAgent):
        run = orchestrator.run_agent(db, get_settings(), "clip_production", payload_for(chain))
    assert run.status == AgentRunStatus.SUCCEEDED and run.finished_at is not None
    assert chain.variant.status == VideoStatus.EDITING
    decision = db.scalar(select(AgentDecision).where(AgentDecision.agent_run_id == run.id))
    assert decision is not None and decision.decision_type == "cut"

    # Running the same job again is a no-op: the variant moved on.
    with registry.override("clip_production", AdvanceAgent):
        again = orchestrator.run_agent(db, get_settings(), "clip_production", payload_for(chain))
    assert again.status == AgentRunStatus.SKIPPED and again.output["gate"] == "wrong_status"


def test_run_agent_failure_marks_entity_failed_and_master_retries(db: Session) -> None:
    chain = ready_chain(db)
    with registry.override("clip_production", BrokenAgent):
        run = orchestrator.run_agent(db, get_settings(), "clip_production", payload_for(chain))
    assert run.status == AgentRunStatus.FAILED and "ffmpeg exploded" in (run.error or "")
    db.refresh(chain.variant)
    assert chain.variant.status == VideoStatus.FAILED
    assert chain.variant.failed_step == "clip_production"

    master = MasterOrchestratorAgent(submit=lambda name, payload: None)
    settings = make_settings(agent_retry_base_delay_s=0)
    ctx_run = AgentRun(agent_name="master")
    db.add(ctx_run)
    db.flush()
    ctx = AgentContext(db, settings, ctx_run, "master")
    # Retry back-off: with the default delay nothing is retried yet.
    out = master.run(AgentContext(db, get_settings(), ctx_run, "master"), {})
    assert out.output["retried"] == []
    out = master.run(ctx, {})
    assert out.output["retried"][0]["entity_id"] == chain.variant.id
    assert chain.variant.status == VideoStatus.SCENE_SELECTED and chain.variant.retry_count == 1


def test_run_agent_skips_when_gate_closed(db: Session) -> None:
    with registry.override("clip_production", None):
        run = orchestrator.run_agent(db, get_settings(), "clip_production", {})
    assert run.status == AgentRunStatus.SKIPPED and run.output["gate"] == "not_implemented"


def test_budget_refusal_inside_agent_is_skipped_not_failed(db: Session) -> None:
    with registry.override("trend_research", PaidAgent, cost_kind=CostKind.PAID):
        run = orchestrator.run_agent(db, get_settings(), "trend_research", {})
    assert run.status == AgentRunStatus.SKIPPED and "disabled" in (run.error or "")
    assert db.scalar(select(Cost).where(Cost.agent_run_id == run.id)) is None


def test_unknown_agent() -> None:
    with pytest.raises(orchestrator.UnknownAgentError):
        orchestrator.submit("nope", {})


# --- master -----------------------------------------------------------------


def test_master_dispatches_ready_work_and_reports_waiting(db: Session) -> None:
    chain = ready_chain(db)
    submitted: list[tuple[str, dict[str, Any]]] = []
    run = AgentRun(agent_name="master")
    db.add(run)
    db.flush()
    ctx = AgentContext(db, get_settings(), run, "master")
    master = MasterOrchestratorAgent(submit=lambda n, p: submitted.append((n, p)))

    with registry.override("clip_production", None):
        result = master.run(ctx, {})
    assert submitted == []
    assert result.output["waiting"]["clip_production"]["reason"] == "waiting_for_phase_7"

    with registry.override("clip_production", AdvanceAgent):
        result = master.run(ctx, {})
        assert submitted == [("clip_production", payload_for(chain))]
        update_operations(db, None, {"max_daily_production_jobs": 0})
        submitted.clear()
        result = master.run(ctx, {})
        assert submitted == [] and result.output["waiting"]["clip_production"]["reason"] == (
            "daily_limit"
        )
    decision = db.scalar(
        select(AgentDecision)
        .where(AgentDecision.agent_name == "master", AgentDecision.decision_type == "dispatch")
        .order_by(AgentDecision.id.desc())
    )
    assert decision is not None and "dispatched" in (decision.reasoning or "")


def test_master_does_nothing_during_emergency_stop(db: Session) -> None:
    ready_chain(db)
    update_runtime_controls(db, None, emergency_stop=True)
    run = orchestrator.run_agent(db, get_settings(), "master", {})
    assert run.status == AgentRunStatus.SKIPPED and run.output["gate"] == "emergency_stop"


def test_master_records_blocked_entities(db: Session) -> None:
    build_chain(db)  # material not analyzed -> rights gate blocks
    run = AgentRun(agent_name="master")
    db.add(run)
    db.flush()
    with registry.override("clip_production", AdvanceAgent):
        result = MasterOrchestratorAgent(submit=lambda n, p: None).run(
            AgentContext(db, get_settings(), run, "master"), {}
        )
    assert result.output["blocked"][0]["gate"] == "rights"


# --- budget agent -----------------------------------------------------------


def test_budget_agent_notifies_once_per_level(db: Session) -> None:
    update_operations(db, None, {"monthly_budget_eur": 50})
    add_spend(db, "30")
    first = orchestrator.run_agent(db, get_settings(), "budget_cost", {})
    second = orchestrator.run_agent(db, get_settings(), "budget_cost", {})
    assert first.output["level"] == "warn" and first.output["notified"] is True
    assert second.output["notified"] is False
    notes = db.scalars(select(Notification).where(Notification.title.like("Budget%"))).all()
    assert len(notes) == 1 and notes[0].level == NotificationLevel.WARNING


# --- queue and worker -------------------------------------------------------


@contextmanager
def _shared(db: Session) -> Iterator[Session]:
    yield db


def test_submit_is_idempotent_and_worker_executes_job(
    db: Session, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    chain = ready_chain(db)
    with registry.override("clip_production", AdvanceAgent):
        first = orchestrator.submit("clip_production", payload_for(chain), connection=redis_client)
        second = orchestrator.submit("clip_production", payload_for(chain), connection=redis_client)
        assert first.id == second.id
        assert get_queue("default", redis_client).count == 1

        monkeypatch.setattr(orchestrator, "get_sessionmaker", lambda: lambda: _shared(db))
        worker = SimpleWorker([get_queue("default", redis_client)], connection=redis_client)
        assert worker.work(burst=True)
    job = get_queue("default", redis_client).fetch_job(first.id)
    assert job is not None and job.return_value()["status"] == "succeeded"  # type: ignore[index]
    assert chain.variant.status == VideoStatus.EDITING


def test_scheduler_enqueues_due_agents(
    engine: object, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import scheduler

    calls: list[str] = []
    monkeypatch.setattr(scheduler, "submit", lambda name, payload: calls.append(name))
    sched = scheduler.Schedule({"master": 60, "budget_cost": 3600})
    settings = get_settings()
    assert scheduler.tick(sched, 1000.0, settings) == ["master", "budget_cost"]
    assert scheduler.tick(sched, 1030.0, settings) == []
    assert scheduler.tick(sched, 1061.0, settings) == ["master"]
    stopped = make_settings(emergency_stop=True)
    assert scheduler.tick(sched, 2000.0, stopped) == []
    assert calls == ["master", "budget_cost", "master"]


def test_month_start() -> None:
    now = datetime(2026, 11, 14, 15, 30, tzinfo=UTC)
    assert budget.month_start(now) == datetime(2026, 11, 1, tzinfo=UTC)


def test_material_stage_rechecks_rights(db: Session) -> None:
    chain = build_chain(db)
    chain.gameplay_file.status = MaterialStatus.RIGHTS_APPROVED
    chain.license.status = LicenseStatus.REVOKED
    db.flush()
    payload = {"entity_type": "gameplay_files", "entity_id": chain.gameplay_file.id}
    with registry.override("gameplay_analysis", AdvanceAgent) as patched:
        assert gates.check(db, get_settings(), patched, payload).code == "rights"
        chain.license.status = LicenseStatus.APPROVED
        db.flush()
        assert gates.check(db, get_settings(), patched, payload).allowed


def test_live_publishing_requires_authorized_channel(db: Session) -> None:
    chain = ready_chain(db)
    chain.variant.status = VideoStatus.SCHEDULED
    chain.variant.quality_score = 0.9
    db.add(QualityCheck(variant_id=chain.variant.id, passed=True, score=0.9))
    chain.channel.is_paused = False  # seeded channels start paused
    db.flush()
    update_runtime_controls(db, None, auto_publish_enabled=True)
    live = make_settings(publishing_mode="live", auto_publish_enabled=True)
    payload = {"entity_type": "variants", "entity_id": chain.variant.id}
    with registry.override("publishing", AdvanceAgent) as patched:
        result = gates.check(db, live, patched, payload)
    assert result.code == "channel" and "not authorized" in result.reason
