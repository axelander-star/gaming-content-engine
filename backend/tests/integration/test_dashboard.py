"""Start page of the dashboard: GET /api/overview/dashboard."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from core.enums import ChannelAuthStatus, PublishingJobStatus, UserRole
from models import Post, PublishingJob
from models.access import User
from services import workflow
from services.seed import seed_base_data
from tests.conftest import login
from tests.factories import build_chain

pytestmark = pytest.mark.integration

MakeUser = Callable[..., User]


def _viewer(api: TestClient, make_user: MakeUser) -> None:
    make_user(role=UserRole.VIEWER, email="viewer@example.com")
    login(api, "viewer@example.com")


def test_dashboard_requires_login(api: TestClient) -> None:
    assert api.get("/api/overview/dashboard").status_code == 401


def test_empty_dashboard(api: TestClient, make_user: MakeUser, db: Session) -> None:
    seed_base_data(db)
    _viewer(api, make_user)
    r = api.get("/api/overview/dashboard")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["videos_total"] == 0
    assert [s["key"] for s in data["states"]] == [
        "draft",
        "in_progress",
        "ready",
        "scheduled",
        "uploading",
        "published",
        "failed",
    ]
    tiles = {t["code"]: t for t in data["platforms"]}
    assert list(tiles) == ["youtube", "twitch", "instagram", "tiktok"]
    assert tiles["twitch"]["can_publish"] is False
    assert "keine Upload" in tiles["twitch"]["note"]
    assert all(t["can_publish"] for c, t in tiles.items() if c != "twitch")
    assert tiles["youtube"]["connection"] == "not_connected"
    assert tiles["youtube"]["channels"] == 0  # the seed channels are only placeholders
    assert data["recent_posts"] == []
    assert data["failures"] == []
    assert data["controls"]["publishing_allowed"] is False


def test_dashboard_counts_states_posts_and_failures(
    api: TestClient, make_user: MakeUser, db: Session
) -> None:
    chain = build_chain(db)
    chain.channel.auth_status = ChannelAuthStatus.CONNECTED_RESTRICTED
    now = datetime.now(UTC)
    job = PublishingJob(
        variant_id=chain.variant.id,
        channel_id=chain.channel.id,
        status=PublishingJobStatus.SUCCEEDED,
        idempotency_key="dash-ok",
    )
    failed_job = PublishingJob(
        variant_id=chain.variant.id,
        channel_id=chain.channel.id,
        status=PublishingJobStatus.FAILED,
        idempotency_key="dash-failed",
        last_error="quota exceeded",
    )
    running = PublishingJob(
        variant_id=chain.variant.id,
        channel_id=chain.channel.id,
        status=PublishingJobStatus.RUNNING,
        idempotency_key="dash-running",
    )
    db.add_all([job, failed_job, running])
    db.flush()
    db.add(
        Post(
            publishing_job_id=job.id,
            variant_id=chain.variant.id,
            channel_id=chain.channel.id,
            published_at=now - timedelta(minutes=5),
            url="https://example.invalid/mock",
            is_mock=True,
        )
    )
    workflow.mark_failed(db, chain.variant, "editing", "ffmpeg crashed", actor="test")
    db.flush()
    _viewer(api, make_user)

    data = api.get("/api/overview/dashboard").json()
    states = {s["key"]: s["count"] for s in data["states"]}
    assert states["failed"] == 1
    assert states["uploading"] == 1
    assert data["videos_total"] == 1
    assert data["failed"] == 1

    tile = next(t for t in data["platforms"] if t["code"] == chain.channel.platform.code.value)
    assert tile["connection"] == "restricted"
    assert tile["channels_connected"] == 1
    assert tile["test_posts"] == 1  # mock posts are counted separately
    assert tile["published"] == 0
    assert tile["failed_jobs"] == 1
    assert tile["open_jobs"] == 1

    assert len(data["recent_posts"]) == 1
    post = data["recent_posts"][0]
    assert post["is_mock"] is True
    assert post["content_project"] == "Gaming"

    errors = {f["kind"]: f for f in data["failures"]}
    assert errors["publishing"]["error"] == "quota exceeded"
    assert errors["video"]["error"] == "ffmpeg crashed"

    actions = [a["action"] for a in data["activity"]]
    assert "failed" in actions


def test_failed_logins_are_not_shown_as_activity(
    api: TestClient, make_user: MakeUser, db: Session
) -> None:
    seed_base_data(db)
    make_user(role=UserRole.VIEWER, email="viewer@example.com")
    api.post("/api/auth/login", json={"email": "viewer@example.com", "password": "wrong"})
    login(api, "viewer@example.com")
    data = api.get("/api/overview/dashboard").json()
    assert all(a["action"] != "auth.login_failed" for a in data["activity"])
