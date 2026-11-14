"""Health endpoints and the Redis job queue."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from rq import SimpleWorker
from sqlalchemy.engine import Engine

from app.main import create_app
from services.queue import enqueue_unique, get_queue, get_redis
from workflows.jobs import heartbeat

pytestmark = pytest.mark.integration


@pytest.fixture
def client(engine: Engine) -> TestClient:
    return TestClient(create_app())


def test_liveness(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readiness_ok(client: TestClient, redis_client: Redis) -> None:
    r = client.get("/api/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": True, "redis": True}


def test_readiness_degraded_when_redis_down(client: TestClient) -> None:
    app = client.app
    broken = Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2)
    app.dependency_overrides[get_redis] = lambda: broken  # type: ignore[attr-defined]
    r = client.get("/api/health/ready")
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "database": True, "redis": False}


def test_openapi_available_outside_production(client: TestClient) -> None:
    assert client.get("/api/openapi.json").status_code == 200


def test_unknown_queue_rejected(redis_client: Redis) -> None:
    with pytest.raises(ValueError, match="Unknown queue"):
        get_queue("urgent", redis_client)


def test_enqueue_unique_is_idempotent(redis_client: Redis) -> None:
    j1 = enqueue_unique(heartbeat, "heartbeat:test", connection=redis_client)
    j2 = enqueue_unique(heartbeat, "heartbeat:test", connection=redis_client)
    assert j1.id == j2.id
    assert get_queue("default", redis_client).count == 1


def test_worker_executes_job(engine: Engine, redis_client: Redis) -> None:
    job = enqueue_unique(heartbeat, "heartbeat:run", connection=redis_client)
    queue = get_queue("default", redis_client)
    SimpleWorker([queue], connection=redis_client).work(burst=True)
    job.refresh()
    assert job.get_status() == "finished"
    result = job.return_value()
    assert result is not None
    assert result["ok"] is True


def test_job_id_is_normalized() -> None:
    from services.queue import normalize_job_id

    assert normalize_job_id("variant:12/publish") == "variant-12-publish"
