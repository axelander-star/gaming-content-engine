"""Topic suggestions from trends ("Themen vorschlagen"). No network: MockTransport."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import ContentProjectStatus
from models.access import User
from models.projects import ContentProject
from services import topic_suggest
from services.projects import ensure_default_project
from tests.conftest import login

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 26, 12, tzinfo=UTC)


def video(
    i: int, views: int, hours: int, channel: str, title: str, category: str = ""
) -> dict[str, object]:
    published = datetime(2026, 11, 26, 12 - hours, tzinfo=UTC).isoformat()
    return {
        "id": f"v{i}",
        "snippet": {
            "title": title,
            "channelId": channel,
            "categoryId": category,
            "publishedAt": published.replace("+00:00", "Z"),
        },
        "statistics": {"viewCount": str(views)},
    }


def fake_google(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "wikimedia.org" in url:
        assert "ContentEngine" in request.headers["User-Agent"]
        articles = [
            {"article": "Hauptseite", "views": 9_000_000},
            {"article": "Spezial:Suche", "views": 800_000},
            {"article": "Airfryer", "views": 120_000},
        ]
        return httpx.Response(200, json={"items": [{"articles": articles}]})
    assert "key=yt-key" in url
    category = request.url.params.get("videoCategoryId")
    region = request.url.params.get("regionCode")
    if category is None:  # overall chart: gaming and entertainment only show up here
        items = [video(i, 40_000, 4, f"g{i}", "Minecraft Update", "20") for i in range(5)]
        items += [video(10 + i, 30_000, 3, f"e{i}", "Reaction Show", "24") for i in range(3)]
        if region == "US":
            items = [video(i, 9_000_000, 1, f"u{i}", "Dog rescue", "15") for i in range(9)]
    elif region == "US":
        items = (
            [video(i, 9_000_000, 1, f"u{i}", "Dog rescue", "15") for i in range(9)]
            if category == "15"
            else []
        )
    elif category in ("20", "24"):
        return httpx.Response(404, json={"error": {"errors": [{"reason": "notFound"}]}})
    elif category == "26":
        items = [video(i, 200_000, 2, f"c{i}", "Airfryer Rezepte schnell") for i in range(6)]
    elif category == "28":
        items = [video(i, 50_000, 10, "big", "Handy Akku Trick") for i in range(4)]
    elif category == "1":
        return httpx.Response(404, json={"error": {"errors": [{"reason": "notFound"}]}})
    else:
        items = []
    return httpx.Response(200, json={"items": items})


@pytest.fixture
def live() -> Settings:
    return get_settings().model_copy(
        update={
            "youtube_api_key": SecretStr("yt-key"),
            "trend_sources_mode": "live",
            "trend_alarm_regions": "DE",
        }
    )


def test_live_suggestions_have_real_numbers_and_skip_existing_areas(
    db: Session, live: Settings, redis_client: Redis
) -> None:
    ensure_default_project(db)  # "Gaming" exists and is never suggested
    with httpx.Client(transport=httpx.MockTransport(fake_google)) as client:
        result = topic_suggest.suggest(db, live, redis_client, client=client, now=NOW)
    assert result.live and not result.sample
    assert result.errors == []  # 404 for a category is no error
    names = [s.name for s in result.suggestions]
    assert names[0] == "Praktische Tipps & Styling"  # fastest growth, many channels
    assert "Gaming" not in names
    top = result.suggestions[0]
    assert "100.000 Aufrufe pro Stunde" in top.facts[0]
    assert "6 verschiedene Kanäle" in top.facts[0]
    assert top.subtopics[:2] == ["Airfryer", "Rezepte"]
    assert top.examples == ["Airfryer Rezepte schnell"] * 3
    tech = next(s for s in result.suggestions if s.name == "Wissenschaft & Technik")
    assert "1 verschiedene Kanäle" in tech.facts[0]
    # no category chart for entertainment in DE (404): the overall chart stands in
    show = next(s for s in result.suggestions if s.name == "Unterhaltung")
    assert show.facts[0].startswith("Unterhaltung (Deutschland): 3 der 50")
    assert "3 Plätze in den Top 50 insgesamt" in show.facts[0]


def test_germany_counts_most_and_gaming_is_always_considered(
    db: Session, live: Settings, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    for area in db.scalars(select(ContentProject)):
        area.status = ContentProjectStatus.ARCHIVED  # free all names, Gaming included
    db.flush()
    monkeypatch.setattr(topic_suggest, "SUGGESTIONS", 3)
    settings = live.model_copy(update={"trend_alarm_regions": "DE,US"})
    with httpx.Client(transport=httpx.MockTransport(fake_google)) as client:
        result = topic_suggest.suggest(db, settings, redis_client, client=client, now=NOW)
    names = [s.name for s in result.suggestions]
    # US dogs grow 90x faster than anything in Germany, yet Germany leads
    assert names[0] == "Praktische Tipps & Styling"
    # three places: gaming and entertainment (both only in the overall chart) push
    # out the faster US topic
    assert names == ["Praktische Tipps & Styling", "Gaming", "Unterhaltung"]
    gaming = next(s for s in result.suggestions if s.name == "Gaming")
    assert gaming.facts[0].startswith("Gaming (Deutschland): 5 der 50")
    assert gaming.subtopics[:2] == ["Minecraft", "Update"]


def test_production_without_key_gives_a_hint_not_invented_numbers(
    db: Session, redis_client: Redis
) -> None:
    prod = get_settings().model_copy(update={"sample_data": False})
    result = topic_suggest.suggest(db, prod, redis_client, now=NOW)
    assert result.suggestions == [] and not result.sample
    assert result.hint is not None and "YOUTUBE_API_KEY" in result.hint


def test_development_shows_marked_sample_data(db: Session, redis_client: Redis) -> None:
    dev = get_settings().model_copy(update={"sample_data": True})
    result = topic_suggest.suggest(db, dev, redis_client, now=NOW)
    assert result.sample and len(result.suggestions) == topic_suggest.SUGGESTIONS


def test_api_for_admin_only(
    api: TestClient, make_user: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.enums import UserRole

    make_user()
    make_user(email="viewer@example.com", role=UserRole.VIEWER)
    headers = login(api, "viewer@example.com")
    assert api.post("/api/projects/suggestions", headers=headers).status_code == 403
    headers = login(api, "admin@example.com")
    r = api.post("/api/projects/suggestions", headers=headers)
    assert r.status_code == 200, r.text
    assert set(r.json()) >= {"live", "sample", "suggestions", "hint"}


def test_area_profile_from_trends(db: Session, live: Settings, redis_client: Redis) -> None:
    assert topic_suggest.category_for("Unterhaltung", []) == "24"
    assert topic_suggest.category_for("Zocken am Abend", []) == "20"
    with httpx.Client(transport=httpx.MockTransport(fake_google)) as client:
        profile = topic_suggest.profile_for(
            db, live, redis_client, name="Unterhaltung", subtopics=["Fakten"], client=client,
            now=NOW,
        )  # fmt: skip
    assert profile.live and profile.errors == []
    assert profile.description and profile.audience and profile.tone
    # the category chart is missing (404): the overall chart's entertainment videos count
    assert profile.facts == [
        "Unterhaltung (Deutschland): 3 der 50 meistgesehenen Videos, Median 30.000 Aufrufe, "
        "10.000 Aufrufe pro Stunde, 3 verschiedene Kanäle, 3 Plätze in den Top 50 insgesamt"
    ]
    assert profile.subtopics[:3] == ["Fakten", "Reaction", "Show"]


def test_area_profile_api(api: TestClient, make_user: Callable[..., User]) -> None:
    make_user()
    headers = login(api, "admin@example.com")
    r = api.post("/api/projects/profile-suggestion", json={"name": "Unterhaltung"}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["description"] and body["audience"] and body["tone"]
    assert isinstance(body["subtopics"], list)
