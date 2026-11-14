"""Hand out agent jobs and execute them with protocol, gates and error handling.

* :func:`submit` puts one agent job into the Redis queue under a deterministic
  job id, so the same job cannot be queued twice.
* :func:`run_agent` is what the worker executes: it re-checks the gates,
  writes an ``agent_runs`` row, runs the agent and books the result. Errors
  never crash the worker: the run is marked failed and the entity moves to
  ``FAILED`` (with the step it failed in) so the master can retry it later.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from redis import Redis
from rq.job import Job
from sqlalchemy.orm import Session

from agents.base import AgentContext, AgentSkipError, PermanentError
from agents.registry import AgentSpec, get_spec
from core.config import Settings, get_settings
from core.enums import AgentRunStatus
from database.session import get_sessionmaker
from models.control import AgentRun
from services import gates, workflow
from services.queue import enqueue_unique

log = logging.getLogger("orchestrator")


class UnknownAgentError(LookupError):
    pass


def _spec(agent_name: str) -> AgentSpec:
    spec = get_spec(agent_name)
    if spec is None:
        raise UnknownAgentError(agent_name)
    return spec


def job_key(agent_name: str, payload: dict[str, Any]) -> str:
    """Deterministic id: one queued job per agent, entity and entity status."""
    if payload.get("sweep"):
        return f"agent-{agent_name}-sweep"
    if "entity_type" in payload and "entity_id" in payload:
        status = payload.get("status", "")
        return f"agent-{agent_name}-{payload['entity_type']}-{payload['entity_id']}-{status}"
    return f"agent-{agent_name}"


def queue_for(spec: AgentSpec, priority: bool) -> str:
    if priority or spec.name in {"master", "budget_cost"}:
        return "high"
    return "low" if spec.stage is None else "default"


def submit(
    agent_name: str,
    payload: dict[str, Any],
    *,
    priority: bool = False,
    connection: Redis | None = None,
) -> Job:
    spec = _spec(agent_name)
    options: dict[str, Any] = {}
    if spec.production:  # analysis and rendering take longer than a normal job
        options["job_timeout"] = get_settings().production_job_timeout_s
    return enqueue_unique(
        run_agent_job,
        job_key(agent_name, payload),
        agent_name,
        payload,
        priority,
        queue=queue_for(spec, priority),
        connection=connection,
        **options,
    )


def run_agent_job(
    agent_name: str, payload: dict[str, Any], priority: bool = False
) -> dict[str, Any]:
    """Entry point for the RQ worker (own session per job)."""
    with get_sessionmaker()() as session:
        run = run_agent(session, get_settings(), agent_name, payload, priority=priority)
        return {"run_id": run.id, "status": run.status.value}


def _finish(session: Session, run: AgentRun, status: AgentRunStatus, **fields: Any) -> AgentRun:
    run.status = status
    run.finished_at = datetime.now(UTC)
    for key, value in fields.items():
        setattr(run, key, value)
    session.commit()
    return run


def _current_job_id() -> str | None:
    try:
        from rq import get_current_job

        job = get_current_job()
    except Exception:  # pragma: no cover - outside a worker
        return None
    return job.id if job is not None else None


def run_agent(
    session: Session,
    settings: Settings,
    agent_name: str,
    payload: dict[str, Any],
    *,
    priority: bool = False,
) -> AgentRun:
    """Execute one agent job and return its ``agent_runs`` row (already committed)."""
    spec = _spec(agent_name)
    run = AgentRun(agent_name=agent_name, input=payload, queue_job_id=_current_job_id())
    gate = gates.check(session, settings, spec, payload, priority=priority)
    session.add(run)
    session.flush()
    if not gate.allowed:
        log.info("agent skipped", extra={"agent": agent_name, "gate": gate.code})
        return _finish(
            session,
            run,
            AgentRunStatus.SKIPPED,
            output={"gate": gate.code, "reason": gate.reason},
        )
    session.commit()  # the run is visible in the dashboard while the agent works

    assert spec.factory is not None  # guaranteed by the gate
    ctx = AgentContext(session=session, settings=settings, run=run, agent_name=agent_name)
    try:
        result = spec.factory().run(ctx, payload)
    except Exception as exc:  # an agent error must not kill the worker
        session.rollback()
        error = f"{type(exc).__name__}: {exc}"
        log.warning("agent failed", extra={"agent": agent_name, "error": error})
        if isinstance(exc, AgentSkipError):
            return _finish(
                session, run, AgentRunStatus.SKIPPED, error=error[:4000], output={"gate": exc.gate}
            )
        _fail_entity(
            session,
            spec,
            payload,
            error,
            permanent_after=settings.agent_max_retries if isinstance(exc, PermanentError) else None,
        )
        return _finish(session, run, AgentRunStatus.FAILED, error=error[:4000], output={})
    if not result.ok:
        _fail_entity(session, spec, payload, result.message or "agent reported failure")
        return _finish(
            session, run, AgentRunStatus.FAILED, error=result.message, output=result.output
        )
    return _finish(session, run, AgentRunStatus.SUCCEEDED, output=result.output)


def _fail_entity(
    session: Session,
    spec: AgentSpec,
    payload: dict[str, Any],
    error: str,
    permanent_after: int | None = None,
) -> None:
    """Move the stage entity to FAILED if it is still in the agent's status.

    ``permanent_after`` marks the retry budget as used up, so the master does not
    retry an input that can never succeed."""
    if spec.stage is None:
        return
    entity_id = payload.get("entity_id")
    if not isinstance(entity_id, int):
        return
    entity = gates.load_entity(session, spec.stage.entity_type, entity_id)
    if entity is not None and entity.status.value == spec.stage.status:
        workflow.mark_failed(session, entity, spec.name, error, actor=spec.name)
        if permanent_after is not None:
            entity.retry_count = max(entity.retry_count, permanent_after)
