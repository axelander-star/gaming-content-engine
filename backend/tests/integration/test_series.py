"""Video series: outline, part scripts, rendering, approval and the release pace.

The AI runs in mock mode, publishing in mock mode; nothing leaves the machine.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import (
    AgentRunStatus,
    IdeaStatus,
    Language,
    LibraryOrigin,
    PlatformCode,
    ProductionStatus,
    UserRole,
    VideoStatus,
)
from models import Channel, User
from models.library import OwnProduction, ProductionSeries
from models.production import Variant
from models.projects import ContentProject
from models.publishing import PublishingJob, StrategyVersion
from models.research import Idea
from services import approval, media, orchestrator, series
from tests.conftest import login
from tests.integration.test_approval import make_channel, make_item

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed"),
]

MakeUser = Callable[..., User]
BERLIN = ZoneInfo("Europe/Berlin")
SATURDAY = datetime(2026, 11, 21, 7, 0, tzinfo=UTC)  # 08:00 in Berlin
TUESDAY = datetime(2026, 11, 24, 7, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def vertical(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("series") / "vertical.mp4"
    return media.make_test_video(
        get_settings(), path, width=720, height=1280, calm_s=2, action_s=2, tail_s=1
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(
        update={"media_root": str(tmp_path / "media"), "render_preset": "ultrafast"}
    )


@pytest.fixture
def client(api: TestClient, settings: Settings) -> Iterator[TestClient]:
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    yield api


@pytest.fixture
def op(client: TestClient, make_user: MakeUser) -> dict[str, str]:
    make_user("op@example.com", UserRole.OPERATOR)
    return login(client, "op@example.com")


@pytest.fixture
def science(db: Session) -> ContentProject:
    from services.seed import seed_base_data

    seed_base_data(db)
    project = ContentProject(slug="wissen", name="Wissen", languages=["de"], priority=200)
    db.add(project)
    db.flush()
    return project


@pytest.fixture
def channel(db: Session, science: ContentProject) -> Channel:
    return make_channel(db, science, PlatformCode.YOUTUBE)


# --- pure rules ----------------------------------------------------------------------------


def test_part_count_and_outline_parsing() -> None:
    assert series.part_count(None, 60, 90) == 30  # one hour of 1.5-minute parts, capped
    assert series.part_count(None, 30, 90) == 20
    assert series.part_count(50, None, 90) == series.MAX_PARTS
    assert series.part_count(None, None, 90) is None
    title, parts = series.parse_outline(
        'x {"title": "Welt", "parts": [{"title": "A"}, {"title": "B"}, 3, {"title": "C"}]}', 2
    )
    assert title == "Welt" and [p["title"] for p in parts] == ["A", "B"]
    with pytest.raises(series.SeriesError):
        series.parse_outline('{"parts": [{"title": "nur einer"}]}', None)
    with pytest.raises(series.SeriesError):
        series.parse_outline("keine Gliederung", None)


def test_pace_follows_the_numbers() -> None:
    tue, sat = date(2026, 11, 24), date(2026, 11, 28)
    base = series.pace(tue, 10, [], {}, None, 0, None)
    assert base.per_day == 1 and "Grundtakt" in base.reasons[0]
    # no own weekday data yet: one more part at the weekend, marked as an assumption
    weekend = series.pace(sat, 10, [], {}, None, 0, None)
    assert weekend.per_day == 2 and "Annahme" in weekend.reasons[-1]
    assert series.pace(sat, 2, [], {}, None, 0, None).per_day == 1  # short series: no extra
    # strong parts speed up, weak ones get a rest day
    assert series.pace(tue, 10, [1.6, 1.4], {}, None, 2, None).per_day == 2
    weak = series.pace(tue, 10, [0.4, 0.5], {}, None, 2, tue - timedelta(days=1))
    assert weak.per_day == 0 and "Pause" in weak.reasons[0]
    assert series.pace(tue, 10, [0.4, 0.5], {}, None, 2, tue - timedelta(days=2)).per_day == 1
    # the channel's own strong weekday counts, the weekend assumption is then gone
    days = {1: 1.5, 2: 1.0, 3: 0.9, 5: 0.8}
    strong = series.pace(tue, 10, [], days, None, 0, None)
    assert strong.per_day == 2 and "Dienstag" in strong.reasons[-1]
    assert series.pace(sat, 10, [], days, None, 0, None).per_day == 1
    # a hot topic starts strong; never more than the cap or the parts left
    assert series.pace(sat, 10, [1.5, 1.5], {}, 90, 0, None).per_day == series.MAX_PER_DAY
    assert series.pace(tue, 1, [1.5, 1.5], {}, 90, 0, None).per_day == 1
    assert series.pace(tue, 0, [], {}, None, 0, None).per_day == 0


# --- API: from topic to finished parts ------------------------------------------------------


def test_series_from_topic_to_approved_parts(
    client: TestClient,
    op: dict[str, str],
    db: Session,
    settings: Settings,
    science: ContentProject,
    channel: Channel,
) -> None:
    r = client.post(
        "/api/series",
        json={
            "project_id": science.id,
            "topic": "Wie entsteht die Welt",
            "parts": 3,
            "part_seconds": 45,
        },
        headers=op,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["title"] == "Wie entsteht die Welt" and data["counts"]["parts"] == 3
    assert [p["part"] for p in data["parts"]] == [1, 2, 3]
    first = data["parts"][0]["production"]
    assert first["title"].startswith("Wie entsteht die Welt – Teil 1:")
    assert first["script_source"] == "pending" and first["series_part"] == 1
    # parts are not listed as single productions
    assert client.get("/api/productions", params={"project_id": science.id}).json() == []
    # rendering needs all scripts first
    assert client.post(f"/api/series/{data['id']}/render", headers=op).status_code == 409

    r = client.post(f"/api/series/{data['id']}/scripts", headers=op)
    assert r.status_code == 200 and r.json()["remaining"] == 0, r.text
    parts = r.json()["series"]["parts"]
    for p in parts:
        segs = p["production"]["segments"]
        assert p["production"]["script_source"] == "mock" and 3 <= len(segs) <= 12
    assert parts[0]["production"]["segments"][0]["headline"].startswith("Teil 1")
    assert "nächsten Teil" in parts[0]["production"]["segments"][-1]["text"]
    assert "ganze Serie" in parts[-1]["production"]["segments"][-1]["text"]

    r = client.post(f"/api/series/{data['id']}/render", headers=op)
    assert r.status_code == 200 and r.json()["queued"] == 3, r.text
    for p in parts:
        run = orchestrator.run_agent(
            db, settings, "own_production",
            {"entity_type": "own_productions", "entity_id": p["production"]["id"]},
        )  # fmt: skip
        assert run.status == AgentRunStatus.SUCCEEDED, run.output
    out = client.get(f"/api/series/{data['id']}").json()
    assert out["counts"]["done"] == 3
    durations = [p["production"]["duration_s"] for p in out["parts"]]
    assert all(d is not None and 35 <= d <= 120 for d in durations), durations

    r = client.post(f"/api/series/{data['id']}/prepare", json={"approve": True}, headers=op)
    assert r.status_code == 200, r.text
    assert r.json()["prepared"] == 3 and r.json()["approved"] == 3
    assert r.json()["series"]["counts"]["approved"] == 3
    # a second call changes nothing
    r = client.post(f"/api/series/{data['id']}/prepare", json={"approve": True}, headers=op)
    assert r.json()["prepared"] == 0 and r.json()["approved"] == 0

    plan = client.get(f"/api/series/{data['id']}/plan").json()
    assert len(plan) == 1 and plan[0]["channel_id"] == channel.id
    days = plan[0]["days"]
    assert sorted(n for d in days for n in d["parts"]) == [1, 2, 3]
    assert all(len(d["parts"]) <= series.MAX_PER_DAY for d in days)
    assert len(days) >= 2  # never everything on one day

    r = client.patch(f"/api/series/{data['id']}", json={"paused": True}, headers=op)
    assert r.status_code == 200 and r.json()["paused"] is True
    assert client.get(f"/api/series/{data['id']}/plan").json()[0]["days"] == []


def test_series_from_idea_checks_area_and_viewer_cannot_change(
    client: TestClient,
    op: dict[str, str],
    db: Session,
    make_user: MakeUser,
    science: ContentProject,
) -> None:
    other = ContentProject(slug="kochen", name="Kochen", languages=["de"], priority=300)
    db.add(other)
    db.flush()

    def idea(project: ContentProject, state: IdeaStatus, trend: int = 80) -> Idea:
        row = Idea(
            content_project_id=project.id, title="Die Geschichte der Sterne",
            pitch="Wie Sterne entstehen und vergehen.", format="short", sources=[],
            trend_score=trend, fit_score=70, effort_score=50, rights_risk=10, score=75,
            reasoning="x", status=state, provider="mock",
        )  # fmt: skip
        db.add(row)
        db.flush()
        return row

    foreign = idea(other, IdeaStatus.ACCEPTED)
    r = client.post("/api/series", json={"project_id": science.id, "idea_id": foreign.id},
                    headers=op)  # fmt: skip
    assert r.status_code == 409
    good = idea(science, IdeaStatus.NEW)
    r = client.post("/api/series", json={"project_id": science.id, "idea_id": good.id},
                    headers=op)  # fmt: skip
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["topic"] == "Die Geschichte der Sterne" and created["idea_id"] == good.id
    assert created["counts"]["parts"] == 6  # the mock AI picks six parts
    row = db.get(ProductionSeries, created["id"])
    assert row is not None and series.trend_of(db, row) == 80

    # suggestions: the idea is already a series, templates fill up; no AI call
    sugg = client.get("/api/series/suggestions", params={"project_id": science.id}).json()
    titles = [s["title"] for s in sugg]
    assert "Die Geschichte der Sterne" not in titles
    assert any(s["source"] == "template" for s in sugg) and len(sugg) <= 8
    fresh = client.post("/api/series/suggestions", params={"project_id": science.id}, headers=op)
    assert fresh.status_code == 200 and len(fresh.json()) >= 3

    client.cookies.clear()
    make_user("v@example.com", UserRole.VIEWER)
    viewer = login(client, "v@example.com")
    assert client.get(f"/api/series/{created['id']}").status_code == 200
    for method, path in (
        ("post", "/api/series"),
        ("post", f"/api/series/{created['id']}/scripts"),
        ("post", f"/api/series/{created['id']}/render"),
        ("delete", f"/api/series/{created['id']}"),
    ):
        kw = {"json": {"project_id": science.id, "topic": "X Y Z"}} if path == "/api/series" else {}
        assert getattr(client, method)(path, headers=viewer, **kw).status_code == 403

    client.cookies.clear()
    op2 = login(client, "op@example.com")
    assert client.delete(f"/api/series/{created['id']}", headers=op2).status_code == 204
    assert db.scalar(select(OwnProduction).where(OwnProduction.series_id == created["id"])) is None


# --- release: order and pace inside the Publishing Strategy Agent -------------------------------


def _series_with_parts(
    db: Session, settings: Settings, project: ContentProject, vertical: Path, n: int
) -> tuple[ProductionSeries, list[OwnProduction]]:
    row = ProductionSeries(
        content_project_id=project.id, title="Wie entsteht die Welt", topic="Wie entsteht die Welt",
        language=Language.DE, part_seconds=60,
        outline=[{"title": f"Kapitel {i}", "summary": ""} for i in range(1, n + 1)],
        script_source="mock",
    )  # fmt: skip
    db.add(row)
    db.flush()
    prods = []
    for i in range(1, n + 1):
        item = make_item(
            db, settings, project, vertical, origin=LibraryOrigin.GENERATED,
            rights={"kind": "generated", "third_party_video": False},
        )  # fmt: skip
        item.original_sha256 = f"{item.original_sha256[:-4]}{i:04d}"  # distinct files
        item.title = f"Wie entsteht die Welt – Teil {i}"
        db.flush()
        prod = OwnProduction(
            content_project_id=project.id, title=item.title, language=Language.DE,
            status=ProductionStatus.DONE, segments=[{"headline": "", "text": "x"}],
            script_source="mock", output_item_id=item.id, series_id=row.id, series_part=i,
        )  # fmt: skip
        db.add(prod)
        prods.append(prod)
    db.flush()
    return row, prods


def _post(db: Session, settings: Settings, prod: OwnProduction, channel: Channel) -> Variant:
    assert prod.output_item_id is not None
    (v,) = approval.prepare(db, settings, prod.output_item_id, [channel.id], None)
    return v


def _plan_day(
    db: Session, settings: Settings, channel: Channel, now: datetime, amount: int
) -> None:
    latest = db.scalar(
        select(StrategyVersion)
        .where(StrategyVersion.channel_id == channel.id)
        .order_by(StrategyVersion.version.desc())
        .limit(1)
    )
    db.add(
        StrategyVersion(
            channel_id=channel.id, version=(latest.version + 1) if latest else 1,
            planned_for=now.astimezone(BERLIN).date(), posts_per_day=amount,
            params={}, reasons=["Test"], inputs={}, created_by="test",
        )
    )  # fmt: skip
    db.flush()
    run = orchestrator.run_agent(
        db, settings, "publishing_strategy",
        {"sweep": True, "channel_id": channel.id, "now": now.isoformat()},
    )  # fmt: skip
    assert run.status == AgentRunStatus.SUCCEEDED, run.output


def _scheduled(db: Session, variants: list[Variant]) -> list[int]:
    ids = {v.id: i + 1 for i, v in enumerate(variants)}
    jobs = db.scalars(select(PublishingJob).where(PublishingJob.variant_id.in_(list(ids))))
    return sorted(ids[j.variant_id] for j in jobs)


def test_parts_go_out_in_order_and_spread_over_days(
    db: Session, settings: Settings, science: ContentProject, channel: Channel, vertical: Path
) -> None:
    row, prods = _series_with_parts(db, settings, science, vertical, 5)
    variants = [_post(db, settings, p, channel) for p in prods]
    # part 1 is not approved yet: nothing of the series may go out
    for v in variants[1:]:
        approval.approve(db, v, None)
    db.flush()
    _plan_day(db, settings, channel, TUESDAY, 3)
    assert _scheduled(db, variants) == []
    release = series.allowed_today(
        db, row, channel.id, TUESDAY.date(), series.channel_data(db, settings, channel)
    )
    assert release.allowed == [] and "Teil 1" in release.held[variants[1].id]

    approval.approve(db, variants[0], None)
    db.flush()
    # Tuesday: one part, although the channel could post three today
    _plan_day(db, settings, channel, TUESDAY + timedelta(minutes=5), 3)
    assert _scheduled(db, variants) == [1]
    job = db.scalar(select(PublishingJob).where(PublishingJob.variant_id == variants[0].id))
    assert job is not None and job.decided_by_decision_id is not None


def test_weekend_gets_two_parts_but_the_channel_amount_wins(
    db: Session, settings: Settings, science: ContentProject, channel: Channel, vertical: Path
) -> None:
    _, prods = _series_with_parts(db, settings, science, vertical, 5)
    variants = [_post(db, settings, p, channel) for p in prods]
    for v in variants:
        approval.approve(db, v, None)
    db.flush()
    _plan_day(db, settings, channel, SATURDAY, 1)
    assert _scheduled(db, variants) == [1]  # channel amount 1 limits the series
    _plan_day(db, settings, channel, SATURDAY + timedelta(minutes=5), 3)
    assert _scheduled(db, variants) == [1, 2]  # weekend: two parts, still in order
    assert all(v.status == VideoStatus.SCHEDULED for v in variants[:2])
    assert all(v.status == VideoStatus.READY_TO_PUBLISH for v in variants[2:])
