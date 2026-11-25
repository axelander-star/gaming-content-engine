"""Ausbau A5: weekly rules, holidays/occasions, competitor radar.

No test talks to YouTube: the live radar runs against an ``httpx.MockTransport``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import UserRole
from models.access import User
from models.assistant import ChatAction
from models.competitors import Competitor, CompetitorVideo
from models.planning import EditorialDay, PlanRule
from models.projects import ContentProject
from models.research import ResearchItem
from services import assistant, competitors, events, ideas, plan_rules, planning
from services.seed import seed_base_data
from tests.conftest import login

pytestmark = pytest.mark.integration

MakeUser = Callable[..., User]


@pytest.fixture
def uhren(db: Session) -> ContentProject:
    seed_base_data(db, demo_channels=True)
    p = ContentProject(
        slug="uhren", name="Uhren", languages=["de"], subtopics=["Rolex", "Smartwatch"],
        priority=300,
    )  # fmt: skip
    db.add(p)
    db.flush()
    return p


def _today() -> date:
    return planning.today(get_settings())


# --- holidays and occasions ------------------------------------------------------------


def test_built_in_dates_2026() -> None:
    assert events.easter(2026) == date(2026, 4, 5)
    assert events.easter(2025) == date(2025, 4, 20)
    by_name = {o.name: o.day for o in events.built_in(2026)}
    assert by_name["Karfreitag"] == date(2026, 4, 3)
    assert by_name["Christi Himmelfahrt / Vatertag"] == date(2026, 5, 14)
    assert by_name["Pfingsten"] == date(2026, 5, 24)
    assert by_name["Muttertag"] == date(2026, 5, 10)
    assert by_name["Thanksgiving"] == date(2026, 11, 26)
    assert by_name["Black Friday"] == date(2026, 11, 27)
    assert by_name["Cyber Monday"] == date(2026, 11, 30)
    assert by_name["1. Advent"] == date(2026, 11, 29)
    assert {o.name: o.day for o in events.built_in(2027)}["1. Advent"] == date(2027, 11, 28)


def test_between_language_and_upcoming(db: Session) -> None:
    nov = events.between(None, date(2026, 11, 1), date(2026, 11, 30), language="de")
    names = [o.name for o in nov]
    assert "Black Friday" in names and "Thanksgiving" not in names
    en = [o.name for o in events.between(None, date(2026, 11, 1), date(2026, 11, 30), "en")]
    assert "Thanksgiving" in en and "1. Advent" not in en
    soon = events.upcoming(None, date(2026, 11, 16), days=30)
    names = [o.name for o in soon]
    # Black Friday has 21 days lead time, Weihnachten only 21 days -> not yet on 16.11.
    assert "Black Friday" in names and "Weihnachten" not in names
    assert events.describe(soon[0], date(2026, 11, 16)).endswith("Tagen)")


def test_occasions_reach_the_idea_prompt(db: Session, uhren: ContentProject) -> None:
    prompt = ideas._prompt(uhren, [], [], 3, ["Black Friday (27.11., in 11 Tagen)"])
    assert "Anlässe bald (nur nutzen, wenn es zum Thema passt): Black Friday" in prompt
    assert "Anlässe bald (nur nutzen, wenn es zum Thema passt): keine" in ideas._prompt(
        uhren, [], [], 3
    )


# --- weekly rules ------------------------------------------------------------------------


def test_rule_fills_weeks_and_respects_removed_days(db: Session, uhren: ContentProject) -> None:
    settings = get_settings()
    today = _today()
    rule, created = plan_rules.create(db, settings, uhren, 3)  # Thursday
    assert created
    days = sorted(db.scalars(select(EditorialDay.day).where(EditorialDay.rule_id == rule.id)))
    assert days and all(d.weekday() == 3 for d in days)
    assert len(days) in (4, 5) and days[0] >= today
    assert plan_rules.create(db, settings, uhren, 3) == (rule, False)

    removed = planning.remove_day(db, settings, days[1], uhren)
    assert removed is not None
    assert plan_rules.apply(db, settings) == 0  # not filled again
    assert days[1].isoformat() in rule.skipped_days

    later = today + timedelta(days=7)
    assert plan_rules.apply(db, settings, today=later) >= 1  # tops up the next week

    future = plan_rules.stop(db, settings, rule)
    assert future >= 1 and not rule.active
    assert plan_rules.apply(db, settings) == 0


def test_every_second_week(db: Session, uhren: ContentProject) -> None:
    rule = PlanRule(
        content_project_id=uhren.id, weekday=0, every_weeks=2, starts_on=date(2026, 11, 2)
    )
    days = plan_rules.days_of(rule, date(2026, 11, 3), date(2026, 12, 31))
    assert days[:3] == [date(2026, 11, 16), date(2026, 11, 30), date(2026, 12, 14)]


def test_rule_days_do_not_close_the_day_for_others(db: Session, uhren: ContentProject) -> None:
    settings = get_settings()
    gaming = db.scalar(select(ContentProject).where(ContentProject.slug == "gaming"))
    assert gaming is not None
    rule, _ = plan_rules.create(db, settings, uhren, 3)
    day = db.scalars(select(EditorialDay.day).where(EditorialDay.rule_id == rule.id)).first()
    assert day is not None
    assert planning.day_block(db, day, gaming.id) is None
    planning.add_day(db, settings, day, uhren, None, None)  # already there -> None
    other = day + timedelta(days=1)
    planning.add_day(db, settings, other, uhren, None, None)  # hand-made entry
    assert planning.day_block(db, other, gaming.id) is not None


def test_chat_weekly_rule_mock_with_channel_hint_and_undo(
    db: Session, make_user: MakeUser, uhren: ContentProject
) -> None:
    user = make_user()
    exchange = assistant.send(db, get_settings(), user, "Jeden Donnerstag Uhren")
    assert [a.tool for a in exchange.actions] == ["weekly_rule"]
    assert "Für Uhren fehlen noch Kanäle: YouTube (DE), TikTok (DE), Instagram (DE)" in (
        exchange.answer.text
    )
    rule = db.scalars(select(PlanRule)).one()
    assert rule.weekday == 3 and rule.active

    action = db.scalars(select(ChatAction).where(ChatAction.tool == "weekly_rule")).one()
    assistant.undo(db, get_settings(), user, action.id)
    assert not rule.active
    assert db.scalars(select(EditorialDay).where(EditorialDay.rule_id == rule.id)).all() == []

    again = assistant.send(db, get_settings(), user, "Jeden Freitag Kochen")
    assert "kenne ich noch nicht" in again.answer.text

    assistant.send(db, get_settings(), user, "Jeden Montag Uhren")
    stop = assistant.send(db, get_settings(), user, "Montags keine Uhren mehr")
    assert "beendet" in stop.actions[0].summary


# --- competitor radar --------------------------------------------------------------------


def test_normalize_handles() -> None:
    assert competitors.normalize("https://www.youtube.com/@WatchGuy/videos") == "@WatchGuy"
    assert competitors.normalize("@watch.guy") == "@watch.guy"
    assert competitors.normalize("watchguy") == "@watchguy"
    with pytest.raises(competitors.RadarError):
        competitors.normalize("x")


def test_mock_scan_marks_standout_and_feeds_idea_lab(db: Session, uhren: ContentProject) -> None:
    comp = competitors.add(db, uhren, "@uhrenkanal")
    assert competitors.add(db, uhren, "https://youtube.com/@uhrenkanal") is comp
    res = competitors.scan(db, get_settings())
    assert (res.checked, res.videos, res.outliers, res.items) == (1, 8, 1, 1)
    top = db.scalars(select(CompetitorVideo).order_by(CompetitorVideo.views.desc())).first()
    assert top is not None and top.outlier and top.outlier >= 3 and top.is_mock
    item = db.get(ResearchItem, top.research_item_id)
    assert item is not None and item.title.startswith("Läuft bei Testkanal @uhrenkanal")
    assert "Nicht nachmachen" in (item.summary or "") and item.is_mock
    assert competitors.scan(db, get_settings()).items == 0  # once only
    assert [v.id for v, _ in competitors.standouts(db, uhren.id)] == [top.id]


class FakeYouTube:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, list[str]]]] = []

    def client(self) -> httpx.Client:
        def handler(req: httpx.Request) -> httpx.Response:
            path = urlparse(str(req.url)).path.rsplit("/", 1)[-1]
            q = parse_qs(urlparse(str(req.url)).query)
            self.calls.append((path, q))
            if path == "channels":
                if q["forHandle"] == ["@missing"]:
                    return httpx.Response(200, json={"items": []})
                return httpx.Response(200, json={"items": [{
                    "id": "UCabc", "snippet": {"title": "Uhren Profi"},
                    "contentDetails": {"relatedPlaylists": {"uploads": "UUabc"}},
                }]})  # fmt: skip
            if path == "playlistItems":
                ids = [{"contentDetails": {"videoId": f"v{i}"}} for i in range(5)]
                return httpx.Response(200, json={"items": ids})
            if path == "videos":
                now = datetime.now(UTC)
                items = [
                    {"id": f"v{i}", "snippet": {"title": f"Video {i}",
                     "publishedAt": (now - timedelta(days=i + 1)).isoformat()},
                     "statistics": {"viewCount": str(50000 if i == 0 else 8000 + i)}}
                    for i in range(5)
                ]  # fmt: skip
                return httpx.Response(200, json={"items": items})
            return httpx.Response(404)

        return httpx.Client(transport=httpx.MockTransport(handler))


def _live() -> Settings:
    return get_settings().model_copy(
        update={"trend_sources_mode": "live", "youtube_api_key": SecretStr("test-key-not-real")}
    )


def test_live_scan_uses_official_endpoints(db: Session, uhren: ContentProject) -> None:
    yt = FakeYouTube()
    comp = competitors.add(db, uhren, "@uhrenprofi")
    missing = competitors.add(db, uhren, "@missing")
    res = competitors.scan(db, _live(), client=yt.client())
    assert res.checked == 2 and res.errors == 1 and res.outliers == 1
    assert comp.name == "Uhren Profi" and comp.uploads_playlist_id == "UUabc"
    assert missing.last_error == "Kanal @missing nicht gefunden"
    paths = [p for p, _ in yt.calls]
    assert paths == ["channels", "playlistItems", "videos", "channels"]
    channels_q = yt.calls[0][1]
    assert channels_q["part"] == ["snippet,contentDetails"] and channels_q["key"] == [
        "test-key-not-real"
    ]
    assert yt.calls[2][1]["id"] == ["v0,v1,v2,v3,v4"]
    top = db.scalars(select(CompetitorVideo).where(CompetitorVideo.external_id == "v0")).one()
    assert top.url == "https://www.youtube.com/watch?v=v0" and not top.is_mock

    yt.calls.clear()
    competitors.scan(db, _live(), client=yt.client())
    assert [p for p, _ in yt.calls][:2] == ["playlistItems", "videos"]  # channel cached


def test_api_error_never_contains_the_key(db: Session, uhren: ContentProject) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}})

    comp = competitors.add(db, uhren, "@x_y_z")
    competitors.scan(db, _live(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert comp.last_error == "YouTube antwortet mit 403 quotaExceeded"
    assert "test-key" not in (comp.last_error or "")


# --- API -----------------------------------------------------------------------------------


def test_api_rules_events_calendar_and_radar(
    api: TestClient, db: Session, make_user: MakeUser, uhren: ContentProject, redis_client: Any
) -> None:
    make_user(email="op@example.com", role=UserRole.OPERATOR)
    headers = login(api, "op@example.com")

    r = api.post("/api/planning/rules", json={"project_id": uhren.id, "weekday": 3},
                 headers=headers)  # fmt: skip
    assert r.status_code == 201, r.text
    rule = r.json()
    assert rule["label"] == "jeden Donnerstag: Uhren"
    again = api.post(
        "/api/planning/rules", json={"project_id": uhren.id, "weekday": 3}, headers=headers
    )
    assert again.status_code == 409
    assert [x["id"] for x in api.get("/api/planning/rules").json()] == [rule["id"]]

    today = _today()
    cal = api.get(f"/api/planning/calendar?start={today}&end={today + timedelta(days=13)}").json()
    rule_entries = [e for d in cal["days"] for e in d["entries"] if e["from_rule"]]
    assert rule_entries and all(e["project"] == "Uhren" for e in rule_entries)

    ev = api.post(
        "/api/planning/events",
        json={"name": "Uhrenmesse", "day": str(today + timedelta(days=3)), "languages": ["de"],
              "project_id": uhren.id},
        headers=headers,
    )  # fmt: skip
    assert ev.status_code == 201, ev.text
    listed = api.get(
        f"/api/planning/events?start={today}&end={today + timedelta(days=10)}&language=de"
    ).json()
    assert any(e["name"] == "Uhrenmesse" and e["kind"] == "own" for e in listed)
    cal = api.get(f"/api/planning/calendar?start={today}&end={today + timedelta(days=5)}").json()
    assert any(e["name"] == "Uhrenmesse" for d in cal["days"] for e in d["events"])
    assert api.delete(f"/api/planning/events/{ev.json()['id']}", headers=headers).status_code == 204
    year = api.get("/api/planning/events?start=2026-11-01&end=2026-12-31").json()
    assert any(e["name"] == "Black Friday" and e["day"] == "2026-11-27" for e in year)

    assert api.delete(f"/api/planning/rules/{rule['id']}", headers=headers).status_code == 204
    assert api.get("/api/planning/rules").json() == []

    r = api.post("/api/competitors", json={"project_id": uhren.id, "handle": "@uhrentester"},
                 headers=headers)  # fmt: skip
    assert r.status_code == 201, r.text
    bad = api.post("/api/competitors", json={"project_id": uhren.id, "handle": "x"},
                   headers=headers)  # fmt: skip
    assert bad.status_code == 422
    competitors.scan(db, get_settings())
    radar = api.get(f"/api/competitors?project_id={uhren.id}").json()
    assert radar["live"] is False
    assert radar["competitors"][0]["videos"] == 8 and radar["competitors"][0]["standouts"] == 1
    assert radar["standouts"][0]["in_idea_lab"] is True
    run = api.post("/api/competitors/run", headers=headers)
    assert run.status_code == 200 and run.json()["job_id"]
    comp_id = radar["competitors"][0]["id"]
    assert api.delete(f"/api/competitors/{comp_id}", headers=headers).status_code == 204
    assert api.get("/api/competitors").json()["competitors"] == []
    assert db.get(Competitor, comp_id) is not None  # kept, only switched off
