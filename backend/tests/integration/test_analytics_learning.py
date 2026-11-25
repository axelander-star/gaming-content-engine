"""Phase 14: Analytics Agent, Learning Agent, cost overview and budget.

No platform is contacted: live statistics go to an ``httpx.MockTransport``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import crypto
from core.config import Settings, get_settings
from core.enums import (
    AgentRunStatus,
    ChannelAuthStatus,
    CostCategory,
    MetricWindow,
    PlatformCode,
    PublishingJobStatus,
    PublishingMode,
    UserRole,
    VideoStatus,
)
from models import Channel, ChannelCredential, LearningVersion, User, Variant
from models.analytics import AnalyticsSnapshot, Metric
from models.control import Cost
from models.publishing import Post, PublishingJob
from services import budget, costs, learning, metrics, orchestrator, platform, strategy, youtube
from services.controls import update_operations
from tests.conftest import login
from tests.factories import build_chain
from tests.integration.test_publishing import FakeGoogle

NOW = datetime.now(UTC)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(
        update={
            "media_root": str(tmp_path / "media"),
            "youtube_oauth_client_id": "cid",
            "youtube_oauth_client_secret": SecretStr("secret"),
        }
    )


def make_post(
    db: Session,
    age: timedelta,
    *,
    mock: bool = True,
    platform_code: PlatformCode | None = None,
    external_id: str | None = None,
    status: VideoStatus = VideoStatus.PUBLISHED,
) -> tuple[Post, Variant]:
    chain = build_chain(db)
    v = chain.variant
    if platform_code is not None:
        channel = db.scalar(
            select(Channel).where(
                Channel.platform.has(code=platform_code), Channel.language == v.language
            )
        )
        assert channel is not None
        v.channel_id = channel.id
    v.status, v.quality_score, v.title = status, 0.8, "Titel"
    job = PublishingJob(
        variant_id=v.id,
        channel_id=v.channel_id,
        status=PublishingJobStatus.SUCCEEDED,
        mode=PublishingMode.MOCK if mock else PublishingMode.LIVE,
        scheduled_for=NOW - age,
        idempotency_key=f"a-{v.id}-{age}",
    )
    db.add(job)
    db.flush()
    post = Post(
        publishing_job_id=job.id,
        variant_id=v.id,
        channel_id=v.channel_id,
        external_post_id=external_id or f"mock-{v.id}",
        published_at=NOW - age,
        is_mock=mock,
    )
    db.add(post)
    db.flush()
    return post, v


def run(db: Session, settings: Settings, name: str, payload: dict[str, Any] | None = None) -> Any:
    return orchestrator.run_agent(db, settings, name, payload or {"sweep": True})


# --- measurement windows ------------------------------------------------------------


def test_due_window_measures_each_window_once_and_skips_missed_ones() -> None:
    pub = NOW - timedelta(minutes=70)
    assert metrics.due_window(pub, set(), NOW) == MetricWindow.H1
    assert metrics.due_window(pub, {MetricWindow.H1}, NOW) is None
    assert metrics.due_window(NOW - timedelta(minutes=30), set(), NOW) is None
    # 25 h: the 24 h window is due; the earlier ones are history now
    assert metrics.due_window(NOW - timedelta(hours=25), {MetricWindow.H1}, NOW) == MetricWindow.H24
    # 36 h: 24 h missed by more than its tolerance (6 h), 48 h not reached yet
    assert metrics.due_window(NOW - timedelta(hours=36), set(), NOW) is None
    assert metrics.due_window(NOW - timedelta(days=7, hours=3), set(), NOW) == MetricWindow.D7
    assert metrics.due_window(NOW - timedelta(days=10), set(), NOW) is None


def test_mock_numbers_are_stable_and_grow() -> None:
    a = metrics.mock_snapshot(5, MetricWindow.H24, 0.8)
    assert a == metrics.mock_snapshot(5, MetricWindow.H24, 0.8) and a.raw == {"mock": True}
    assert (metrics.mock_snapshot(5, MetricWindow.D7, 0.8).views or 0) > (a.views or 0)


# --- Analytics Agent ----------------------------------------------------------------


def test_analytics_measures_test_posts_and_moves_the_status(
    db: Session, settings: Settings
) -> None:
    young, v1 = make_post(db, timedelta(hours=25))
    _old, v2 = make_post(db, timedelta(days=7, hours=1))
    result = run(db, settings, "analytics")
    assert result.status == AgentRunStatus.SUCCEEDED, result.error
    m1 = db.scalars(select(Metric).where(Metric.post_id == young.id)).all()
    assert [m.measure_window for m in m1] == [MetricWindow.H24] and m1[0].raw == {"mock": True}
    assert v1.status == VideoStatus.ANALYTICS_PENDING
    assert v2.status == VideoStatus.ANALYZED
    assert db.scalar(
        select(AnalyticsSnapshot).where(AnalyticsSnapshot.channel_id == young.channel_id)
    )
    # second run: nothing new to measure, no second report
    again = run(db, settings, "analytics")
    assert again.output["measured"] == 0 and again.output["reports"] == []


def test_youtube_statistics_and_analytics(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGoogle()
    monkeypatch.setattr(youtube, "TRANSPORT", httpx.MockTransport(fake))
    post, _v = make_post(
        db,
        timedelta(hours=6, minutes=10),
        mock=False,
        platform_code=PlatformCode.YOUTUBE,
        external_id="yt9",
    )
    db.add(
        ChannelCredential(
            channel_id=post.channel_id,
            provider="youtube",
            access_token_enc=crypto.encrypt(settings, "ya29"),
            expires_at=NOW + timedelta(hours=1),
            scopes=list(youtube.SCOPES),
        )
    )
    db.flush()
    fake.on(
        "GET",
        f"{youtube.API}/videos",
        httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "yt9",
                        "statistics": {"viewCount": "1200", "likeCount": "80", "commentCount": "7"},
                    }
                ]
            },
        ),
    )
    fake.on(
        "GET", metrics.YT_ANALYTICS_URL, httpx.Response(200, json={"rows": [[14.5, 61.2, 9, 3]]})
    )
    run(db, settings, "analytics")
    m = db.scalar(select(Metric).where(Metric.post_id == post.id))
    assert m is not None and m.measure_window == MetricWindow.H6
    assert (m.views, m.likes, m.comments) == (1200, 80, 7)
    assert (m.avg_view_duration_s, m.retention_pct, m.shares, m.followers_gained) == (
        14.5,
        61.2,
        9,
        3,
    )
    q = fake.sent("GET", metrics.YT_ANALYTICS_URL)[0].url.params
    assert q["filters"] == "video==yt9" and q["ids"] == "channel==MINE"


def test_missing_permission_means_no_numbers(db: Session, settings: Settings) -> None:
    post, v = make_post(
        db,
        timedelta(hours=25),
        mock=False,
        platform_code=PlatformCode.INSTAGRAM,
        external_id="1799",
    )
    db.add(
        ChannelCredential(
            channel_id=post.channel_id,
            provider="meta",
            access_token_enc=crypto.encrypt(settings, "pt"),
            scopes=["instagram_basic", "instagram_content_publish"],
        )
    )
    db.flush()
    result = run(db, settings, "analytics")
    assert str(post.id) in result.output["problems"]
    assert db.scalar(select(Metric).where(Metric.post_id == post.id)) is None
    assert v.status == VideoStatus.PUBLISHED


def test_instagram_and_facebook_insights_are_parsed(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGoogle()
    monkeypatch.setattr(platform, "TRANSPORT", httpx.MockTransport(fake))
    cred = ChannelCredential(
        channel_id=1,
        provider="meta",
        scopes=[metrics.IG_INSIGHTS_SCOPE, metrics.FB_INSIGHTS_SCOPE],
        access_token_enc=crypto.encrypt(settings, "pt"),
    )
    post = Post(external_post_id="M1", is_mock=False)
    fake.on(
        "GET",
        "https://graph.facebook.com/v25.0/M1/insights",
        httpx.Response(
            200,
            json={
                "data": [
                    {"name": "views", "values": [{"value": 900}]},
                    {"name": "likes", "values": [{"value": 40}]},
                    {"name": "ig_reels_avg_watch_time", "values": [{"value": 6500}]},
                ]
            },
        ),
    )
    snap = metrics._instagram(settings, cred, post)
    assert (snap.views, snap.likes, snap.avg_view_duration_s) == (900, 40, 6.5)
    post.external_post_id = "V1"
    fake.on(
        "GET",
        "https://graph.facebook.com/v25.0/V1/video_insights",
        httpx.Response(
            200,
            json={
                "data": [
                    {"name": "fb_reels_total_plays", "values": [{"value": 300}]},
                    {"name": "post_video_avg_time_watched", "values": [{"value": 4000}]},
                ]
            },
        ),
    )
    snap = metrics._facebook(settings, cred, post)
    assert (snap.views, snap.avg_view_duration_s) == (300, 4.0)


def test_live_mode_ignores_test_posts(db: Session) -> None:
    post, _v = make_post(db, timedelta(days=2))
    assert any(p.post_id == post.id for p in strategy.load_history(db, post.channel_id))
    assert not any(
        p.post_id == post.id for p in strategy.load_history(db, post.channel_id, include_mock=False)
    )


# --- Learning -----------------------------------------------------------------------


def sample(i: int, score: float, game: str = "A", fmt: str = "f1", day: int = 0) -> learning.Sample:
    return learning.Sample(
        i, NOW - timedelta(days=day), score, {"game": game, "format": fmt, "hook": "h"}
    )


def test_learning_needs_enough_consistent_data() -> None:
    few = [sample(i, 1.6, day=i) for i in range(5)]
    assert learning.derive(learning.group_stats(few))[0]["game"] == {}
    one_viral = [sample(i, 1.0, day=i % 4) for i in range(9)] + [sample(99, 9.0)]
    assert "A" not in learning.derive(learning.group_stats(one_viral))[0]["game"]
    same_day = [sample(i, 1.5, day=0) for i in range(10)]
    assert learning.derive(learning.group_stats(same_day))[0]["game"] == {}
    good = [sample(i, 1.4, game="Horror", day=i % 5) for i in range(10)]
    bad = [sample(100 + i, 0.6, game="Racing", day=i % 5) for i in range(10)]
    weights, reasons = learning.derive(learning.group_stats(good + bad))
    assert weights["game"] == {"Horror": 1.2, "Racing": 0.8}
    assert any("Horror läuft besser" in r for r in reasons)


def test_trial_is_kept_or_rolled_back(db: Session) -> None:
    before = [sample(i, 1.0, day=10 + i % 5) for i in range(10)]
    trial = learning.start_trial(db, {"game": {"Horror": 1.2}}, ["x"], {}, before, NOW)
    assert trial.status == learning.TRIAL and trial.evidence["baseline"] == 1.0
    assert learning.weights(db)["game"] == {"Horror": 1.2}
    assert learning.evaluate(db, trial, before, NOW) is None  # test period still running
    later = NOW + timedelta(days=8)
    worse = [learning.Sample(200 + i, NOW + timedelta(days=1), 0.7, {}) for i in range(8)]
    assert learning.evaluate(db, trial, before + worse, later) == learning.ROLLED_BACK
    assert learning.current(db) is None and learning.weights(db)["game"] == {}

    trial2 = learning.start_trial(db, {"format": {"f1": 1.1}}, ["y"], {}, before, NOW)
    fine = [learning.Sample(300 + i, NOW + timedelta(days=1), 1.05, {}) for i in range(8)]
    assert learning.evaluate(db, trial2, before + fine, later) == learning.ACTIVE
    assert learning.current(db) is trial2 and trial2.evaluation["trial_posts"] == 8


def test_trial_without_enough_data_is_rolled_back_after_the_maximum(db: Session) -> None:
    trial = learning.start_trial(db, {"hook": {"h": 1.1}}, [], {}, [], NOW)
    assert learning.evaluate(db, trial, [], NOW + timedelta(days=10)) is None
    assert learning.evaluate(db, trial, [], NOW + timedelta(days=22)) == learning.ROLLED_BACK


def test_learning_agent_without_data_changes_nothing(db: Session, settings: Settings) -> None:
    result = run(db, settings, "learning", {})
    assert result.status == AgentRunStatus.SUCCEEDED and result.output["change"] is False
    assert db.scalar(select(LearningVersion)) is None


def test_consumers_use_the_learned_factors() -> None:
    merged = learning.merge_groups({"game": {"A": 1.5}}, {"game": {"A": 0.8, "B": 1.2}})
    assert merged["game"] == {"A": 1.5, "B": 1.2}  # channel data wins
    assert learning.format_performance({"format": {"f1": 1.2, "f2": 0.8, "f3": 1.0}}) == {
        "f1": 1.0,
        "f2": 0.0,
        "f3": 0.5,
    }


# --- costs and budget ---------------------------------------------------------------


def test_fixed_costs_count_against_the_budget(db: Session, settings: Settings) -> None:
    update_operations(db, None, {"monthly_budget_eur": 50})
    fixed = settings.model_copy(update={"server_monthly_eur": 30.0})
    status = budget.budget_status(db, fixed)
    assert status.spent_eur >= Decimal("30") and status.used_pct >= 60
    assert status.level in (
        budget.BudgetLevel.WARN,
        budget.BudgetLevel.REDUCED,
        budget.BudgetLevel.PRIORITY_ONLY,
        budget.BudgetLevel.STOP_PAID,
    )


def test_cost_summary_per_video_and_views(db: Session, settings: Settings) -> None:
    update_operations(db, None, {"monthly_budget_eur": 50})
    db.add(Cost(category=CostCategory.AI, amount_eur=Decimal("2.5"), provider="test"))
    post, _v = make_post(db, timedelta(hours=1), mock=False)
    db.add(Metric(post_id=post.id, measure_window=MetricWindow.H1, views=5000, measured_at=NOW))
    db.flush()
    s = settings.model_copy(update={"server_monthly_eur": 7.5})
    media = Path(s.media_root)
    media.mkdir(parents=True, exist_ok=True)
    (media / "x.bin").write_bytes(b"0" * 2048)
    data = costs.summary(db, s, None)
    assert data["costs"]["ai"] >= 2.5 and data["costs"]["fixed"] == 7.5
    assert data["storage"]["bytes"] == 2048
    assert data["videos"]["published"] >= 1 and data["videos"]["views"] >= 5000
    assert data["unit_costs"]["per_1000_views"] is not None
    assert data["prices_configured"] is True


# --- API ----------------------------------------------------------------------------


def test_analytics_api(
    db: Session, settings: Settings, api: TestClient, make_user: Callable[..., User]
) -> None:
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    post, v = make_post(db, timedelta(days=2))
    db.add(
        Metric(
            post_id=post.id,
            measure_window=MetricWindow.H48,
            views=800,
            likes=40,
            comments=5,
            shares=5,
            retention_pct=55.0,
            measured_at=NOW,
        )
    )
    v.video_format = "clutch"
    learning.start_trial(db, {"game": {"G": 1.1}}, ["Grund"], {}, [], NOW)
    make_user("viewer@example.com", UserRole.VIEWER)
    make_user("admin@example.com", UserRole.ADMIN)
    db.commit()
    h = login(api, "viewer@example.com")
    res = api.get("/api/analytics/overview", params={"days": 7, "format": "clutch"}, headers=h)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["test_data"] is True and data["totals"]["views"] >= 800
    assert data["totals"]["engagement_rate"] is not None
    assert any(g["key"] == "clutch" for g in data["groups"]["format"])
    assert "clutch" in data["options"]["format"]
    assert api.get("/api/costs/summary", headers=h).status_code == 200
    versions = api.get("/api/analytics/learning", headers=h).json()
    assert versions[0]["status"] == "trial" and versions[0]["reasons"] == ["Grund"]
    number = versions[0]["version"]
    assert api.post(f"/api/analytics/learning/{number}/rollback", headers=h).status_code == 403
    ha = login(api, "admin@example.com")
    res = api.post(f"/api/analytics/learning/{number}/rollback", headers=ha)
    assert res.status_code == 200 and res.json()["status"] == "active"
    assert res.json()["rolled_back_to"] == number


def test_expired_access_marks_channel_during_measurement(db: Session, settings: Settings) -> None:
    post, _v = make_post(
        db, timedelta(hours=25), mock=False, platform_code=PlatformCode.TIKTOK, external_id="7300"
    )
    channel = db.get(Channel, post.channel_id)
    assert channel is not None
    channel.auth_status = ChannelAuthStatus.AUTHORIZED
    db.flush()
    result = run(db, settings, "analytics")
    assert str(post.id) in result.output["problems"]
    assert channel.auth_status == ChannelAuthStatus.EXPIRED
