"""Ausbau A11: trend alarm – signals, score, drafts, one-tap approval, autopilot.

YouTube is never contacted: live chart data comes from an ``httpx.MockTransport``.
Rendering is replaced by finished library videos, so the test stays fast.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import PlatformCode, ProductionStatus, UserRole, VideoStatus
from models import Channel, User
from models.access import Notification
from models.competitors import Competitor, CompetitorVideo
from models.library import OwnProduction
from models.production import Variant
from models.projects import ContentProject
from models.trend_alarms import TrendAlarm
from services import ai, own_production, trend_alarm
from services.seed import seed_base_data
from tests.conftest import login
from tests.integration.test_approval import landscape, make_channel, make_item, vertical

__all__ = ["landscape", "vertical"]  # fixtures used through pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed"),
]

MakeUser = Callable[..., User]
NOW = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(
        update={"media_root": str(tmp_path / "media"), "trend_autopilot_enabled": False}
    )


@pytest.fixture
def food(db: Session) -> ContentProject:
    seed_base_data(db)
    project = ContentProject(
        slug="ernaehrung",
        name="Ernährung",
        languages=["de"],
        subtopics=["Meal Prep", "Proteinriegel"],
        priority=200,
    )
    db.add(project)
    db.flush()
    return project


@pytest.fixture
def channels(db: Session, food: ContentProject) -> dict[PlatformCode, Channel]:
    return {
        code: make_channel(db, food, code)
        for code in (PlatformCode.YOUTUBE, PlatformCode.INSTAGRAM)
    }


def _signal(**kw: object) -> trend_alarm.Signal:
    base: dict[str, object] = {
        "key": "x",
        "project_id": 1,
        "source": "youtube_chart",
        "title": "Meal Prep Hype",
        "url": None,
        "creator": "Kanal",
        "published_at": NOW - timedelta(hours=8),
        "views": 2_400_000,
        "likes": 80_000,
        "comments": 6000,
        "chart_rank": 2,
        "region": "DE",
        "keyword": "Meal Prep",
    }
    base.update(kw)
    return trend_alarm.Signal(**base)  # type: ignore[arg-type]


def test_score_and_facts_are_transparent() -> None:
    hot = trend_alarm.score(_signal(), NOW, None)
    assert hot.score >= 75 and hot.views_per_hour == 300_000
    assert set(hot.parts) == set(trend_alarm.WEIGHTS)
    slow = trend_alarm.score(
        _signal(views=180_000, published_at=NOW - timedelta(hours=30), chart_rank=17), NOW, None
    )
    assert slow.score < 75
    # a paying campaign of the topic area lifts the score
    assert trend_alarm.score(_signal(), NOW, 4.0).score > hot.score

    lines = trend_alarm.facts(_signal(), hot, ("Riegel-Kampagne", 2.5))
    assert lines[0] == "2,4 Mio. Aufrufe in 8 Stunden (rund 300.000 pro Stunde)"
    assert "Platz 2 der YouTube-Trends in DE" in lines
    assert "Passende Kampagne: Riegel-Kampagne (2,50 $ je 1.000 Aufrufe)" in lines
    outlier = trend_alarm.facts(_signal(outlier=7.5, chart_rank=None, region=None), hot, None)
    assert "7,5× so viele Aufrufe wie sonst bei Kanal" in outlier


def test_keyword_match_is_word_based(food: ContentProject) -> None:
    assert trend_alarm._match(food, "Mein MEAL PREP für die Woche") == "Meal Prep"
    assert trend_alarm._match(food, "Ernährung im Winter") == "Ernährung"
    assert trend_alarm._match(food, "Mealprepping") is None
    assert not trend_alarm.is_gaming(food)


def test_scheduled_mock_run_stays_quiet_manual_run_alarms(
    db: Session, settings: Settings, food: ContentProject
) -> None:
    quiet = trend_alarm.scan(db, settings, now=NOW, render=False, project_id=food.id)
    assert quiet.alarms == [] and quiet.mode == "mock"

    res = trend_alarm.scan(db, settings, now=NOW, render=False, manual=True, project_id=food.id)
    assert len(res.alarms) == 1 and res.drafts == settings.trend_alarm_drafts
    alarm = db.get(TrendAlarm, res.alarms[0])
    assert alarm is not None and alarm.status == "drafting" and alarm.is_mock
    assert alarm.score >= settings.trend_alarm_threshold
    assert "Testdaten, kein echter Abruf" in alarm.facts
    assert [d["angle"] for d in alarm.drafts] == ["Kurz erklärt", "Meinung", "Drei Fakten"]
    prods = trend_alarm._productions(db, alarm)
    assert all(p.status == ProductionStatus.QUEUED and p.segments for p in prods)

    again = trend_alarm.scan(db, settings, now=NOW, render=False, manual=True, project_id=food.id)
    assert again.alarms == []  # the same video never alarms twice


def test_daily_limit(db: Session, settings: Settings, food: ContentProject) -> None:
    capped = settings.model_copy(update={"trend_alarm_max_per_day": 0})
    assert (
        trend_alarm.scan(db, capped, now=NOW, render=False, manual=True, project_id=food.id).alarms
        == []
    )


def test_competitor_outlier_alarms(db: Session, settings: Settings, food: ContentProject) -> None:
    comp = Competitor(
        content_project_id=food.id, platform=PlatformCode.YOUTUBE, handle="@riegel", name="Riegel"
    )
    db.add(comp)
    db.flush()
    db.add(
        CompetitorVideo(
            competitor_id=comp.id,
            external_id="abc",
            title="Proteinriegel selbst machen",
            url="https://www.youtube.com/watch?v=abc",
            published_at=NOW - timedelta(hours=5),
            views=900_000,
            outlier=9.0,
        )
    )
    db.flush()
    res = trend_alarm.scan(db, settings, now=NOW, render=False)
    assert len(res.alarms) == 1
    alarm = db.get(TrendAlarm, res.alarms[0])
    assert alarm is not None and alarm.source == "competitor" and not alarm.is_mock
    assert any("9,0× so viele Aufrufe wie sonst bei Riegel" in f for f in alarm.facts)


def test_live_chart_uses_official_api(
    db: Session, settings: Settings, food: ContentProject
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        published = (NOW - timedelta(hours=6)).isoformat().replace("+00:00", "Z")
        items = [
            {
                "id": "v1",
                "snippet": {
                    "title": "Meal Prep für 5 Euro",
                    "channelTitle": "Großer Kanal",
                    "publishedAt": published,
                },
                "statistics": {"viewCount": "3000000", "likeCount": "1", "commentCount": "2"},
            },
            {
                "id": "v2",
                "snippet": {"title": "Autos", "publishedAt": published},
                "statistics": {"viewCount": "9000000"},
            },
        ]
        return httpx.Response(200, json={"items": items})

    live = settings.model_copy(
        update={
            "youtube_api_key": SecretStr("k"),
            "trend_sources_mode": "live",
            "trend_alarm_regions": "DE",
        }
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    res = trend_alarm.scan(db, live, now=NOW, client=client, render=False, project_id=food.id)
    assert len(seen) == 1  # no gaming topic area: no category request
    params = seen[0].url.params
    assert params["chart"] == "mostPopular" and params["regionCode"] == "DE"
    assert seen[0].url.path.endswith("/youtube/v3/videos")
    assert len(res.alarms) == 1
    alarm = db.get(TrendAlarm, res.alarms[0])
    assert alarm is not None and alarm.url == "https://www.youtube.com/watch?v=v1"
    assert alarm.creator == "Großer Kanal" and alarm.metrics["keyword"] == "Meal Prep"

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}})

    bad = trend_alarm.collect(
        db, live, [food], NOW, httpx.Client(transport=httpx.MockTransport(broken))
    )
    assert bad[1] == ["YouTube-Trends DE: YouTube antwortet mit 403 quotaExceeded"]


def test_ai_blocked_still_alarms(
    db: Session, settings: Settings, food: ContentProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    def blocked(*a: object, **kw: object) -> None:
        raise ai.AIBlockedError("budget", "Monatsbudget erreicht")

    monkeypatch.setattr(own_production, "draft_script", blocked)
    res = trend_alarm.scan(db, settings, now=NOW, render=False, manual=True, project_id=food.id)
    alarm = db.get(TrendAlarm, res.alarms[0])
    assert alarm is not None and alarm.status == "failed" and "Monatsbudget" in (alarm.error or "")
    note = db.scalar(select(Notification).where(Notification.kind == "trend"))
    assert note is not None and "Monatsbudget" in (note.body or "")


def _render_all(
    db: Session, settings: Settings, food: ContentProject, alarm: TrendAlarm, video: Path
) -> list[OwnProduction]:
    prods = trend_alarm._productions(db, alarm)
    for prod in prods:
        copy = video.parent / f"draft-{prod.id}.mp4"  # one file each (unique checksum)
        copy.write_bytes(video.read_bytes() + prod.id.to_bytes(8, "big"))
        item = make_item(db, settings, food, copy)
        prod.status = ProductionStatus.DONE
        prod.output_item_id = item.id
    db.flush()
    for prod in prods:
        trend_alarm.on_production_done(db, settings, prod)
    return prods


def test_drafts_become_posts_and_one_tap_approves(
    api: TestClient,
    make_user: MakeUser,
    db: Session,
    settings: Settings,
    food: ContentProject,
    channels: dict[PlatformCode, Channel],
    vertical: Path,
) -> None:
    res = trend_alarm.scan(db, settings, now=NOW, render=False, manual=True, project_id=food.id)
    alarm = db.get(TrendAlarm, res.alarms[0])
    assert alarm is not None
    prods = trend_alarm._productions(db, alarm)
    prods[0].status = ProductionStatus.DONE
    db.flush()
    trend_alarm.on_production_done(db, settings, prods[0])
    assert alarm.status == "drafting"  # waits for the other drafts

    prods = _render_all(db, settings, food, alarm, vertical)
    assert alarm.status == "ready" and not alarm.autopilot
    variants = trend_alarm.alarm_variants(db, alarm.id)
    assert len(variants) == len(prods) * len(channels)
    assert all(v.status == VideoStatus.QUALITY_APPROVED for v in variants)
    note = db.scalar(select(Notification).where(Notification.kind == "trend"))
    assert note is not None and note.link == f"/trend-alarm?alarm={alarm.id}"
    assert "3 Entwürfe bereit" in (note.body or "") and "Aufrufe" in (note.body or "")
    db.commit()

    make_user(role=UserRole.VIEWER, email="viewer@example.com")
    viewer = login(api, "viewer@example.com")
    chosen = prods[1].id
    url = f"/api/trend-alarms/{alarm.id}/approve"
    denied = api.post(url, json={"production_id": chosen}, headers=viewer)
    assert denied.status_code == 403

    make_user(role=UserRole.OPERATOR, email="op@example.com")
    op = login(api, "op@example.com")
    listing = api.get("/api/trend-alarms").json()
    assert listing[0]["id"] == alarm.id and len(listing[0]["drafts"]) == 3
    assert len(listing[0]["drafts"][0]["posts"]) == 2
    assert api.post(url, json={"production_id": 999999}, headers=op).status_code == 404

    out = api.post(url, json={"production_id": chosen}, headers=op)
    assert out.status_code == 200, out.text
    assert out.json()["status"] == "approved"
    db.expire_all()
    for v in trend_alarm.alarm_variants(db, alarm.id):
        mine = v.concept["production_id"] == chosen
        assert v.status == (VideoStatus.READY_TO_PUBLISH if mine else VideoStatus.ARCHIVED)
    again = api.post(f"/api/trend-alarms/{alarm.id}/dismiss", headers=op)
    assert again.status_code == 409


def test_autopilot_needs_both_switches(
    db: Session,
    settings: Settings,
    food: ContentProject,
    channels: dict[PlatformCode, Channel],
    vertical: Path,
) -> None:
    channels[PlatformCode.YOUTUBE].trend_autopilot = True
    res = trend_alarm.scan(db, settings, now=NOW, render=False, manual=True, project_id=food.id)
    alarm = db.get(TrendAlarm, res.alarms[0])
    assert alarm is not None
    _render_all(db, settings, food, alarm, vertical)
    assert not alarm.autopilot  # global switch off: everything waits for a person
    assert all(
        v.status == VideoStatus.QUALITY_APPROVED for v in trend_alarm.alarm_variants(db, alarm.id)
    )

    on = settings.model_copy(
        update={"trend_autopilot_enabled": True, "trend_autopilot_min_score": 70}
    )
    res = trend_alarm.scan(
        db, on, now=NOW + timedelta(days=1), render=False, manual=True, project_id=food.id
    )
    alarm2 = db.get(TrendAlarm, res.alarms[0])
    assert alarm2 is not None
    prods = _render_all(db, on, food, alarm2, vertical)
    assert alarm2.autopilot and alarm2.status == "ready"  # Instagram still waits
    yt = channels[PlatformCode.YOUTUBE].id
    by_state = {
        (v.channel_id, v.concept["production_id"]): v.status
        for v in trend_alarm.alarm_variants(db, alarm2.id)
    }
    assert by_state[(yt, prods[0].id)] == VideoStatus.READY_TO_PUBLISH
    assert by_state[(yt, prods[1].id)] == VideoStatus.ARCHIVED
    ig = channels[PlatformCode.INSTAGRAM].id
    assert by_state[(ig, prods[0].id)] == VideoStatus.QUALITY_APPROVED
    note = db.scalars(
        select(Notification).where(Notification.dedup_key == f"trend-alarm-{alarm2.id}")
    ).one()
    assert "Automatisch freigegeben für" in (note.body or "")

    low = on.model_copy(update={"trend_autopilot_min_score": 100})
    res = trend_alarm.scan(
        db, low, now=NOW + timedelta(days=2), render=False, manual=True, project_id=food.id
    )
    alarm3 = db.get(TrendAlarm, res.alarms[0])
    assert alarm3 is not None
    _render_all(db, low, food, alarm3, vertical)
    assert not alarm3.autopilot  # below the autopilot score


def test_api_info_dismiss_and_autopilot_switch(
    api: TestClient,
    make_user: MakeUser,
    db: Session,
    settings: Settings,
    food: ContentProject,
    channels: dict[PlatformCode, Channel],
) -> None:
    res = trend_alarm.scan(db, settings, now=NOW, render=False, manual=True, project_id=food.id)
    db.commit()
    make_user(role=UserRole.OPERATOR, email="op2@example.com")
    op = login(api, "op2@example.com")
    info = api.get("/api/trend-alarms/info").json()
    assert info["autopilot_enabled"] is False and info["mode"] == "mock"
    assert {c["platform"] for c in info["channels"] if c["project"] == "Ernährung"} == {
        "youtube",
        "instagram",
    }
    yt = channels[PlatformCode.YOUTUBE].id
    assert (
        api.patch(f"/api/trend-alarms/autopilot/{yt}", json={"enabled": True}, headers=op)
    ).status_code == 403

    out = api.post(f"/api/trend-alarms/{res.alarms[0]}/dismiss", headers=op)
    assert out.status_code == 200 and out.json()["status"] == "dismissed"
    assert api.get("/api/trend-alarms").json() == []
    assert len(api.get("/api/trend-alarms", params={"view": "all"}).json()) == 1

    make_user(role=UserRole.ADMIN, email="admin@example.com")
    admin = login(api, "admin@example.com")
    on = api.patch(f"/api/trend-alarms/autopilot/{yt}", json={"enabled": True}, headers=admin)
    assert on.status_code == 200 and on.json()["trend_autopilot"] is True
    db.expire_all()
    channel = db.get(Channel, yt)
    assert channel is not None and channel.trend_autopilot
    assert json.loads(json.dumps(info))  # plain JSON


def test_sweep_finishes_stuck_drafts_and_expires(
    db: Session, settings: Settings, food: ContentProject
) -> None:
    res = trend_alarm.scan(db, settings, now=NOW, render=False, manual=True, project_id=food.id)
    alarm = db.get(TrendAlarm, res.alarms[0])
    assert alarm is not None
    later = datetime.now(UTC) + timedelta(hours=3)
    finished, _ = trend_alarm.sweep(db, settings, later)
    assert finished == 1 and alarm.status == "failed"  # nothing was rendered

    alarm.status = "ready"
    db.flush()
    _, expired = trend_alarm.sweep(db, settings, datetime.now(UTC) + timedelta(days=3))
    assert expired == 1 and alarm.status == "expired"
    assert db.scalar(select(Variant).where(Variant.concept["trend_alarm_id"].isnot(None))) is None
