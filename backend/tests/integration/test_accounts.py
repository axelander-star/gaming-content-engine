"""Account overview (A2): aggregation per channel, revenue, recommendation, API."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.enums import (
    CampaignStatus,
    ChannelAuthStatus,
    Language,
    MetricWindow,
    PlatformCode,
    PublishingJobStatus,
    PublishingMode,
    RevenueSource,
    SubmissionStatus,
    UserRole,
    VideoStatus,
)
from models import Campaign, CampaignSubmission, Channel, Metric, Post, PublishingJob, RevenueEntry
from models.access import User
from services import accounts
from tests.conftest import login
from tests.factories import build_chain

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)
MakeUser = Callable[..., User]


def channel(db: Session, code: PlatformCode, lang: Language = Language.DE) -> Channel:
    ch = db.scalar(select(Channel).where(Channel.platform.has(code=code), Channel.language == lang))
    assert ch is not None
    ch.auth_status = ChannelAuthStatus.AUTHORIZED
    ch.is_paused = False
    return ch


def post(db: Session, ch: Channel, days_ago: float, views: int, likes: int = 0) -> Post:
    chain = build_chain(db)
    v = chain.variant
    v.channel_id, v.language, v.status = ch.id, ch.language, VideoStatus.PUBLISHED
    job = PublishingJob(
        variant_id=v.id,
        channel_id=ch.id,
        status=PublishingJobStatus.SUCCEEDED,
        mode=PublishingMode.MOCK,
        scheduled_for=NOW - timedelta(days=days_ago),
        idempotency_key=f"acc-{uuid4().hex}",
    )
    db.add(job)
    db.flush()
    p = Post(
        publishing_job_id=job.id,
        variant_id=v.id,
        channel_id=ch.id,
        external_post_id=f"acc-{v.id}",
        published_at=NOW - timedelta(days=days_ago),
    )
    db.add(p)
    db.flush()
    # an older, smaller measurement must be ignored: only the latest counts
    db.add(
        Metric(
            post_id=p.id,
            measure_window=MetricWindow.H1,
            views=1,
            likes=0,
            measured_at=NOW - timedelta(days=days_ago) + timedelta(hours=1),
        )
    )
    db.add(
        Metric(
            post_id=p.id,
            measure_window=MetricWindow.D7,
            views=views,
            likes=likes,
            followers_gained=2,
            measured_at=NOW - timedelta(days=max(days_ago - 7, 0.01)),
        )
    )
    db.flush()
    return p


def by_id(rows: list[accounts.Account]) -> dict[int, accounts.Account]:
    return {a.channel_id: a for a in rows}


def test_overview_aggregates_and_recommends(db: Session) -> None:
    build_chain(db)  # seeds platforms and channels
    weak = channel(db, PlatformCode.YOUTUBE)
    strong = [
        channel(db, PlatformCode.TIKTOK),
        channel(db, PlatformCode.INSTAGRAM),
        channel(db, PlatformCode.FACEBOOK),
    ]
    for ch in [weak, *strong]:
        post(db, ch, 120, 500)  # first post long ago: channel is judged
    for days in (5, 15, 50):
        post(db, weak, days, 40)
        for ch in strong:
            post(db, ch, days, 2000 if days < 30 else 500, likes=100)
    db.add(
        RevenueEntry(
            channel_id=strong[0].id,
            source=RevenueSource.AFFILIATE,
            amount_eur=Decimal("12.50"),
            period_start=(NOW - timedelta(days=20)).date(),
            period_end=(NOW - timedelta(days=10)).date(),
        )
    )
    db.flush()

    rows = by_id(accounts.overview(db, get_settings(), NOW))
    w = rows[weak.id]
    assert (w.current.posts, w.current.views) == (2, 80)
    assert w.status == "pause_suggested"
    assert any("90 Tagen" in r for r in w.reasons)

    s = rows[strong[0].id]
    assert (s.current.posts, s.current.views, s.current.interactions) == (2, 4000, 200)
    assert s.current.followers == 4
    assert s.previous.views == 500
    assert s.status == "growing"
    assert s.revenue_30d == Decimal("12.50")
    assert s.revenue_by_source == {"affiliate": Decimal("12.50")}

    # channels that are not connected are never judged
    en = db.scalar(
        select(Channel).where(
            Channel.platform.has(code=PlatformCode.YOUTUBE), Channel.language == Language.EN
        )
    )
    assert en is not None
    assert rows[en.id].status == "setup"

    summary = accounts.summary(list(rows.values()))
    assert summary["revenue_30d"] == Decimal("12.50")
    assert summary["by_status"]["pause_suggested"] == 1
    assert summary["top_revenue"][0] == strong[0].id


def test_new_and_idle_channels_are_not_judged_too_early(db: Session) -> None:
    build_chain(db)
    young = channel(db, PlatformCode.YOUTUBE)
    idle = channel(db, PlatformCode.TIKTOK)
    for days in (2, 4, 6, 8):
        post(db, young, days, 1)
    post(db, idle, 200, 10)
    rows = by_id(accounts.overview(db, get_settings(), NOW))
    assert rows[young.id].status == "new"
    assert rows[idle.id].status == "idle"
    # fewer than three channels with posts: absolute lower bound instead of a median
    short = get_settings().model_copy(update={"account_review_days": 7})
    rows = by_id(accounts.overview(db, short, NOW))
    assert rows[young.id].status == "pause_suggested"
    assert "Untergrenze 200" in rows[young.id].reasons[0]


def test_revenue_stops_a_pause_suggestion(db: Session) -> None:
    build_chain(db)
    ch = channel(db, PlatformCode.YOUTUBE)
    post(db, ch, 100, 1)
    for days in (5, 10, 20):
        post(db, ch, days, 1)
    db.add(
        RevenueEntry(
            channel_id=ch.id,
            source=RevenueSource.SPONSOR,
            amount_eur=Decimal("50"),
            period_start=date.today(),
            period_end=date.today(),
        )
    )
    db.flush()
    acc = by_id(accounts.overview(db, get_settings(), NOW))[ch.id]
    assert acc.status != "pause_suggested"


def test_content_rewards_estimate(db: Session) -> None:
    chain = build_chain(db)
    ch = channel(db, PlatformCode.TIKTOK)
    p = post(db, ch, 3, 100_000)
    campaign = Campaign(
        content_project_id=ch.content_project_id,
        source_id=chain.license.source_id,
        license_id=chain.license.id,
        name="Streamer",
        url="https://contentrewards.com/x",
        status=CampaignStatus.ACTIVE,
        cpm_usd=Decimal("1.5"),
        max_payout_per_clip_usd=Decimal("100"),
    )
    db.add(campaign)
    db.flush()
    db.add(
        CampaignSubmission(
            campaign_id=campaign.id,
            post_id=p.id,
            variant_id=p.variant_id,
            channel_id=ch.id,
            posted_at=NOW - timedelta(days=3),
            status=SubmissionStatus.SUBMITTED,
        )
    )
    db.flush()
    acc = by_id(accounts.overview(db, get_settings(), NOW))[ch.id]
    # 100k views x 1.5 $ CPM = 150 $, capped at 100 $ -> 92 EUR
    assert acc.estimate_30d == Decimal("92.00")
    assert acc.revenue_30d == 0  # an estimate is no revenue


def test_api_overview_and_revenue(api: TestClient, db: Session, make_user: MakeUser) -> None:
    build_chain(db)
    ch = channel(db, PlatformCode.YOUTUBE)
    make_user()
    headers = login(api, "admin@example.com")
    r = api.get("/api/accounts")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["summary"]["review_days"] == 90
    assert data["summary"]["channels"] == len(data["accounts"]) >= 8

    body = {
        "channel_id": ch.id,
        "source": "youtube",
        "amount_eur": "3.20",
        "period_start": "2026-11-01",
        "period_end": str(date.today()),
    }
    r = api.post("/api/accounts/revenue", json=body, headers=headers)
    assert r.status_code == 201, r.text
    entry_id = r.json()["id"]
    bad = {**body, "period_start": "2026-12-31", "period_end": "2026-01-01"}
    assert api.post("/api/accounts/revenue", json=bad, headers=headers).status_code == 422
    row = next(a for a in api.get("/api/accounts").json()["accounts"] if a["channel_id"] == ch.id)
    assert row["revenue_30d"] == "3.20"
    assert [e["id"] for e in api.get(f"/api/accounts/revenue?channel_id={ch.id}").json()] == [
        entry_id
    ]
    assert api.delete(f"/api/accounts/revenue/{entry_id}", headers=headers).status_code == 204
    assert api.get(f"/api/accounts/revenue?channel_id={ch.id}").json() == []


def test_api_revenue_needs_admin(api: TestClient, db: Session, make_user: MakeUser) -> None:
    build_chain(db)
    ch = channel(db, PlatformCode.YOUTUBE)
    make_user(email="op@example.com", role=UserRole.OPERATOR)
    headers = login(api, "op@example.com")
    body = {
        "channel_id": ch.id,
        "source": "other",
        "amount_eur": "1",
        "period_start": "2026-11-01",
        "period_end": "2026-11-02",
    }
    assert api.post("/api/accounts/revenue", json=body, headers=headers).status_code == 403
