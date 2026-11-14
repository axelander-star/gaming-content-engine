"""Agent 1: Master Orchestrator (PROJECT_SPEC section 6).

One *tick* of the master:

1. Return failed material and videos to the status they failed in, if the
   retry limit is not reached and the back-off time has passed.
2. For every pipeline stage, find entities waiting in that stage's status and
   hand each one to the responsible agent through the queue, after checking
   the gates (emergency stop, pause, budget, rights, quality, channel).
3. Respect the daily production limit from the operator settings.
4. Record what was dispatched, retried and blocked, with reasons.

The master never does production work itself and never calls agents
directly; it only puts jobs into the queue.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from agents.base import Agent, AgentContext, AgentResult
from agents.registry import AgentSpec, stage_specs
from models.production import GameplayFile, Variant
from services import agent_control, gates, workflow
from services.controls import effective_controls, get_operations

Submit = Callable[[str, dict[str, Any]], object]


def _default_submit(agent_name: str, payload: dict[str, Any]) -> object:
    from services.orchestrator import submit

    return submit(agent_name, payload)


class MasterOrchestratorAgent(Agent):
    def __init__(self, submit: Submit | None = None) -> None:
        self._submit = submit or _default_submit

    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        if effective_controls(ctx.session, ctx.settings).emergency_stop:
            return AgentResult(output={"skipped": "emergency_stop"})
        retried = self._retry_failed(ctx)
        dispatched, blocked, waiting = self._dispatch(ctx)
        output = {
            "dispatched": dispatched,
            "retried": retried,
            "blocked": blocked,
            "waiting": waiting,
        }
        if dispatched or retried or blocked:
            ctx.decide(
                "dispatch",
                {"dispatched": len(dispatched), "retried": len(retried), "blocked": len(blocked)},
                self._reasoning(dispatched, retried, blocked, waiting),
                inputs={"waiting": waiting},
            )
        return AgentResult(output=output)

    # --- retries ------------------------------------------------------------

    def _retry_failed(self, ctx: AgentContext) -> list[dict[str, Any]]:
        s = ctx.settings
        now = datetime.now(UTC)
        retried: list[dict[str, Any]] = []
        for entity_type, model in gates.ENTITY_MODELS.items():
            rows: Sequence[GameplayFile | Variant] = ctx.session.scalars(
                select(model)
                .where(
                    model.status == "FAILED",
                    model.last_good_status.is_not(None),
                    model.retry_count < s.agent_max_retries,
                )
                .order_by(model.updated_at)
                .limit(s.master_batch_size)
            ).all()  # type: ignore[assignment]
            for entity in rows:
                delay = timedelta(seconds=s.agent_retry_base_delay_s * 2**entity.retry_count)
                if entity.updated_at and entity.updated_at + delay > now:
                    continue
                step, error = entity.failed_step, entity.error_message
                workflow.retry(ctx.session, entity, actor="master", max_retries=s.agent_max_retries)
                info = {
                    "entity_type": entity_type,
                    "entity_id": entity.id,
                    "status": entity.status.value,
                    "attempt": entity.retry_count,
                }
                retried.append(info)
                ctx.decide(
                    "retry",
                    info,
                    f"Failed in step '{step}' ({(error or '')[:200]}); retry "
                    f"{entity.retry_count} of {s.agent_max_retries}.",
                    entity_type=entity_type,
                    entity_id=entity.id,
                )
        ctx.session.flush()
        return retried

    # --- dispatch -----------------------------------------------------------

    def _dispatch(
        self, ctx: AgentContext
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        session, settings = ctx.session, ctx.settings
        limit = get_operations(session).max_daily_production_jobs
        capacity = max(0, limit - gates.production_runs_today(session))
        dispatched: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        waiting: dict[str, Any] = {}
        for spec in stage_specs():
            assert spec.stage is not None
            model = gates.ENTITY_MODELS[spec.stage.entity_type]
            where = [model.status == spec.stage.status, *gates.step_filter(spec)]
            count = session.scalar(select(func.count(model.id)).where(*where))
            if not count:
                continue
            reason = self._stage_unavailable(ctx, spec)
            if reason:
                waiting[spec.name] = {"count": count, "reason": reason}
                continue
            ids = session.scalars(
                select(model.id)
                .where(*where)
                .order_by(model.updated_at, model.id)
                .limit(settings.master_batch_size)
            ).all()
            for entity_id in ids:
                if spec.production and capacity <= 0:
                    waiting[spec.name] = {"count": count, "reason": "daily_limit"}
                    break
                payload = {
                    "entity_type": spec.stage.entity_type,
                    "entity_id": entity_id,
                    "status": spec.stage.status,
                }
                gate = gates.check(session, settings, spec, payload, count_daily_limit=False)
                if not gate.allowed:
                    blocked.append({**payload, "agent": spec.name, "gate": gate.code,
                                    "reason": gate.reason})  # fmt: skip
                    continue
                self._submit(spec.name, payload)
                dispatched.append({**payload, "agent": spec.name})
                if spec.production:
                    capacity -= 1
        return dispatched, blocked, waiting

    @staticmethod
    def _stage_unavailable(ctx: AgentContext, spec: AgentSpec) -> str | None:
        if not spec.implemented:
            return f"waiting_for_phase_{spec.phase}"
        if not agent_control.is_enabled(ctx.session, spec.name):
            return "agent_paused"
        return None

    @staticmethod
    def _reasoning(
        dispatched: list[dict[str, Any]],
        retried: list[dict[str, Any]],
        blocked: list[dict[str, Any]],
        waiting: dict[str, Any],
    ) -> str:
        parts = [f"{len(dispatched)} job(s) dispatched", f"{len(retried)} retried"]
        if blocked:
            reasons = sorted({b["gate"] for b in blocked})
            parts.append(f"{len(blocked)} blocked by gates ({', '.join(reasons)})")
        if waiting:
            parts.append("waiting: " + ", ".join(f"{k}={v['reason']}" for k, v in waiting.items()))
        return "; ".join(parts) + "."
