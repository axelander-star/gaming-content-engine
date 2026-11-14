"""Central gate checks that every agent job passes before it runs.

The master orchestrator checks the gates when it hands out a job, and the
orchestrator checks them again right before execution, because the situation
can change while a job waits in the queue (emergency stop, pause, budget).

Gates (in this order):

1. emergency stop (environment or dashboard)
2. agent implemented in the current phase
3. agent not paused by the operator
4. budget, for agents that may cause paid calls (only while paid calls are
   possible at all; with ``PAID_API_CALLS_ENABLED=false`` those agents run
   against mock providers and :func:`services.budget.authorize_paid_call`
   refuses every real call anyway)
5. daily production limit (``max_daily_production_jobs``)
6. entity checks: the entity exists and is in the agent's stage status,
   the rights of the source material are still valid, the quality gate is
   passed before publishing, and the target channel may publish.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents.base import CostKind
from agents.registry import AgentSpec, all_specs
from core.config import Settings
from core.enums import (
    AgentRunStatus,
    ChannelAuthStatus,
    MaterialStatus,
    VideoStatus,
)
from models.channels import Channel
from models.control import AgentRun
from models.production import Clip, GameplayFile, QualityCheck, Scene, Variant
from services import agent_control
from services.budget import BudgetLevel, budget_status
from services.controls import effective_controls, get_operations

#: Sub-steps inside one status: (SQL filter, check on a loaded entity). ``EDITING`` is
#: shared by the Creative Director (no concept yet) and Script & Hook (concept chosen).
STEPS: dict[str, tuple[Any, Any]] = {
    "concept": (Variant.video_format.is_(None), lambda v: v.video_format is None),
    "script": (Variant.video_format.is_not(None), lambda v: v.video_format is not None),
}


def step_filter(spec: AgentSpec) -> list[Any]:
    """Extra WHERE clauses that select the entities of an agent's sub-step."""
    if spec.stage is None or spec.stage.step is None:
        return []
    return [STEPS[spec.stage.step][0]]


ENTITY_MODELS: dict[str, type[GameplayFile] | type[Variant]] = {
    "gameplay_files": GameplayFile,
    "variants": Variant,
}

#: Variant statuses from which on the quality gate must have been passed.
_NEEDS_QUALITY = {VideoStatus.READY_TO_PUBLISH, VideoStatus.SCHEDULED}


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    code: str
    reason: str

    @classmethod
    def ok(cls) -> GateResult:
        return cls(True, "ok", "ok")

    @classmethod
    def deny(cls, code: str, reason: str) -> GateResult:
        return cls(False, code, reason)


def load_entity(
    session: Session, entity_type: str, entity_id: int
) -> GameplayFile | Variant | None:
    if entity_type == "gameplay_files":
        return session.get(GameplayFile, entity_id)
    if entity_type == "variants":
        return session.get(Variant, entity_id)
    return None


def production_runs_today(session: Session, now: datetime | None = None) -> int:
    """Runs of production agents started today (UTC) that did not get skipped."""
    names = [s.name for s in all_specs() if s.production]
    start = (now or datetime.now(UTC)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        session.scalar(
            select(func.count(AgentRun.id)).where(
                AgentRun.agent_name.in_(names),
                AgentRun.started_at >= start,
                AgentRun.status != AgentRunStatus.SKIPPED,
            )
        )
        or 0
    )


def rights_check(
    session: Session, gameplay_file: GameplayFile, today: date | None = None
) -> str | None:
    """Return ``None`` if the material may be used, else the first failed criterion.

    Uses the full rights evaluation of :mod:`services.rights`, so a license
    that expired or a source that was blocked since approval stops all work.
    """
    from services.rights import evaluate

    result = evaluate(session, gameplay_file, today)
    if result.approved:
        return None
    failed = next(c for c in result.checks if c.outcome != "ok")
    return f"{failed.label}: {failed.reason}"


def source_file(session: Session, variant: Variant) -> GameplayFile | None:
    return session.scalar(
        select(GameplayFile)
        .join(Scene, Scene.gameplay_file_id == GameplayFile.id)
        .join(Clip, Clip.scene_id == Scene.id)
        .where(Clip.id == variant.clip_id)
    )


def _quality_check(session: Session, settings: Settings, variant: Variant) -> str | None:
    latest = session.scalar(
        select(QualityCheck)
        .where(QualityCheck.variant_id == variant.id)
        .order_by(QualityCheck.checked_at.desc(), QualityCheck.id.desc())
        .limit(1)
    )
    if latest is None or not latest.passed:
        return "quality check not passed"
    minimum = get_operations(session).min_quality_score
    score = variant.quality_score if variant.quality_score is not None else latest.score
    if score is None or score < minimum:
        return f"quality score {score} below minimum {minimum}"
    return None


def _channel_check(session: Session, settings: Settings, variant: Variant) -> str | None:
    channel = session.get(Channel, variant.channel_id)
    if channel is None:
        return "channel missing"
    if channel.is_paused or channel.platform.is_paused:
        return "channel or platform paused"
    if settings.publishing_mode == "live":
        if not effective_controls(session, settings).publishing_allowed:
            return "live publishing not allowed (auto-publish switches)"
        if channel.auth_status != ChannelAuthStatus.AUTHORIZED:
            return f"channel not authorized ({channel.auth_status.value})"
    return None


def check_entity(
    session: Session, settings: Settings, spec: AgentSpec, payload: dict[str, Any]
) -> GateResult:
    """Entity-related gates for an agent that owns a pipeline stage."""
    if spec.stage is None or payload.get("sweep") is True:
        return GateResult.ok()  # sweeps (e.g. expiry monitoring) work without one entity
    entity_id = payload.get("entity_id")
    if payload.get("entity_type") != spec.stage.entity_type or not isinstance(entity_id, int):
        return GateResult.deny("bad_payload", "payload must name the stage entity")
    entity = load_entity(session, spec.stage.entity_type, entity_id)
    if entity is None:
        return GateResult.deny("entity_missing", f"{spec.stage.entity_type}#{entity_id} not found")
    if entity.status.value != spec.stage.status:
        return GateResult.deny(
            "wrong_status",
            f"{spec.stage.entity_type}#{entity_id} is {entity.status.value}, "
            f"agent works on {spec.stage.status}",
        )
    if spec.stage.step is not None and not STEPS[spec.stage.step][1](entity):
        return GateResult.deny(
            "wrong_step", f"{spec.stage.entity_type}#{entity_id} is not at step {spec.stage.step}"
        )
    if isinstance(entity, GameplayFile):
        # Scout and rights agent decide about rights themselves; later stages re-check.
        if entity.status not in (MaterialStatus.DISCOVERED, MaterialStatus.RIGHTS_PENDING):
            problem = rights_check(session, entity)
            if problem:
                return GateResult.deny("rights", problem)
        return GateResult.ok()
    source = source_file(session, entity)
    if source is None or source.status != MaterialStatus.ANALYZED:
        return GateResult.deny("rights", "source material has not passed rights and analysis")
    problem = rights_check(session, source)
    if problem:
        return GateResult.deny("rights", problem)
    if entity.status in _NEEDS_QUALITY:
        problem = _quality_check(session, settings, entity)
        if problem:
            return GateResult.deny("quality", problem)
    if entity.status == VideoStatus.SCHEDULED:
        problem = _channel_check(session, settings, entity)
        if problem:
            return GateResult.deny("channel", problem)
    return GateResult.ok()


def check(
    session: Session,
    settings: Settings,
    spec: AgentSpec,
    payload: dict[str, Any],
    *,
    priority: bool = False,
    count_daily_limit: bool = True,
) -> GateResult:
    """Run all gates for one agent job."""
    controls = effective_controls(session, settings)
    if controls.emergency_stop:
        return GateResult.deny("emergency_stop", "emergency stop is active")
    if not spec.implemented:
        return GateResult.deny("not_implemented", f"agent is planned for phase {spec.phase}")
    if not agent_control.is_enabled(session, spec.name):
        return GateResult.deny("agent_paused", "agent is paused by the operator")
    if spec.cost_kind == CostKind.PAID and controls.paid_api_calls_enabled:
        level = budget_status(session, settings).level
        if level == BudgetLevel.STOP_PAID:
            return GateResult.deny("budget_stop", "budget exhausted - paid agents stopped")
        if level == BudgetLevel.PRIORITY_ONLY and not priority:
            return GateResult.deny("budget_priority_only", "budget level: priority jobs only")
    if spec.production and count_daily_limit:
        limit = get_operations(session).max_daily_production_jobs
        if production_runs_today(session) >= limit:
            return GateResult.deny("daily_limit", f"daily production limit of {limit} reached")
    return check_entity(session, settings, spec, payload)
