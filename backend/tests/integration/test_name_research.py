"""Channel names from market data (name_research + channel assistant)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis import Redis
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import Language, PlatformCode
from models import ContentProject
from models.competitors import Competitor, CompetitorVideo
from models.research import ResearchItem
from services import channel_setup, name_research, quota
from services.seed import seed_base_data
from tests.conftest import login

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(
        update={"media_root": str(tmp_path / "media"), "trend_sources_mode": "mock"}
    )


def watches(db: Session) -> ContentProject:
    seed_base_data(db, demo_channels=True)
    project = ContentProject(slug="uhren", name="Uhren", languages=["de"])
    db.add(project)
    db.flush()
    titles = [
        "Automatik oder Quarz: was taugt mehr?",
        "Neue Automatik-Uhren unter 300 Euro",
        "Taucheruhren im Test: Automatik schlägt Quarz",
        "Vintage Taucheruhren werden teurer",
        "Smartwatch-Verkäufe sinken",
    ]
    for i, title in enumerate(titles):
        db.add(
            ResearchItem(
                content_project_id=project.id,
                guid_hash=f"h{i}",
                title=title,
                fetched_at=NOW - timedelta(days=2),
            )
        )
    old = ResearchItem(
        content_project_id=project.id,
        guid_hash="old",
        title="Kalender Kalender Kalender",
        fetched_at=NOW - timedelta(days=90),
    )
    db.add(old)
    rival = Competitor(
        content_project_id=project.id, platform=PlatformCode.YOUTUBE, handle="zeitzone"
    )
    db.add(rival)
    db.flush()
    rival.name = "Zeitzone"
    for i, views in enumerate([1000, 5000, 9000]):
        db.add(
            CompetitorVideo(
                competitor_id=rival.id,
                external_id=f"v{i}",
                title="Taucheruhren unter 500 Euro",
                views=views,
                seen_at=NOW - timedelta(days=1),
            )
        )
    db.flush()
    return project


def test_keywords_competitors_and_facts_from_local_data(db: Session, settings: Settings) -> None:
    project = watches(db)
    ctx = name_research.collect(db, settings, project, Language.DE, now=NOW)
    words = dict(ctx.keywords)
    assert words["Automatik"] == 3  # once per title, the topic word "Uhren" is left out
    assert words["Taucheruhren"] == 5  # 2 news items + 3 competitor videos
    assert "Kalender" not in words  # older than 30 days
    assert "Uhren" not in words
    assert ctx.competitors == [("Zeitzone", 5000)]  # median views
    assert not ctx.live and ctx.similar == []
    facts = ctx.facts()
    assert facts[0].startswith("Häufige Begriffe der letzten 30 Tage: ")
    assert any("Zeitzone (Ø 5.000 Aufrufe)" in f for f in facts)
    assert any("TREND_SOURCES_MODE=live" in f for f in facts)
    assert "zeitzone" in ctx.taken_names()


def test_no_data_gives_a_hint(db: Session, settings: Settings) -> None:
    seed_base_data(db, demo_channels=True)
    project = ContentProject(slug="leer", name="Leer", languages=["de"])
    db.add(project)
    db.flush()
    ctx = name_research.collect(
        db, settings.model_copy(update={"trend_sources_mode": "live"}), project, Language.DE
    )
    assert ctx.keywords == [] and ctx.competitors == []
    assert "Konkurrenz-Radar" in ctx.facts()[0]


def _youtube_client(calls: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/search"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": {"channelId": "UC1"}, "snippet": {"channelTitle": "Uhrenkosmos"}},
                        {"id": {"channelId": "UC2"}, "snippet": {"channelTitle": "Uhren Kompakt"}},
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {"id": "UC1", "statistics": {"subscriberCount": "120000"}},
                    {"id": "UC2", "statistics": {"hiddenSubscriberCount": True}},
                ]
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_youtube_search_uses_official_api_and_quota(
    db: Session, settings: Settings, redis_client: Redis
) -> None:
    project = watches(db)
    live = settings.model_copy(
        update={"trend_sources_mode": "live", "youtube_api_key": SecretStr("test-key")}
    )
    calls: list[httpx.Request] = []
    ctx = name_research.collect(
        db, live, project, Language.DE, redis=redis_client, client=_youtube_client(calls), now=NOW
    )
    search, stats = calls
    assert search.url.path == "/youtube/v3/search"
    assert search.url.params["type"] == "channel" and search.url.params["q"] == "Uhren"
    assert search.url.params["regionCode"] == "DE"
    assert stats.url.path == "/youtube/v3/channels"
    assert stats.url.params["part"] == "statistics" and stats.url.params["id"] == "UC1,UC2"
    assert ctx.live
    assert [(c.title, c.subscribers) for c in ctx.similar] == [
        ("Uhrenkosmos", 120000),
        ("Uhren Kompakt", None),
    ]
    assert any("Uhrenkosmos (120.000 Abos)" in f for f in ctx.facts())
    assert quota.used(redis_client, "youtube_search") == 1

    # quota used up: no request, a note instead
    redis_client.set(quota._key("youtube_search"), name_research.SEARCH_DAILY_CALLS)
    calls.clear()
    ctx = name_research.collect(
        db, live, project, Language.DE, redis=redis_client, client=_youtube_client(calls), now=NOW
    )
    assert calls == [] and not ctx.live
    assert "aufgebraucht" in (ctx.note or "")


def test_names_avoid_existing_channels(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = watches(db)
    ctx = name_research.collect(db, settings, project, Language.DE, now=NOW)
    # the template favourite "Uhren Kompakt" already exists on YouTube
    ctx.similar = [name_research.SimilarChannel("Uhren Kompakt", 5000)]
    monkeypatch.setattr(channel_setup, "market_context", lambda *_a, **_k: ctx)
    task = channel_setup.prepare_one(db, settings, project, PlatformCode.YOUTUBE, Language.DE)
    assert task.display_name != "Uhren Kompakt"
    names = [o["name"] for o in task.name_options]
    assert "Uhren Kompakt" not in names and task.display_name not in names
    assert any("Automatik" in n or "Taucheruhren" in n for n in [task.display_name, *names])
    assert all(o["reason"] for o in task.name_options)
    assert task.research["facts"] and task.research["live"] is False


def test_ai_alternatives_are_used(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = watches(db)
    answer = {
        "display_name": "Zeit für Automatik",
        "alternatives": [
            {"name": "Zeitzone", "reason": "copy of a competitor"},
            {"name": "Tauchzeit", "reason": "Taucheruhren 3× in Meldungen"},
        ],
        "handles": ["zeitfuerautomatik"],
        "bio": "Uhren kurz erklärt.",
        "tagline": "Uhren in 60 Sekunden",
    }

    def fake_generate(_session: Session, _settings: Settings, req: object) -> object:
        prompt = req.messages[0].content  # type: ignore[attr-defined]
        assert "Frequent topic words" in prompt and "Automatik" in prompt
        assert "Strongest competitor channels" in prompt
        return type("R", (), {"text": json.dumps(answer), "provider": "claude"})()

    monkeypatch.setattr("services.ai.generate", fake_generate)
    task = channel_setup.prepare_one(db, settings, project, PlatformCode.TIKTOK, Language.DE)
    assert task.display_name == "Zeit für Automatik"
    assert task.name_options == [{"name": "Tauchzeit", "reason": "Taucheruhren 3× in Meldungen"}]
    assert task.text_source == "claude"


def test_api_research_again(
    api: TestClient, db: Session, settings: Settings, make_user: object
) -> None:
    project = watches(db)
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    make_user()  # type: ignore[operator]
    headers = login(api, "admin@example.com")
    r = api.post("/api/channel-setup/prepare", json={"project_id": project.id}, headers=headers)
    assert r.status_code == 201, r.text
    task = next(t for t in r.json() if t["platform"] == "youtube")
    assert task["research_facts"] and task["research_live"] is False
    assert task["name_options"] and {"name", "reason"} <= set(task["name_options"][0])

    r = api.post(f"/api/channel-setup/tasks/{task['id']}/research", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["researched_at"]
    # all at once again: another name and another look each time
    first = r.json()["display_name"]
    first_avatar = api.get(f"/api/channel-setup/tasks/{task['id']}/avatar.png", headers=headers)
    r = api.post(f"/api/channel-setup/tasks/{task['id']}/research", headers=headers)
    assert r.json()["display_name"] != first
    assert first in [o["name"] for o in r.json()["name_options"]]
    second_avatar = api.get(f"/api/channel-setup/tasks/{task['id']}/avatar.png", headers=headers)
    assert second_avatar.status_code == 200 and second_avatar.content != first_avatar.content
    r = api.post(f"/api/channel-setup/tasks/{task['id']}/dismiss", headers=headers)
    r = api.post(f"/api/channel-setup/tasks/{task['id']}/research", headers=headers)
    assert r.status_code == 422


def test_api_research_single_fields(
    api: TestClient, db: Session, settings: Settings, make_user: object
) -> None:
    """Each AI symbol renews only its own field; pictures change together."""
    project = watches(db)
    project.subtopics = ["Automatik", "Taucheruhren"]
    db.commit()
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    make_user()  # type: ignore[operator]
    headers = login(api, "admin@example.com")
    r = api.post("/api/channel-setup/prepare", json={"project_id": project.id}, headers=headers)
    task = next(t for t in r.json() if t["platform"] == "youtube")
    url = f"/api/channel-setup/tasks/{task['id']}/research"

    def pics() -> tuple[bytes, bytes]:
        base = f"/api/channel-setup/tasks/{task['id']}"
        return (
            api.get(f"{base}/avatar.png", headers=headers).content,
            api.get(f"{base}/banner.png", headers=headers).content,
        )

    before, pics_before = task, pics()

    # name: only the name changes; the pictures show the new name
    r = api.post(f"{url}?part=name", headers=headers)
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["display_name"] != before["display_name"]
    assert (after["handle"], after["bio"]) == (before["handle"], before["bio"])
    assert pics() != pics_before

    # handle: matches the current name, nothing else changes
    r = api.post(f"{url}?part=handle", headers=headers)
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["handle"] != after["handle"]
    assert (h["display_name"], h["bio"]) == (after["display_name"], after["bio"])
    name_key = channel_setup.normalize_handle(h["display_name"], PlatformCode.YOUTUBE)
    assert h["handle"].startswith(name_key)
    r = api.post(f"{url}?part=handle", headers=headers)
    assert r.json()["handle"] != h["handle"]  # every click a new one

    # bio: a different bio each click, name and handle stay
    bios = {after["bio"]}
    for _ in range(3):
        r = api.post(f"{url}?part=bio", headers=headers)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["bio"] not in bios
        assert b["display_name"] == h["display_name"]
        bios.add(b["bio"])

    # images: avatar and banner both new, texts unchanged
    texts = (b["display_name"], b["handle"], b["bio"])
    p1 = pics()
    r = api.post(f"{url}?part=images", headers=headers)
    assert r.status_code == 200, r.text
    p2 = pics()
    assert p2[0] != p1[0] and p2[1] != p1[1]
    assert (r.json()["display_name"], r.json()["handle"], r.json()["bio"]) == texts

    assert api.post(f"{url}?part=email", headers=headers).status_code == 422


def test_next_after_rotates() -> None:
    assert channel_setup._next_after("b", ["a", "b", "c"]) == "c"
    assert channel_setup._next_after("c", ["a", "b", "c"]) == "a"
    assert channel_setup._next_after("x", ["a", "b"]) == "a"
    assert channel_setup._next_after("a", ["a", "a"]) is None
    assert channel_setup._next_after("A", ["a", "b"], key=str.lower) == "b"
