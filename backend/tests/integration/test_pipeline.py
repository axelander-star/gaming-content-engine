"""Phase 4 acceptance: a full pipeline run with dummy agents up to READY_TO_PUBLISH."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from typing import Any

import pytest
from sqlalchemy.orm import Session

from agents import registry
from agents.base import Agent, AgentContext, AgentResult
from agents.master import MasterOrchestratorAgent
from core.config import get_settings
from core.enums import AgentRunStatus
from core.enums import MaterialStatus as M
from core.enums import VideoStatus as V
from models import QualityCheck
from services import agent_control, gates, orchestrator, workflow
from services.controls import update_runtime_controls
from tests.factories import Chain, build_chain

pytestmark = pytest.mark.integration

#: Dummy behaviour per agent: the statuses it moves its entity through.
STEPS: dict[str, list[Any]] = {
    "material_scout": [M.RIGHTS_PENDING],
    "rights_license": [M.RIGHTS_APPROVED],
    "gameplay_analysis": [M.ANALYZED],
    "clip_production": [V.EDITING],
    "creative_director": [V.LOCALIZATION],
    "localization": [V.VOICEOVER],
    "voice": [V.SUBTITLES],
    "subtitle": [V.QUALITY_CHECK],
    "quality_control": [V.QUALITY_APPROVED, V.READY_TO_PUBLISH],
}


def dummy(name: str) -> Callable[[], Agent]:
    class Dummy(Agent):
        def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
            entity = gates.load_entity(ctx.session, payload["entity_type"], payload["entity_id"])
            assert entity is not None
            if name == "quality_control":
                ctx.session.add(QualityCheck(variant_id=entity.id, passed=True, score=0.9))
                entity.quality_score = 0.9  # type: ignore[union-attr]
            for target in STEPS[name]:
                workflow.transition(ctx.session, entity, target, actor=name)
            ctx.decide("dummy_step", {"to": entity.status.value}, f"{name} test step")
            return AgentResult(output={"status": entity.status.value})

    return Dummy


def _master_into(queued: list[tuple[str, dict[str, Any]]]) -> Callable[[], Agent]:
    def submit(name: str, payload: dict[str, Any]) -> None:
        queued.append((name, payload))

    return lambda: MasterOrchestratorAgent(submit=submit)


def run_ticks(db: Session, ticks: int) -> list[str]:
    """Run master ticks and execute every dispatched job; return agents that ran."""
    executed: list[str] = []
    for _ in range(ticks):
        queued: list[tuple[str, dict[str, Any]]] = []

        with registry.override("master", _master_into(queued)):
            orchestrator.run_agent(db, get_settings(), "master", {})
        if not queued:
            break
        for name, payload in queued:
            run = orchestrator.run_agent(db, get_settings(), name, payload)
            assert run.status == AgentRunStatus.SUCCEEDED, (name, run.output, run.error)
            executed.append(name)
    return executed


@pytest.fixture
def dummies() -> Any:
    with ExitStack() as stack:
        for name in STEPS:
            stack.enter_context(registry.override(name, dummy(name)))
        yield


def test_pipeline_runs_to_ready_to_publish(db: Session, dummies: None) -> None:
    chain: Chain = build_chain(db)
    executed = run_ticks(db, 15)
    assert chain.gameplay_file.status == M.ANALYZED
    assert chain.variant.status == V.READY_TO_PUBLISH
    # Material first (rights gate), then every video stage exactly once, in order.
    assert executed == list(STEPS)


def test_paused_agent_blocks_pipeline(db: Session, dummies: None) -> None:
    chain = build_chain(db)
    agent_control.set_enabled(db, "voice", False, None)
    run_ticks(db, 15)
    assert chain.variant.status == V.VOICEOVER
    agent_control.set_enabled(db, "voice", True, None)
    run_ticks(db, 15)
    assert chain.variant.status == V.READY_TO_PUBLISH


def test_emergency_stop_halts_pipeline(db: Session, dummies: None) -> None:
    chain = build_chain(db)
    update_runtime_controls(db, None, emergency_stop=True)
    assert run_ticks(db, 5) == []
    assert chain.gameplay_file.status == M.DISCOVERED
