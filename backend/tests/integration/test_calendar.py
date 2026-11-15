"""Editorial calendar (extension phase E6): plan drives topic area per day, amount stays dynamic."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.enums import PublishingJobStatus, UserRole
from models import Channel, User
from models.control import AgentDecision
from models.planning import ContentFocus, EditorialDay
from models.projects import ContentProject
from services import planning, strategy
from tests.conftest import login
from tests.factories import build_chain
from tests.integration.test_publishing_strategy import (
    MORNING,
    jobs,
    plan,
    ready_variants,
)

pytestmark = pytest.mark.integration

MakeUser = Callable[..., User]
DAY = date(2026, 11, 16)  # the local day of MORNING


@pytest.fixture
def channel(db: Session) -> Channel:
    ch = build_chain(db).channel
    ch.is_paused, ch.min_posts_per_day, ch.max_posts_per_day = False, 0, 4
    ch.min_interval_minutes = 90
    ch.platform.is_paused = False
    db.flush()
    return ch


@pytest.fixture
def food(db: Session) -> ContentProject:
    project = ContentProject(slug="ernaehrung", name="Ernährung", languages=["de"], priority=200)
    db.add(project)
    db.flush()
    return project


def _plan_day(db: Session, day: date, project_id: int) -> EditorialDay:
    entry = EditorialDay(day=day, content_project_id=project_id)
    db.add(entry)
    db.flush()
    return entry


# --- effect on the Publishing Strategy Agent -----------------------------------------


def test_day_planned_for_another_area_gets_no_posts(
    db: Session, channel: Channel, food: ContentProject
) -> None:
    ready_variants(db, 3, channel)
    _plan_day(db, DAY, food.id)
    out = plan(db, channel, MORNING)
    assert out["planned"] == [] and "Redaktionsplan" in out["blocked"]
    assert "nur Ernährung" in out["blocked"]
    # the amount itself is still decided from the data, not by the plan
    version = strategy.latest_version(db, channel.id)
    assert version is not None and version.posts_per_day == 1


def test_day_planned_for_the_channels_area_posts_normally(
    db: Session, channel: Channel, food: ContentProject
) -> None:
    ready_variants(db, 3, channel)
    _plan_day(db, DAY, food.id)
    _plan_day(db, DAY, channel.content_project_id)
    out = plan(db, channel, MORNING)
    assert out["blocked"] is None and len(out["planned"]) == 1


def test_plan_change_takes_back_planned_posts(
    db: Session, channel: Channel, food: ContentProject
) -> None:
    ready_variants(db, 3, channel)
    plan(db, channel, MORNING)
    assert len(jobs(db, channel, PublishingJobStatus.SCHEDULED)) == 1
    _plan_day(db, DAY, food.id)
    out = plan(db, channel, MORNING + timedelta(minutes=30))
    assert len(out["unscheduled"]) == 1 and "Redaktionsplan" in out["unscheduled"][0]["reason"]
    assert jobs(db, channel, PublishingJobStatus.SCHEDULED) == []


def test_focus_topic_gets_priority(db: Session, channel: Channel) -> None:
    normal, gta = ready_variants(db, 2, channel)
    normal.quality_score, gta.quality_score = 0.9, 0.85
    gta.title = "GTA 6: der neue Trailer"
    db.add(
        ContentFocus(
            content_project_id=channel.content_project_id,
            topic="GTA 6",
            starts_on=DAY,
            ends_on=DAY + timedelta(days=6),
        )
    )
    db.flush()
    out = plan(db, channel, MORNING)
    assert [p["variant_id"] for p in out["planned"]] == [gta.id]
    reason = db.scalars(
        select(AgentDecision.reasoning).where(AgentDecision.decision_type == "scheduled")
    ).one()
    assert reason is not None and "Schwerpunkt GTA 6" in reason


def test_day_block_without_entries_is_open(db: Session, food: ContentProject) -> None:
    assert planning.day_block(db, DAY, food.id) is None
    _plan_day(db, DAY, food.id)
    assert planning.day_block(db, DAY, food.id) is None
    assert planning.day_block(db, DAY, food.id + 999) is not None


# --- API -----------------------------------------------------------------------------


def test_calendar_shows_entries_videos_and_focus(
    api: TestClient, make_user: MakeUser, db: Session, channel: Channel, food: ContentProject
) -> None:
    ready_variants(db, 2, channel)
    plan(db, channel, MORNING)
    _plan_day(db, DAY, channel.content_project_id)
    make_user(role=UserRole.VIEWER, email="v@example.com")
    login(api, "v@example.com")
    r = api.get("/api/planning/calendar", params={"start": "2026-11-16", "end": "2026-11-22"})
    assert r.status_code == 200, r.text
    data = r.json()
    monday = data["days"][0]
    assert monday["weekday"] == "Montag" and len(data["days"]) == 7
    assert [e["project"] for e in monday["entries"]] == ["Gaming"]
    [video] = monday["videos"]
    assert video["status"] == "scheduled" and video["is_mock"] is True
    assert video["channel"] == channel.name

    only_food = api.get(
        "/api/planning/calendar",
        params={"start": "2026-11-16", "end": "2026-11-22", "project_id": food.id},
    ).json()
    assert only_food["days"][0]["entries"] == [] and only_food["days"][0]["videos"] == []
    too_long = api.get(
        "/api/planning/calendar", params={"start": "2026-11-01", "end": "2027-01-15"}
    )
    assert too_long.status_code == 422


def test_add_move_and_remove_plan_entries(
    api: TestClient, make_user: MakeUser, db: Session, food: ContentProject
) -> None:
    make_user(role=UserRole.VIEWER, email="v@example.com")
    viewer = login(api, "v@example.com")
    today = planning.today(get_settings())
    body = {"day": today.isoformat(), "project_id": food.id, "note": "Rezepte"}
    assert api.post("/api/planning/days", json=body, headers=viewer).status_code == 403
    api.cookies.clear()
    make_user(role=UserRole.OPERATOR, email="op@example.com")
    op = login(api, "op@example.com")

    r = api.post("/api/planning/days", json=body, headers=op)
    assert r.status_code == 201, r.text
    entry = r.json()
    assert entry["project"] == "Ernährung" and entry["note"] == "Rezepte"
    assert api.post("/api/planning/days", json=body, headers=op).status_code == 409

    later = today + timedelta(days=2)
    r = api.patch(f"/api/planning/days/{entry['id']}", json={"day": later.isoformat()}, headers=op)
    assert r.status_code == 200, r.text
    assert db.get(EditorialDay, entry["id"]).day == later  # type: ignore[union-attr]

    other = api.post("/api/planning/days", json={**body, "note": None}, headers=op).json()
    clash = api.patch(
        f"/api/planning/days/{other['id']}", json={"day": later.isoformat()}, headers=op
    )
    assert clash.status_code == 409
    r = api.patch(f"/api/planning/days/{other['id']}", json={"note": "Meal Prep"}, headers=op)
    assert r.json()["note"] == "Meal Prep"

    far = today + timedelta(days=400)
    r = api.post("/api/planning/days", json={**body, "day": far.isoformat()}, headers=op)
    assert r.status_code == 422

    assert api.delete(f"/api/planning/days/{entry['id']}", headers=op).status_code == 204
    assert db.get(EditorialDay, entry["id"]) is None


def test_focus_api(api: TestClient, make_user: MakeUser, db: Session, food: ContentProject) -> None:
    make_user(role=UserRole.OPERATOR, email="op@example.com")
    op = login(api, "op@example.com")
    today = planning.today(get_settings())
    body = {
        "project_id": food.id,
        "topic": "Meal Prep",
        "starts_on": today.isoformat(),
        "ends_on": (today + timedelta(days=6)).isoformat(),
    }
    r = api.post("/api/planning/focus", json=body, headers=op)
    assert r.status_code == 201, r.text
    focus_id = r.json()["id"]
    bad = {**body, "ends_on": (today - timedelta(days=1)).isoformat()}
    assert api.post("/api/planning/focus", json=bad, headers=op).status_code == 422
    assert api.delete(f"/api/planning/focus/{focus_id}", headers=op).status_code == 204
    assert db.get(ContentFocus, focus_id) is None
