"""Phase 4: agents API (status, pause/resume, runs, decisions, manual run)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy.orm import Session

from core.enums import AgentRunStatus, UserRole
from models import AgentDecision, AgentRun, User
from services.controls import update_runtime_controls
from services.queue import get_queue
from tests.conftest import login

pytestmark = pytest.mark.integration


def agents_by_name(api: TestClient) -> dict[str, dict[str, object]]:
    r = api.get("/api/agents")
    assert r.status_code == 200, r.text
    return {a["name"]: a for a in r.json()}


def test_list_agents_shows_all_23(api: TestClient, make_user: Callable[..., User]) -> None:
    make_user(role=UserRole.VIEWER, email="v@example.com")
    login(api, "v@example.com")
    agents = agents_by_name(api)
    assert len(agents) == 23
    assert agents["master"]["status"] == "ready" and agents["master"]["can_run_manually"]
    assert all(a["status"] != "not_available" for a in agents.values())  # all 23 built
    assert agents["analytics"]["phase"] == 14


def test_status_reflects_runs_and_emergency_stop(
    api: TestClient, db: Session, make_user: Callable[..., User]
) -> None:
    make_user()
    login(api, "admin@example.com")
    db.add(AgentRun(agent_name="budget_cost", status=AgentRunStatus.FAILED, error="boom"))
    db.add(AgentRun(agent_name="master", status=AgentRunStatus.RUNNING, input={"x": 1}))
    db.flush()
    agents = agents_by_name(api)
    budget = agents["budget_cost"]
    assert budget["status"] == "error" and budget["last_error"] == "boom"
    assert agents["master"]["status"] == "running" and agents["master"]["current_task"] == {"x": 1}
    update_runtime_controls(db, None, emergency_stop=True)
    assert agents_by_name(api)["master"]["status"] == "stopped"


def test_pause_by_operator_resume_by_admin(api: TestClient, make_user: Callable[..., User]) -> None:
    make_user(role=UserRole.OPERATOR, email="op@example.com")
    make_user()
    headers = login(api, "op@example.com")
    assert api.post("/api/agents/master/pause", headers=headers).status_code == 204
    assert agents_by_name(api)["master"]["status"] == "paused"
    assert api.post("/api/agents/master/resume", headers=headers).status_code == 403
    assert api.post("/api/agents/nope/pause", headers=headers).status_code == 404
    assert api.post("/api/agents/master/pause").status_code == 403  # CSRF
    headers = login(api, "admin@example.com")
    assert api.post("/api/agents/master/resume", headers=headers).status_code == 204
    assert agents_by_name(api)["master"]["enabled"] is True


def test_manual_run_queues_master(
    api: TestClient, db: Session, redis_client: Redis, make_user: Callable[..., User]
) -> None:
    make_user()
    headers = login(api, "admin@example.com")
    r = api.post("/api/agents/master/run", headers=headers)
    assert r.status_code == 202, r.text
    assert get_queue("high", redis_client).count == 1
    assert api.post("/api/agents/voice/run", headers=headers).status_code == 400
    api.post("/api/agents/master/pause", headers=headers)
    assert api.post("/api/agents/master/run", headers=headers).status_code == 409
    api.post("/api/agents/master/resume", headers=headers)
    update_runtime_controls(db, None, emergency_stop=True)
    assert api.post("/api/agents/master/run", headers=headers).status_code == 409


def test_manual_run_requires_admin(api: TestClient, make_user: Callable[..., User]) -> None:
    make_user(role=UserRole.OPERATOR, email="op@example.com")
    headers = login(api, "op@example.com")
    assert api.post("/api/agents/master/run", headers=headers).status_code == 403


def test_runs_decisions_and_budget(
    api: TestClient, db: Session, make_user: Callable[..., User]
) -> None:
    make_user()
    login(api, "admin@example.com")
    run = AgentRun(agent_name="master", status=AgentRunStatus.SUCCEEDED, output={"dispatched": []})
    db.add(run)
    db.flush()
    db.add(AgentDecision(agent_run_id=run.id, agent_name="master", decision_type="dispatch",
                         decision={"dispatched": 0}, reasoning="nothing to do"))  # fmt: skip
    db.flush()
    runs = api.get("/api/agents/master/runs").json()
    assert runs[0]["id"] == run.id and runs[0]["status"] == "succeeded"
    decisions = api.get("/api/agents/decisions?agent=master").json()
    assert decisions[0]["reasoning"] == "nothing to do"
    assert api.get("/api/agents/nope/runs").status_code == 404
    b = api.get("/api/agents/budget").json()
    assert b["level"] == "normal" and b["paid_api_calls_enabled"] is False
