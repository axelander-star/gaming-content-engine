# ruff: noqa: F811 - pytest fixtures imported from the Phase 9 tests
"""Clipping campaigns (Content Rewards): license, campaign clips, manual submissions."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import (
    AgentRunStatus,
    AssetKind,
    CampaignStatus,
    Language,
    MaterialStatus,
    PlatformCode,
    PolicyStatus,
    PublishingJobStatus,
    PublishingMode,
    SourceType,
    SubmissionStatus,
    UserRole,
    VideoStatus,
)
from models import Clip, Scene, User, Variant
from models.access import Notification
from models.campaigns import Campaign, CampaignSubmission
from models.channels import Channel
from models.production import GameplayFile, QualityCheck
from models.publishing import Post, PublishingJob
from models.rights import Asset, License, PublisherPolicy, Source
from models.trends import Game
from services import campaigns, orchestrator, rights, storage
from services.controls import update_operations
from services.projects import default_project_id
from services.seed import seed_base_data
from tests.conftest import login
from tests.factories import build_chain
from tests.integration.test_localization_voice import (  # noqa: F401 - shared fixtures
    gameplay,
    settings,
)

MakeUser = Callable[..., User]


def channel_of(db: Session, code: PlatformCode, lang: Language) -> Channel:
    seed_base_data(db, demo_channels=True)
    channel = db.scalar(
        select(Channel)
        .where(Channel.language == lang, Channel.content_project_id == default_project_id(db))
        .where(Channel.platform.has(code=code))
        .order_by(Channel.id)
    )
    assert channel is not None
    return channel


def brief(db: Session, **extra: Any) -> dict[str, Any]:
    yt = channel_of(db, PlatformCode.YOUTUBE, Language.DE)
    data: dict[str, Any] = {
        "content_project_id": default_project_id(db),
        "name": "Streamer XY Highlights",
        "url": "https://contentrewards.com/campaigns/streamer-xy",
        "cpm_usd": Decimal("1.50"),
        "platforms": ["youtube", "tiktok"],
        "languages": ["de"],
        "channel_ids": [yt.id],
        "required_hashtags": ["#StreamerXY", "ad"],
        "disclosure": "#Werbung",
        "required_text": "@streamerxy",
        "max_duration_s": 60,
        "rights_confirmed": True,
    }
    data.update(extra)
    return data


def make_campaign(db: Session, **extra: Any) -> Campaign:
    verifier = User(email=f"op-{uuid4().hex[:6]}@example.com", password_hash="x")
    db.add(verifier)
    db.flush()
    return campaigns.create(db, brief(db, **extra), verifier.id)


def campaign_material(
    db: Session, campaign: Campaign, storage_uri: str = "mock://raw.mp4"
) -> GameplayFile:
    suffix = uuid4().hex[:8]
    game = Game(name=f"Campaign Game {suffix}", slug=f"campaign-game-{suffix}")
    db.add(game)
    db.flush()
    db.add(PublisherPolicy(game_id=game.id, status=PolicyStatus.PERMITTED, notes="test"))
    asset = Asset(
        source_id=campaign.source_id,
        license_id=campaign.license_id,
        game_id=game.id,
        kind=AssetKind.VIDEO,
        storage_uri=storage_uri,
    )
    db.add(asset)
    db.flush()
    material = GameplayFile(
        asset_id=asset.id,
        game_id=game.id,
        storage_uri=storage_uri,
        sha256=uuid4().hex * 2,
        status=MaterialStatus.RIGHTS_APPROVED,
    )
    db.add(material)
    db.flush()
    return material


def run(db: Session, s: Settings, agent: str, entity_type: str, entity_id: int) -> Any:
    return orchestrator.run_agent(
        db, s, agent, {"entity_type": entity_type, "entity_id": entity_id}
    )


# --- texts and helpers ------------------------------------------------------------------


def test_texts_are_added_once_and_checked() -> None:
    campaign = Campaign(
        name="X",
        disclosure="#Werbung",
        required_text="@streamerxy",
        required_hashtags=["StreamerXY", "ad"],
    )
    variant = Variant(description="Krasser Clutch", hashtags=["gaming", "ad"])
    assert campaigns.text_problems(campaign, variant)
    assert campaigns.apply_texts(campaign, variant) is True
    assert variant.description == "#Werbung\nKrasser Clutch\n\n@streamerxy"
    assert variant.hashtags == ["StreamerXY", "ad", "gaming"]
    assert campaigns.apply_texts(campaign, variant) is False  # idempotent
    assert campaigns.text_problems(campaign, variant) == []
    variant.description = "Werbung entfernt"
    assert any("Werbehinweis" in p for p in campaigns.text_problems(campaign, variant))


def test_submission_state_and_payout_estimate() -> None:
    now = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
    sub = CampaignSubmission(status=SubmissionStatus.OPEN)
    assert campaigns.state_of(sub, now).state == "needs_link"
    sub.post_url, sub.deadline_at = "https://youtu.be/x", now + timedelta(minutes=12)
    state = campaigns.state_of(sub, now)
    assert (state.state, state.seconds_left) == ("open", 720)
    assert campaigns.state_of(sub, now + timedelta(minutes=13)).state == "overdue"
    sub.status, sub.submitted_at = SubmissionStatus.SUBMITTED, now + timedelta(minutes=40)
    assert campaigns.state_of(sub, now).late is True

    c = Campaign(cpm_usd=Decimal("1.40"), min_views=5000, max_payout_per_clip_usd=Decimal("500"))
    assert campaigns.estimated_payout(c, 4000) == Decimal("0")
    assert campaigns.estimated_payout(c, 100_000) == Decimal("126.00")  # 140 $ minus 10 %
    assert campaigns.estimated_payout(c, 1_000_000) == Decimal("450.00")  # cap 500 $
    assert campaigns.estimated_payout(Campaign(), 1000) is None


# --- campaign as license ----------------------------------------------------------------


def test_campaign_creates_a_scoped_license(db: Session) -> None:
    campaign = make_campaign(db)
    source = db.get(Source, campaign.source_id)
    lic = db.get(License, campaign.license_id)
    assert source is not None and lic is not None
    assert source.type == SourceType.CAMPAIGN and source.url == campaign.url
    assert lic.allowed_platforms == ["youtube", "tiktok"] and lic.allowed_languages == ["de"]
    assert lic.document_uri == campaign.url and lic.verified_by_user_id is not None
    assert campaign.required_hashtags == ["StreamerXY", "ad"]

    material = campaign_material(db, campaign)
    result = rights.evaluate(db, material)
    # Only some platforms and one language, still approved: clips go to campaign channels.
    assert result.approved, result.as_json()

    campaigns.set_status(db, campaign, CampaignStatus.PAUSED, None)
    result = rights.evaluate(db, material)
    assert not result.approved
    assert "Kampagne ist pausiert" in {c.reason for c in result.checks}


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"rights_confirmed": False}, "bestätigen"),
        ({"url": "http://example.com"}, "https://"),
        ({"platforms": ["myspace"]}, "Unbekannte Plattformen"),
        ({"platforms": ["tiktok"]}, "zählt in der Kampagne nicht"),
        ({"languages": ["en"]}, "nicht erlaubt"),
        ({"channel_ids": []}, "Mindestens einen Kanal"),
        ({"min_duration_s": 90, "max_duration_s": 60}, "Mindestlänge"),
    ],
)
def test_invalid_campaigns_are_refused(db: Session, extra: dict[str, Any], message: str) -> None:
    with pytest.raises(campaigns.CampaignError, match=message):
        make_campaign(db, **extra)


def test_channel_of_another_topic_area_is_refused(db: Session) -> None:
    from models.projects import ContentProject

    food = ContentProject(name="Ernährung", slug=f"food-{uuid4().hex[:6]}")
    db.add(food)
    db.flush()
    yt = channel_of(db, PlatformCode.YOUTUBE, Language.DE)
    other = Channel(
        platform_id=yt.platform_id,
        content_project_id=food.id,
        language=Language.DE,
        name="Food DE",
    )
    db.add(other)
    db.flush()
    with pytest.raises(campaigns.CampaignError, match="anderen Themenbereich"):
        make_campaign(db, channel_ids=[other.id])


# --- the whole way: cut, check, approve, publish, submit --------------------------------


@pytest.fixture
def campaign_clip(db: Session, settings: Settings, gameplay: Path) -> Iterator[Variant]:
    """Campaign clip after Quality Control (waits for approval)."""
    update_operations(db, None, {"creative_variants": 1, "max_daily_production_jobs": 100})
    campaign = make_campaign(db)
    stored = storage.store_path(settings, gameplay, "materials", ".mp4", move=False)
    material = campaign_material(db, campaign, stored.uri)
    result = run(db, settings, "gameplay_analysis", "gameplay_files", material.id)
    assert result.status == AgentRunStatus.SUCCEEDED, result.error
    variants = db.scalars(
        select(Variant)
        .join(Clip, Clip.id == Variant.clip_id)
        .join(Scene, Scene.id == Clip.scene_id)
        .where(Scene.gameplay_file_id == material.id)
        .order_by(Variant.id)
    ).all()
    # Only the campaign channel gets clips (not the other languages or platforms).
    assert variants and {v.channel_id for v in variants} == set(campaign.channel_ids)
    variant = variants[0]
    for agent in (
        "clip_production",
        "creative_director",
        "script_hook",
        "localization",
        "voice",
        "subtitle",
        "quality_control",
    ):
        result = run(db, settings, agent, "variants", variant.id)
        assert result.status == AgentRunStatus.SUCCEEDED, (agent, result.error)
    yield variant


def test_campaign_clip_flow(db: Session, settings: Settings, campaign_clip: Variant) -> None:
    v = campaign_clip
    campaign = campaigns.for_variant(db, v)
    assert campaign is not None
    qc = db.scalars(
        select(QualityCheck).where(QualityCheck.variant_id == v.id).order_by(QualityCheck.id)
    ).all()[-1]
    names = {c["name"]: c for c in qc.checks["items"]}
    assert qc.passed, qc.reasons
    assert names["campaign_channel"]["passed"] and names["campaign_texts"]["passed"]
    # A campaign clip waits for a person instead of going to the strategy agent.
    assert v.status == VideoStatus.QUALITY_APPROVED
    assert (v.description or "").startswith("#Werbung")
    assert {"StreamerXY", "ad"} <= set(v.hashtags or [])

    # Removing the disclosure is undone by the text editor.
    campaigns.edit_texts(db, v, description="Nur Text")
    assert (v.description or "").startswith("#Werbung\nNur Text")

    campaigns.approve(db, v, None)
    assert v.status == VideoStatus.READY_TO_PUBLISH
    assert v.publish_options["privacy"] == "public"
    campaigns.withdraw(db, v, None)
    assert v.status == VideoStatus.QUALITY_APPROVED
    campaigns.approve(db, v, None)

    # publish (mock): the strategy agent would plan the job
    channel = db.get(Channel, v.channel_id)
    assert channel is not None
    channel.is_paused = channel.platform.is_paused = False
    v.status = VideoStatus.SCHEDULED
    db.add(
        PublishingJob(
            variant_id=v.id,
            channel_id=v.channel_id,
            status=PublishingJobStatus.SCHEDULED,
            mode=PublishingMode.MOCK,
            scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
            idempotency_key=f"c-{v.id}",
        )
    )
    db.flush()
    result = run(db, settings, "publishing", "variants", v.id)
    assert result.status == AgentRunStatus.SUCCEEDED, result.error
    sub = db.scalar(select(CampaignSubmission).where(CampaignSubmission.variant_id == v.id))
    assert sub is not None and result.output["campaign_submission_id"] == sub.id
    # Mock post: no public link yet, so no countdown either.
    assert campaigns.state_of(sub).state == "needs_link"
    assert db.scalar(select(Notification).where(Notification.title.contains(campaign.name)))
    with pytest.raises(campaigns.CampaignError, match="Link"):
        campaigns.mark_submitted(db, sub, None)

    now = datetime.now(UTC)
    campaigns.set_link(db, sub, "https://youtube.com/shorts/abc", None, now=now)
    assert sub.deadline_at == now + timedelta(minutes=30)
    assert campaigns.state_of(sub, now).state == "open"
    campaigns.mark_submitted(db, sub, None, now=now + timedelta(minutes=5))
    state = campaigns.state_of(sub)
    assert (state.state, state.late) == ("submitted", False)


def test_paused_campaign_stops_its_clips(
    db: Session, settings: Settings, campaign_clip: Variant
) -> None:
    campaign = campaigns.for_variant(db, campaign_clip)
    assert campaign is not None
    campaigns.set_status(db, campaign, CampaignStatus.ENDED, None)
    with pytest.raises(campaigns.CampaignError, match="beendet"):
        campaigns.approve(db, campaign_clip, None)
    campaigns.discard(db, campaign_clip, None)
    assert campaign_clip.status == VideoStatus.ARCHIVED


def test_normal_clip_is_no_campaign_clip(db: Session) -> None:
    chain = build_chain(db)
    assert campaigns.for_variant(db, chain.variant) is None
    with pytest.raises(campaigns.CampaignError):
        campaigns.approve(db, chain.variant, None)


# --- API ----------------------------------------------------------------------------


@pytest.fixture
def client(api: TestClient, settings: Settings) -> Iterator[TestClient]:
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    yield api


def published_post(db: Session, campaign: Campaign, url: str | None) -> Post:
    """A published post of a clip cut from the campaign's material."""
    chain = build_chain(db)
    asset = db.get(Asset, chain.gameplay_file.asset_id)
    assert asset is not None
    asset.source_id, asset.license_id = campaign.source_id, campaign.license_id
    v = chain.variant
    v.channel_id = campaign.channel_ids[0]
    v.status, v.title = VideoStatus.PUBLISHED, "Clutch"
    job = PublishingJob(
        variant_id=v.id,
        channel_id=v.channel_id,
        status=PublishingJobStatus.SUCCEEDED,
        idempotency_key=f"p-{v.id}",
    )
    db.add(job)
    db.flush()
    post = Post(
        publishing_job_id=job.id,
        variant_id=v.id,
        channel_id=v.channel_id,
        url=url,
        external_post_id="abc",
        published_at=datetime.now(UTC),
        is_mock=url is None,
    )
    db.add(post)
    db.flush()
    sub = campaigns.on_published(db, v, post)
    assert sub is not None
    assert campaigns.on_published(db, v, post) is sub  # only once per post
    return post


def test_api_flow(client: TestClient, make_user: MakeUser, db: Session) -> None:
    make_user("op@example.com", UserRole.OPERATOR)
    make_user("viewer@example.com", UserRole.VIEWER)
    data = {
        k: (str(v) if isinstance(v, Decimal) else v)
        for k, v in brief(db).items()
        if k != "rights_confirmed"
    }
    viewer = login(client, "viewer@example.com")
    assert client.post("/api/campaigns", json=data, headers=viewer).status_code == 403

    op = login(client, "op@example.com")
    r = client.post("/api/campaigns", json=data, headers=op)
    assert r.status_code == 422 and "bestätigen" in r.text
    r = client.post("/api/campaigns", json={**data, "rights_confirmed": True}, headers=op)
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["cpm_usd"] == 1.5 and created["channels"] and created["materials"] == 0
    assert client.get("/api/campaigns").json()[0]["id"] == created["id"]

    r = client.patch(
        f"/api/campaigns/{created['id']}", json={"submission_window_min": 45}, headers=op
    )
    assert r.status_code == 200 and r.json()["submission_window_min"] == 45
    r = client.patch(f"/api/campaigns/{created['id']}", json={"languages": ["en"]}, headers=op)
    assert r.status_code == 422

    campaign = db.get(Campaign, created["id"])
    assert campaign is not None
    published_post(db, campaign, "https://youtube.com/shorts/xyz")
    published_post(db, campaign, None)
    db.commit()  # an error response rolls back to the last commit

    open_subs = client.get("/api/campaigns/submissions/list").json()
    assert [s["state"] for s in open_subs] == ["open", "needs_link"]  # most urgent first
    first, draft = open_subs
    assert first["post_url"] == "https://youtube.com/shorts/xyz"
    assert 44 * 60 < first["seconds_left"] <= 45 * 60
    assert first["campaign_url"] == campaign.url

    r = client.post(f"/api/campaigns/submissions/{draft['id']}/link", json={"url": "x"}, headers=op)
    assert r.status_code == 422
    r = client.post(
        f"/api/campaigns/submissions/{draft['id']}/link",
        json={"url": "https://www.tiktok.com/@me/video/1"},
        headers=op,
    )
    assert r.status_code == 200 and r.json()["state"] == "open"

    r = client.post(f"/api/campaigns/submissions/{first['id']}/submitted", headers=op)
    assert r.status_code == 200 and r.json()["state"] == "submitted"
    r = client.post(
        f"/api/campaigns/submissions/{draft['id']}/skip", json={"note": "Doppelt"}, headers=op
    )
    assert r.json()["state"] == "skipped"
    assert client.get("/api/campaigns/submissions/list").json() == []
    done = client.get("/api/campaigns/submissions/list?done=true").json()
    assert {s["state"] for s in done} == {"submitted", "skipped"}
    r = client.post(f"/api/campaigns/submissions/{first['id']}/reopen", headers=op)
    assert r.json()["state"] == "open"

    listed = client.get("/api/campaigns").json()[0]
    assert (listed["submissions_open"], listed["submissions_done"]) == (1, 0)
    r = client.post(f"/api/campaigns/{created['id']}/status", json={"status": "paused"}, headers=op)
    assert r.json()["status"] == "paused"
    assert client.get("/api/campaigns/clips/list").json() == []
    assert client.post("/api/campaigns/clips/999999/approve", headers=op).status_code == 404
