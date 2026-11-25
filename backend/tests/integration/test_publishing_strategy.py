"""Phase 11: Publishing Strategy Agent with database, master dispatch and API."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.master import MasterOrchestratorAgent
from agents.registry import override
from core.config import Settings, get_settings
from core.enums import (
    AgentRunStatus,
    MetricWindow,
    PublishingJobStatus,
    PublishingMode,
    UserRole,
    VideoStatus,
)
from models import Channel, User, Variant
from models.analytics import Metric
from models.publishing import Post, PublishingJob, StrategyVersion
from services import orchestrator, strategy
from services.controls import update_operations
from tests.conftest import login
from tests.factories import build_chain

BERLIN = ZoneInfo("Europe/Berlin")
#: Monday 16.11.2026, 08:00 in Berlin
MORNING = datetime(2026, 11, 16, 7, 0, tzinfo=UTC)


def ready_variants(
    db: Session, count: int, channel: Channel, quality: float = 0.9
) -> list[Variant]:
    out = []
    for _ in range(count):
        chain = build_chain(db)
        v = chain.variant
        v.channel_id, v.language = channel.id, channel.language
        v.status, v.quality_score = VideoStatus.READY_TO_PUBLISH, quality
        v.title, v.video_format, v.hook_type = "Titel", "epic_scene", "question"
        out.append(v)
    db.flush()
    return out


@pytest.fixture
def channel(db: Session) -> Channel:
    ch = build_chain(db).channel  # also seeds the channels
    ch.is_paused, ch.min_posts_per_day, ch.max_posts_per_day = False, 0, 4
    ch.min_interval_minutes = 90
    ch.platform.is_paused = False
    db.flush()
    return ch


def plan(db: Session, channel: Channel, now: datetime, settings: Settings | None = None) -> Any:
    run = orchestrator.run_agent(
        db,
        settings or get_settings(),
        "publishing_strategy",
        {"sweep": True, "channel_id": channel.id, "now": now.isoformat()},
    )
    assert run.status == AgentRunStatus.SUCCEEDED, (run.error, run.output)
    return run.output


def jobs(db: Session, channel: Channel, *statuses: PublishingJobStatus) -> list[PublishingJob]:
    q = select(PublishingJob).where(PublishingJob.channel_id == channel.id)
    if statuses:
        q = q.where(PublishingJob.status.in_(statuses))
    return list(db.scalars(q.order_by(PublishingJob.scheduled_for)))


def published(db: Session, channel: Channel, views: list[int], end: datetime) -> None:
    """Synthetic history: one post per day before ``end`` with 48 h metrics."""
    variants = ready_variants(db, len(views), channel)
    for i, (v, n) in enumerate(zip(variants, views, strict=True)):
        v.channel_id, v.status = channel.id, VideoStatus.PUBLISHED
        when = end - timedelta(days=len(views) - i + 2)
        job = PublishingJob(
            variant_id=v.id,
            channel_id=channel.id,
            status=PublishingJobStatus.SUCCEEDED,
            mode=PublishingMode.MOCK,
            scheduled_for=when,
            idempotency_key=f"hist-{v.id}",
        )
        db.add(job)
        db.flush()
        post = Post(
            publishing_job_id=job.id,
            variant_id=v.id,
            channel_id=channel.id,
            published_at=when,
            is_mock=True,
        )
        db.add(post)
        db.flush()
        db.add(
            Metric(
                post_id=post.id,
                measure_window=MetricWindow.H48,
                views=int(n),
                likes=int(n * 0.05),
                comments=int(n * 0.005),
            )
        )
    db.flush()


def test_first_plan_is_cautious_and_mock_only(db: Session, channel: Channel) -> None:
    ready = ready_variants(db, 5, channel)
    out = plan(db, channel, MORNING)
    version = strategy.latest_version(db, channel.id)
    assert version is not None and version.version == 1 and version.posts_per_day == 1
    assert "vorsichtiger Start" in version.reasons[0]
    planned = jobs(db, channel, PublishingJobStatus.SCHEDULED)
    assert len(planned) == 1 and len(out["planned"]) == 1, repr(out)
    job = planned[0]
    assert job.mode == PublishingMode.MOCK and job.decided_by_decision_id is not None
    assert job.scheduled_for is not None
    local = job.scheduled_for.astimezone(BERLIN)
    assert local.date() == date(2026, 11, 16) and 11 <= local.hour <= 21
    v = db.get(Variant, job.variant_id)
    assert v is not None and v.status == VideoStatus.SCHEDULED
    assert sum(1 for x in ready if x.status == VideoStatus.READY_TO_PUBLISH) == 4
    assert {h["reason"] for h in out["held"]} == {"Tagesmenge erreicht"}

    # same day again: same version, nothing new
    again = plan(db, channel, MORNING + timedelta(hours=1))
    assert again["strategy_version"] == 1 and again["planned"] == []
    assert len(jobs(db, channel, PublishingJobStatus.SCHEDULED)) == 1


def test_good_history_raises_the_amount_next_day(db: Session, channel: Channel) -> None:
    published(db, channel, [1000] * 10 + [1600] * 6, MORNING)
    ready_variants(db, 6, channel)
    plan(db, channel, MORNING - timedelta(days=4))  # an older version: 1 per day
    out = plan(db, channel, MORNING)
    assert out["strategy_version"] == 2 and out["posts_per_day"] == 2
    version = strategy.latest_version(db, channel.id)
    assert version is not None
    assert any("mehr veröffentlichen" in r for r in version.reasons)
    assert version.inputs["assessment"]["judged"] >= 6
    times = [j.scheduled_for for j in jobs(db, channel, PublishingJobStatus.SCHEDULED)]
    today = [t for t in times if t and t.astimezone(BERLIN).date() == date(2026, 11, 16)]
    assert len(today) == 2
    assert abs(today[1] - today[0]) >= timedelta(minutes=90)


def test_quality_minimum_and_rights_take_planned_posts_back(db: Session, channel: Channel) -> None:
    ready_variants(db, 3, channel)
    plan(db, channel, MORNING)
    job = jobs(db, channel, PublishingJobStatus.SCHEDULED)[0]
    update_operations(db, None, {"min_quality_score": 0.95})
    db.flush()
    out = plan(db, channel, MORNING + timedelta(hours=1))
    assert out["unscheduled"][0]["reason"].startswith("Qualitätswert")
    assert job.status == PublishingJobStatus.CANCELLED
    v = db.get(Variant, job.variant_id)
    assert v is not None and v.status == VideoStatus.READY_TO_PUBLISH
    assert out["planned"] == []  # nothing else is good enough
    assert {h["reason"] for h in out["held"]} == {"Qualitätswert unter Minimum"}


def test_paused_channel_plans_nothing(db: Session, channel: Channel) -> None:
    ready_variants(db, 2, channel)
    plan(db, channel, MORNING)
    channel.is_paused = True
    db.flush()
    out = plan(db, channel, MORNING + timedelta(hours=1))
    assert out["blocked"] == "Kanal oder Plattform pausiert"
    assert out["effective_amount"] == 0 and out["planned"] == []
    assert jobs(db, channel, PublishingJobStatus.SCHEDULED) == []

    # next day paused: amount 0; the day after resuming it starts again cautiously
    plan(db, channel, MORNING + timedelta(days=1))
    assert strategy.latest_version(db, channel.id).posts_per_day == 0  # type: ignore[union-attr]
    channel.is_paused = False
    db.flush()
    out = plan(db, channel, MORNING + timedelta(days=2))
    assert out["posts_per_day"] == 1 and len(out["planned"]) == 1


def test_live_mode_needs_an_authorized_channel(db: Session, channel: Channel) -> None:
    ready_variants(db, 2, channel)
    live = get_settings().model_copy(
        update={"publishing_mode": "live", "auto_publish_enabled": True}
    )
    out = plan(db, channel, MORNING, live)
    assert out["planned"] == [] and out["blocked"] is not None
    assert jobs(db, channel) == []


def test_unconfigured_channel_gets_zero(db: Session, channel: Channel) -> None:
    channel.max_posts_per_day = 0
    ready_variants(db, 2, channel)
    out = plan(db, channel, MORNING)
    assert out["posts_per_day"] == 0 and out["planned"] == []


def test_master_dispatches_once_per_channel_and_interval(db: Session, channel: Channel) -> None:
    ready_variants(db, 2, channel)
    queued: list[tuple[str, dict[str, Any]]] = []

    def submit(name: str, payload: dict[str, Any]) -> None:
        queued.append((name, payload))

    with override("master", lambda: MasterOrchestratorAgent(submit=submit)):
        orchestrator.run_agent(db, get_settings(), "master", {})
    mine = [p for n, p in queued if n == "publishing_strategy"]
    assert mine == [{"sweep": True, "channel_id": channel.id}]
    orchestrator.run_agent(db, get_settings(), "publishing_strategy", mine[0])
    queued.clear()
    with override("master", lambda: MasterOrchestratorAgent(submit=submit)):
        orchestrator.run_agent(db, get_settings(), "master", {})
    assert [p for n, p in queued if n == "publishing_strategy"] == []
    assert orchestrator.job_key("publishing_strategy", mine[0]).endswith(f"channel-{channel.id}")


class _FrozenDatetime(datetime):
    """``datetime.now`` pinned to MORNING, so the plan's job window does not age out."""

    @classmethod
    def now(cls, tz: Any = None) -> Any:
        return MORNING if tz is None else MORNING.astimezone(tz)


def test_api_shows_plan_and_admin_can_roll_back(
    db: Session,
    channel: Channel,
    api: TestClient,
    make_user: Callable[..., User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the API lists jobs from "now - 1 day"; the scenario uses a fixed date
    monkeypatch.setattr("api.publishing.datetime", _FrozenDatetime)
    published(db, channel, [1000] * 10 + [1600] * 6, MORNING)
    ready_variants(db, 4, channel)
    plan(db, channel, MORNING - timedelta(days=4))
    plan(db, channel, MORNING)  # version 2: two per day
    # the plan page shows jobs from the last day on; keep the test independent of today
    for job in db.scalars(select(PublishingJob)):
        assert job.scheduled_for is not None
        job.scheduled_for += datetime.now(UTC) - MORNING
    db.commit()

    make_user("viewer@example.com", UserRole.VIEWER)
    h = login(api, "viewer@example.com")
    rows = api.get("/api/publishing/plan", headers=h).json()
    row = next(r for r in rows if r["channel_id"] == channel.id)
    assert row["current"]["version"] == 2 and row["current"]["posts_per_day"] == 2
    assert row["timezone"] == "Europe/Berlin" and row["window"] == [11, 21]
    assert [v["version"] for v in row["history"]] == [2, 1]
    assert any(j["status"] == "scheduled" and j["mode"] == "mock" for j in row["jobs"])
    denied = api.post(f"/api/publishing/channels/{channel.id}/rollback", json={"version": 1},
                      headers=h)  # fmt: skip
    assert denied.status_code == 403

    make_user("admin2@example.com", UserRole.ADMIN)
    ha = login(api, "admin2@example.com")
    res = api.post(
        f"/api/publishing/channels/{channel.id}/rollback", json={"version": 1}, headers=ha
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["version"] == 3 and body["posts_per_day"] == 1 and body["rolled_back_to"] == 1
    assert body["created_by"].startswith("user:")
    missing = api.post(
        f"/api/publishing/channels/{channel.id}/rollback", json={"version": 99}, headers=ha
    )
    assert missing.status_code == 404
    db.expire_all()
    rolled = db.scalar(
        select(StrategyVersion).where(
            StrategyVersion.channel_id == channel.id, StrategyVersion.version == 3
        )
    )
    assert rolled is not None
