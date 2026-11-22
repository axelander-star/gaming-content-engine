# ruff: noqa: F811 - pytest fixtures imported from the campaign tests
"""Campaign help: read a pasted brief, video proposals, deadline watcher."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import CampaignStatus, UserRole
from models.access import Notification
from models.campaigns import Campaign, CampaignSubmission
from models.research import ResearchItem
from models.trends import Game, Trend
from services import ai, campaign_assist, campaigns
from services.projects import default_project_id
from tests.conftest import login
from tests.integration.test_campaigns import (
    brief,
    campaign_material,
    make_campaign,
    published_post,
)
from tests.integration.test_localization_voice import settings  # noqa: F401 - shared fixture

PAGE = """Valorant Clutch Moments
https://contentrewards.com/c/valorant-clutch
Earn $1.50 per 1,000 views · Budget: $5,000 · Max payout per clip $300
Minimum 10k views to get paid.
Platforms: TikTok, YouTube Shorts, Instagram Reels. English only.
Clips must be 15-60 seconds. Use #ad and #ValorantClutch #RiotPartner
Credit @clutchking in the caption.
Show the clutch round from start to end and keep the game audio.
Campaign ends 2026-12-31.
Material: https://drive.google.com/drive/folders/abc123
"""
TODAY = date(2026, 11, 22)


def test_heuristics_read_the_brief() -> None:
    f = campaign_assist.heuristic_fields(PAGE, [(7, "Valorant")], TODAY)
    assert f["name"] == "Valorant Clutch Moments"
    assert f["url"] == "https://contentrewards.com/c/valorant-clutch"
    assert f["cpm_usd"] == Decimal("1.50")
    assert f["budget_usd"] == Decimal("5000")
    assert f["max_payout_per_clip_usd"] == Decimal("300")
    assert f["min_views"] == 10_000
    assert set(f["platforms"]) == {"tiktok", "youtube", "instagram"}
    assert f["languages"] == ["en"]
    assert (f["min_duration_s"], f["max_duration_s"]) == (15, 60)
    assert f["disclosure"] == "#ad"
    assert f["required_hashtags"] == ["#ValorantClutch", "#RiotPartner"]
    assert f["required_text"] == "@clutchking"
    assert f["ends_on"] == date(2026, 12, 31)
    assert f["material_links"] == ["https://drive.google.com/drive/folders/abc123"]
    assert f["game_id"] == 7


@pytest.mark.parametrize(
    ("text", "key", "value"),
    [
        ("Pays 2.10$ per 1k views", "cpm_usd", Decimal("2.10")),
        ("CPM: $0.80", "cpm_usd", Decimal("0.80")),
        ("Budget $12k", "budget_usd", Decimal("12000")),
        ("max 45 sec", "max_duration_s", 45),
        ("Endet am 05.12.2026", "ends_on", date(2026, 12, 5)),
        ("Ends December 3, 2026", "ends_on", date(2026, 12, 3)),
        ("ends in 10 days", "ends_on", date(2026, 12, 2)),
        ("Deutsch, TikTok", "languages", ["de"]),
        ("Mail me at a@b.com", "required_text", None),
    ],
)
def test_heuristic_variants(text: str, key: str, value: Any) -> None:
    assert campaign_assist.heuristic_fields(text, [], TODAY)[key] == value


def test_parse_page_fills_the_form(db: Session, settings: Settings) -> None:
    game = Game(name="Valorant", slug=f"valorant-{uuid4().hex[:6]}")
    db.add(game)
    db.flush()
    result = campaign_assist.parse_page(db, settings, PAGE, today=TODAY)
    assert result.source == "mock"
    assert result.fields["game_id"] == game.id
    assert result.game == "Valorant"
    assert result.fields["cpm_usd"] == 1.5
    assert result.fields["ends_on"] == "2026-12-31"
    assert result.fields["brief"].startswith("Valorant Clutch Moments")
    assert "Plattformen" not in result.missing
    empty = campaign_assist.parse_page(
        db, settings, "Nur ein kurzer Text ohne Angaben", today=TODAY
    )
    assert "Vergütung je 1.000 Aufrufe" in empty.missing


def test_model_answer_only_fills_gaps(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = {
        "cpm_usd": 99,  # the text says 1.50: the text wins
        "platforms": ["youtube", "myspace"],
        "languages": ["de"],
        "url": "javascript:alert(1)",
        "ends_on": "2020-01-01",  # in the past: dropped
        "max_duration_s": 9999,  # implausible: dropped
    }

    def fake(_s: Session, _st: Settings, req: ai.AIRequest) -> ai.AIResult:
        return ai.AIResult(json.dumps(answer), "claude", "m", 1, 1, 1, Decimal(0), [], "end_turn")

    monkeypatch.setattr(ai, "generate", fake)
    result = campaign_assist.parse_page(
        db, settings, "Earn $1.50 per 1000 views for clips", today=TODAY
    )
    f = result.fields
    assert result.source == "claude"
    assert f["cpm_usd"] == 1.5
    assert f["platforms"] == ["youtube"]
    assert f["languages"] == ["de"]
    assert f["url"] is None and f["ends_on"] is None and f["max_duration_s"] is None


def with_game(db: Session, campaign: Campaign) -> Game:
    game = Game(name=f"Arena {uuid4().hex[:4]}", slug=f"arena-{uuid4().hex[:6]}")
    db.add(game)
    db.flush()
    campaign.game_id = game.id
    db.add(Trend(game_id=game.id, source="twitch", score=Decimal("88"), metrics={"viewers": 42000}))
    db.add(
        ResearchItem(
            content_project_id=campaign.content_project_id,
            guid_hash=uuid4().hex,
            title=f"{game.name} season 3 is live",
            url="https://example.com/news",
            summary="New map and ranked reset.",
        )
    )
    db.flush()
    return game


def test_template_proposals_follow_the_rules(db: Session, settings: Settings) -> None:
    campaign = make_campaign(db, min_duration_s=20, max_duration_s=30, brief="Zeige den Clutch.")
    game = with_game(db, campaign)
    proposals = campaign_assist.generate_proposals(db, settings, campaign)
    assert len(proposals) == 3
    assert campaign.proposals_source == "template"
    assert campaign.proposals_basis
    for p in proposals:
        assert p["caption"].startswith("#Werbung")
        assert "#StreamerXY" in p["caption"] and "@streamerxy" in p["caption"]
        assert 20 <= p["length_s"] <= 30
        assert p["hook"] and p["scenes"]
    trend = proposals[2]
    assert "42000" in trend["hook"]
    assert any(f"{game.name} season 3" in fact for fact in trend["facts"])


def test_model_proposals_are_cleaned(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign = make_campaign(db, max_duration_s=40)
    answer = {
        "proposals": [
            {
                "title": "Clutch",
                "hook": "1 gegen 5",
                "scenes": ["a", "b"],
                "caption_body": "Krass #ad",
                "hashtags": ["clutch", "<script>"],
                "length_s": 300,
            },
            {"title": "", "hook": "ohne Titel"},
        ]
    }

    def fake(_s: Session, _st: Settings, req: ai.AIRequest) -> ai.AIResult:
        assert "<brief>" in str(req.messages[-1].content)
        assert req.tools is None
        return ai.AIResult(json.dumps(answer), "claude", "m", 1, 1, 1, Decimal(0), [], "end_turn")

    monkeypatch.setattr(ai, "generate", fake)
    proposals = campaign_assist.generate_proposals(db, settings, campaign)
    assert campaign.proposals_source == "claude"
    assert len(proposals) == 1
    p = proposals[0]
    assert p["length_s"] == 40
    assert p["caption"].splitlines()[0] == "#Werbung"
    assert p["caption"].splitlines()[1] == "Krass"  # model's "#ad" moved out of the text
    assert "<script>" not in p["caption"]
    assert "#clutch" in p["caption"]


def test_next_step() -> None:
    c = Campaign(status=CampaignStatus.ACTIVE, material_links=[], ends_on=None)
    step = campaign_assist.next_step
    assert "hochladen" in step(c, materials=0, clips_waiting=0, submissions_open=0)
    assert "freigeben" in step(c, materials=1, clips_waiting=2, submissions_open=0)
    assert "einreichen" in step(c, materials=1, clips_waiting=2, submissions_open=1)
    assert "Läuft" in step(c, materials=1, clips_waiting=0, submissions_open=0)
    c.ends_on = TODAY - timedelta(days=1)
    assert "Beendet" in step(c, materials=1, clips_waiting=0, submissions_open=0, today=TODAY)
    c.status = CampaignStatus.PAUSED
    assert "Pausiert" in step(c, materials=1, clips_waiting=0, submissions_open=0)


def keys(db: Session) -> set[str]:
    return set(db.scalars(select(Notification.dedup_key).where(Notification.kind == "campaign")))


def test_watch_reminds_and_refreshes(db: Session, settings: Settings) -> None:
    now = datetime.now(UTC)
    campaign = make_campaign(db, ends_on=now.date() + timedelta(days=2))
    campaign.created_at = now - timedelta(days=2)
    post = published_post(db, campaign, "https://youtu.be/x")
    sub = db.scalar(select(CampaignSubmission).where(CampaignSubmission.post_id == post.id))
    assert sub is not None
    sub.deadline_at = now + timedelta(minutes=10)
    db.flush()

    result = campaign_assist.watch(db, settings, now)
    assert {
        f"campaign-soon:{sub.id}",
        f"campaign-ends:{campaign.id}",
    } <= set(result.created)
    assert campaign.id in result.refreshed and campaign.proposals
    # published_post attached its material to the campaign: no "no material" warning
    assert f"campaign-material:{campaign.id}" not in result.created

    again = campaign_assist.watch(db, settings, now + timedelta(minutes=1))
    assert again.created == [] and again.refreshed == []  # deduplicated, nothing changed

    sub.deadline_at = now - timedelta(minutes=1)
    db.flush()
    late = campaign_assist.watch(db, settings, now + timedelta(minutes=2))
    assert late.created == [f"campaign-late:{sub.id}"]

    # new trend data: proposals are refreshed, at most once a day
    with_game(db, campaign)
    assert campaign_assist.watch(db, settings, now + timedelta(hours=1)).refreshed == []
    assert campaign_assist.watch(db, settings, now + timedelta(hours=25)).refreshed == [campaign.id]


def test_watch_without_material_and_after_end(db: Session, settings: Settings) -> None:
    now = datetime.now(UTC)
    campaign = make_campaign(db, ends_on=now.date() + timedelta(days=1))
    fresh = campaign_assist.watch(db, settings, now)
    assert f"campaign-material:{campaign.id}" not in fresh.created  # just created
    campaign.created_at = now - timedelta(days=2)
    campaign.ends_on = now.date() - timedelta(days=1)
    db.flush()
    result = campaign_assist.watch(db, settings, now)
    assert {f"campaign-material:{campaign.id}", f"campaign-over:{campaign.id}"} <= set(
        result.created
    )
    campaign_material(db, campaign)
    campaigns.set_status(db, campaign, CampaignStatus.ENDED, None)
    assert campaign_assist.watch(db, settings, now + timedelta(days=2)).created == []


# --- API ----------------------------------------------------------------------------


@pytest.fixture
def client(api: TestClient, settings: Settings) -> Iterator[TestClient]:
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    yield api


def test_api(client: TestClient, make_user: Any, db: Session) -> None:
    make_user("op@example.com", UserRole.OPERATOR)
    make_user("viewer@example.com", UserRole.VIEWER)
    viewer = login(client, "viewer@example.com")
    assert (
        client.post("/api/campaigns/parse", json={"text": PAGE}, headers=viewer).status_code == 403
    )
    op = login(client, "op@example.com")
    r = client.post("/api/campaigns/parse", json={"text": PAGE}, headers=op)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fields"]["max_duration_s"] == 60 and "cpm_usd" in body["found"]
    assert client.post("/api/campaigns/parse", json={"text": "kurz"}, headers=op).status_code == 422

    data = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in brief(db).items()}
    db.commit()
    r = client.post("/api/campaigns", json=data, headers=op)
    assert r.status_code == 201, r.text
    created = r.json()
    assert len(created["proposals"]) == 3 and created["proposals_source"] == "template"
    assert "hochladen" in created["next_step"]
    r = client.post(f"/api/campaigns/{created['id']}/proposals", headers=op)
    assert r.status_code == 200
    assert r.json()["proposals_at"] >= created["proposals_at"]
    assert default_project_id(db) == created["content_project_id"]
