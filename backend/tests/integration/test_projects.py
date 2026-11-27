"""Content projects (topic areas) and the rule that content stays on its project's channels."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agents import registry
from agents.gameplay_analysis import primary_channel
from core.config import get_settings
from core.enums import (
    ChannelAuthStatus,
    ContentProjectStatus,
    Language,
    MaterialStatus,
    PlatformCode,
    PublishingJobStatus,
    UserRole,
)
from models import Channel, ContentProject, Platform, Post, PublishingJob, Variant
from models.access import User
from services import gates
from services.projects import ProjectMismatchError, default_project_id, slugify
from services.seed import seed_base_data
from tests.conftest import login
from tests.factories import build_chain

pytestmark = pytest.mark.integration

MakeUser = Callable[..., User]


def nutrition(db: Session) -> ContentProject:
    project = ContentProject(slug="ernaehrung", name="Ernährung", languages=["de"])
    db.add(project)
    db.flush()
    return project


def channel_for(db: Session, project: ContentProject, language: Language = Language.DE) -> Channel:
    platform = db.scalar(select(Platform).where(Platform.code == PlatformCode.YOUTUBE))
    assert platform is not None
    channel = Channel(
        platform_id=platform.id,
        content_project_id=project.id,
        language=language,
        name=f"YouTube {project.name} {language.value}",
    )
    db.add(channel)
    db.flush()
    return channel


# --- default project and existing data ------------------------------------------------


def test_seed_puts_existing_channels_into_gaming(db: Session) -> None:
    seed_base_data(db, demo_channels=True)
    gaming = db.get(ContentProject, default_project_id(db))
    assert gaming is not None
    assert (gaming.slug, gaming.name, gaming.status) == (
        "gaming",
        "Gaming",
        ContentProjectStatus.ACTIVE,
    )
    projects = set(db.scalars(select(Channel.content_project_id)))
    assert projects == {gaming.id}


def test_content_inherits_the_project_of_its_channel(db: Session) -> None:
    chain = build_chain(db)
    gaming = default_project_id(db)
    assert chain.channel.content_project_id == gaming
    assert chain.gameplay_file.content_project_id == gaming
    assert chain.variant.content_project_id == gaming
    job = PublishingJob(
        variant_id=chain.variant.id,
        channel_id=chain.channel.id,
        status=PublishingJobStatus.PENDING,
        idempotency_key="k-inherit",
    )
    db.add(job)
    db.flush()
    post = Post(publishing_job_id=job.id, variant_id=chain.variant.id, channel_id=chain.channel.id)
    db.add(post)
    db.flush()
    assert job.content_project_id == gaming
    assert post.content_project_id == gaming


def test_slugify_handles_umlauts() -> None:
    assert slugify("Ernährung & Fitness") == "ernahrung-fitness"
    assert slugify("Straße") == "strasse"
    assert slugify("!!!") == "bereich"


# --- the hard rule: never on another project's channel --------------------------------


def test_nutrition_video_cannot_be_put_on_gaming_channel(db: Session) -> None:
    chain = build_chain(db)  # gaming channel
    food = nutrition(db)
    chain.gameplay_file.content_project_id = food.id  # material is about nutrition
    db.flush()
    db.add(
        Variant(
            clip_id=chain.clip.id,
            channel_id=chain.channel.id,
            language=Language.DE,
            variant_label="B",
        )
    )
    with pytest.raises(ProjectMismatchError):
        db.flush()


def test_explicit_wrong_project_is_refused(db: Session) -> None:
    chain = build_chain(db)
    food = nutrition(db)
    db.add(
        Variant(
            clip_id=chain.clip.id,
            channel_id=chain.channel.id,
            content_project_id=food.id,
            language=Language.DE,
            variant_label="C",
        )
    )
    with pytest.raises(ProjectMismatchError):
        db.flush()


def test_moving_a_video_to_another_projects_channel_is_refused(db: Session) -> None:
    chain = build_chain(db)
    food_channel = channel_for(db, nutrition(db))
    chain.variant.channel_id = food_channel.id
    with pytest.raises(ProjectMismatchError):
        db.flush()


def test_database_refuses_mismatch_even_with_raw_sql(db: Session) -> None:
    chain = build_chain(db)
    food_channel = channel_for(db, nutrition(db))
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            text("UPDATE variants SET channel_id = :c WHERE id = :v"),
            {"c": food_channel.id, "v": chain.variant.id},
        )


def test_publishing_job_on_other_projects_channel_is_refused(db: Session) -> None:
    chain = build_chain(db)
    food_channel = channel_for(db, nutrition(db))
    db.add(
        PublishingJob(
            variant_id=chain.variant.id,
            channel_id=food_channel.id,
            status=PublishingJobStatus.PENDING,
            idempotency_key="k-wrong",
        )
    )
    with pytest.raises(ProjectMismatchError):
        db.flush()


def test_new_variants_start_only_on_channels_of_the_material_project(db: Session) -> None:
    seed_base_data(db, demo_channels=True)
    food = nutrition(db)
    assert primary_channel(db, Language.DE, food.id) is None  # no nutrition channel yet
    food_channel = channel_for(db, food)
    assert primary_channel(db, Language.DE, food.id) == food_channel
    gaming_channel = primary_channel(db, Language.DE, default_project_id(db))
    assert gaming_channel is not None
    assert gaming_channel.content_project_id != food.id


# --- gates ---------------------------------------------------------------------------


def _payload(chain: Any) -> dict[str, Any]:
    return {"entity_type": "variants", "entity_id": chain.variant.id}


def test_paused_project_stops_production(db: Session) -> None:
    chain = build_chain(db)
    chain.gameplay_file.status = MaterialStatus.ANALYZED
    db.flush()
    spec = registry.get_spec("clip_production")
    assert spec is not None
    settings = get_settings()
    assert gates.check_entity(db, settings, spec, _payload(chain)).allowed
    gaming = db.get(ContentProject, chain.variant.content_project_id)
    assert gaming is not None
    gaming.status = ContentProjectStatus.PAUSED
    db.flush()
    result = gates.check_entity(db, settings, spec, _payload(chain))
    assert result.code == "project"
    assert "paused" in result.reason


# --- API -----------------------------------------------------------------------------


def test_admin_creates_project_and_channel(
    api: TestClient, make_user: MakeUser, db: Session
) -> None:
    make_user()
    headers = login(api, "admin@example.com")
    seed_base_data(db, demo_channels=True)
    r = api.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "Ernährung",
            "description": "Tipps und Rezepte",
            "languages": ["de"],
            "subtopics": ["Rezepte", " rezepte ", "Lebensmittelwissen", ""],
        },
    )
    assert r.status_code == 201, r.text
    project = r.json()
    assert project["slug"] == "ernahrung"
    assert project["subtopics"] == ["Rezepte", "Lebensmittelwissen"]
    assert project["is_default"] is False

    dup = api.post("/api/projects", headers=headers, json={"name": "ernährung"})
    assert dup.status_code == 409

    ch = api.post(
        "/api/channels",
        headers=headers,
        json={
            "platform": "youtube",
            "language": "de",
            "name": "Ernährung YouTube",
            "content_project_id": project["id"],
        },
    )
    assert ch.status_code == 201, ch.text
    body = ch.json()
    assert body["content_project"] == "Ernährung"
    assert body["is_paused"] is True
    assert body["max_posts_per_day"] == 0
    assert body["auth_status"] == ChannelAuthStatus.NOT_CONNECTED.value

    listing = {p["slug"]: p for p in api.get("/api/projects").json()}
    assert listing["ernahrung"]["channels"] == 1
    assert listing["gaming"]["is_default"] is True
    assert listing["gaming"]["channels"] == 8


def test_channel_moves_only_while_empty(api: TestClient, make_user: MakeUser, db: Session) -> None:
    make_user()
    headers = login(api, "admin@example.com")
    chain = build_chain(db)
    food = nutrition(db)
    used = api.put(
        f"/api/channels/{chain.channel.id}/project",
        headers=headers,
        json={"content_project_id": food.id},
    )
    assert used.status_code == 409
    empty = db.scalars(
        select(Channel).where(Channel.id != chain.channel.id).order_by(Channel.id)
    ).first()
    assert empty is not None
    moved = api.put(
        f"/api/channels/{empty.id}/project",
        headers=headers,
        json={"content_project_id": food.id},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["content_project_id"] == food.id


def test_default_project_with_channels_cannot_be_archived_but_paused(
    api: TestClient, make_user: MakeUser, db: Session
) -> None:
    make_user()
    headers = login(api, "admin@example.com")
    seed_base_data(db, demo_channels=True)
    db.commit()
    gaming = default_project_id(db)
    r = api.patch(f"/api/projects/{gaming}", headers=headers, json={"status": "archived"})
    assert r.status_code == 422
    r = api.patch(
        f"/api/projects/{gaming}",
        headers=headers,
        json={"status": "paused", "subtopics": ["GTA", "Gaming-News"], "tone": "locker"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "paused"
    assert r.json()["subtopics"] == ["GTA", "Gaming-News"]
    assert r.json()["tone"] == "locker"


def test_archived_project_takes_no_new_channels(
    api: TestClient, make_user: MakeUser, db: Session
) -> None:
    make_user()
    headers = login(api, "admin@example.com")
    seed_base_data(db, demo_channels=True)
    food = nutrition(db)
    food.status = ContentProjectStatus.ARCHIVED
    db.flush()
    r = api.post(
        "/api/channels",
        headers=headers,
        json={
            "platform": "tiktok",
            "language": "de",
            "name": "Ernährung TikTok",
            "content_project_id": food.id,
        },
    )
    assert r.status_code == 422


def test_viewer_and_operator_cannot_manage_projects(api: TestClient, make_user: MakeUser) -> None:
    make_user(role=UserRole.OPERATOR, email="op@example.com")
    headers = login(api, "op@example.com")
    assert api.get("/api/projects").status_code == 200
    assert api.post("/api/projects", headers=headers, json={"name": "X"}).status_code == 403
    r = api.post(
        "/api/channels",
        headers=headers,
        json={"platform": "youtube", "language": "de", "name": "X", "content_project_id": 1},
    )
    assert r.status_code == 403


def test_material_is_registered_for_a_project(
    api: TestClient, make_user: MakeUser, db: Session
) -> None:
    make_user()
    headers = login(api, "admin@example.com")
    chain = build_chain(db)
    food = nutrition(db)
    body = {
        "source_id": chain.license.source_id,
        "license_id": chain.license.id,
        "storage_uri": "mock://food.mp4",
        "sha256": "a" * 64,
        "content_project_id": food.id,
    }
    r = api.post("/api/materials", headers=headers, json=body)
    assert r.status_code == 201, r.text
    assert r.json()["content_project"] == "Ernährung"
    missing = api.post(
        "/api/materials",
        headers=headers,
        json={**body, "sha256": "b" * 64, "content_project_id": 999999},
    )
    assert missing.status_code == 404
    default = api.post(
        "/api/materials",
        headers=headers,
        json={**body, "sha256": "c" * 64, "content_project_id": None},
    )
    assert default.json()["content_project"] == "Gaming"


def test_paused_project_stops_publishing_planning(db: Session) -> None:
    from agents.publishing_strategy import bounds_for, publish_block

    seed_base_data(db, demo_channels=True)
    food = nutrition(db)
    channel = channel_for(db, food)
    channel.is_paused = False
    db.flush()
    assert publish_block(db, get_settings(), channel) is None
    food.status = ContentProjectStatus.PAUSED
    db.flush()
    db.refresh(channel)
    block = publish_block(db, get_settings(), channel)
    assert block is not None and "Ernährung" in block
    assert bounds_for(db, channel).paused is True


def test_empty_default_project_can_be_archived_and_reactivated(
    api: TestClient, make_user: MakeUser, db: Session
) -> None:
    """The operator picks his own topics; an unused Gaming area may go away."""
    make_user()
    headers = login(api, "admin@example.com")
    seed_base_data(db)  # production seed: no channels
    db.commit()
    gaming = default_project_id(db)
    r = api.patch(f"/api/projects/{gaming}", headers=headers, json={"status": "archived"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "archived"
    r = api.patch(f"/api/projects/{gaming}", headers=headers, json={"status": "active"})
    assert r.json()["status"] == "active"


# --- deleting a topic area -------------------------------------------------------------


def _food_chain(db: Session, project: ContentProject) -> dict[str, Any]:
    """Material, video, job and published post of ``project`` (reuses a rights chain)."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from models import Clip, GameplayFile, Idea, Scene
    from models.sponsors import SponsorInquiry

    base = build_chain(db)
    channel = channel_for(db, project)
    gf = GameplayFile(
        asset_id=base.gameplay_file.asset_id,
        game_id=base.gameplay_file.game_id,
        storage_uri="mock://food.mp4",
        sha256=uuid4().hex * 2,
        content_project_id=project.id,
    )
    db.add(gf)
    db.flush()
    scene = Scene(gameplay_file_id=gf.id, start_s=0.0, end_s=10.0)
    db.add(scene)
    db.flush()
    clip = Clip(scene_id=scene.id, start_s=0.0, end_s=10.0)
    db.add(clip)
    db.flush()
    variant = Variant(
        clip_id=clip.id, channel_id=channel.id, language=Language.DE, variant_label="A"
    )
    db.add(variant)
    db.flush()
    job = PublishingJob(
        variant_id=variant.id,
        channel_id=channel.id,
        status=PublishingJobStatus.SUCCEEDED,
        idempotency_key=f"k-food-{uuid4().hex[:6]}",
    )
    db.add(job)
    db.flush()
    post = Post(
        publishing_job_id=job.id,
        variant_id=variant.id,
        channel_id=channel.id,
        published_at=datetime.now(UTC),
    )
    idea = Idea(
        content_project_id=project.id,
        title="Proteinfrühstück",
        pitch="p",
        format="short",
        trend_score=1,
        fit_score=1,
        effort_score=1,
        rights_risk=0,
        score=1,
        reasoning="r",
        provider="mock",
    )
    sponsor = SponsorInquiry(
        content_project_id=project.id,
        brand="Müsli GmbH",
        body="Hallo",
        received_at=datetime.now(UTC),
        language=Language.DE,
        category="sponsor",
    )
    db.add_all([post, idea, sponsor])
    db.flush()
    return {"base": base, "channel": channel, "variant": variant, "sponsor": sponsor}


def test_delete_project_removes_its_content_and_spares_other_areas(
    api: TestClient, make_user: MakeUser, db: Session
) -> None:
    from models.sponsors import SponsorInquiry

    make_user()
    headers = login(api, "admin@example.com")
    food = nutrition(db)
    food_id = food.id
    made = _food_chain(db, food)
    base_variant_id = made["base"].variant.id
    sponsor_id = made["sponsor"].id
    gaming_channels = db.scalar(
        select(text("count(*)")).select_from(Channel).where(Channel.content_project_id != food_id)
    )
    db.commit()

    preview = api.get(f"/api/projects/{food_id}/deletion", headers=headers)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["can_delete"] is True
    counts = {i["key"]: i["count"] for i in body["items"]}
    assert counts["channels"] == 1
    assert counts["variants"] == 1
    assert counts["gameplay_files"] == 1
    assert counts["posts"] == 1
    assert counts["ideas"] == 1
    assert body["published"] == 1
    assert {i["key"]: i["count"] for i in body["kept"]} == {"sponsor_inquiries": 1}

    wrong = api.post(
        f"/api/projects/{food_id}/delete", headers=headers, json={"confirm_name": "Gaming"}
    )
    assert wrong.status_code == 422
    assert db.get(ContentProject, food_id) is not None

    ok = api.post(
        f"/api/projects/{food_id}/delete", headers=headers, json={"confirm_name": " ernährung "}
    )
    assert ok.status_code == 204, ok.text
    db.expire_all()
    assert db.get(ContentProject, food_id) is None
    assert db.scalar(select(Channel.id).where(Channel.content_project_id == food_id)) is None
    # the other area keeps everything
    assert db.get(Variant, base_variant_id) is not None
    assert db.scalar(select(text("count(*)")).select_from(Channel)) == gaming_channels
    sponsor = db.get(SponsorInquiry, sponsor_id)
    assert sponsor is not None and sponsor.content_project_id is None
    from models.access import AuditLog

    log = db.scalar(select(AuditLog).where(AuditLog.action == "project.delete"))
    assert log is not None and log.entity_id == food_id
    assert api.get(f"/api/projects/{food_id}/deletion", headers=headers).status_code == 404


def test_default_project_and_running_jobs_block_delete(
    api: TestClient, make_user: MakeUser, db: Session
) -> None:
    make_user()
    headers = login(api, "admin@example.com")
    seed_base_data(db, demo_channels=True)
    gaming = default_project_id(db)
    food = nutrition(db)
    made = _food_chain(db, food)
    job = PublishingJob(
        variant_id=made["variant"].id,
        channel_id=made["channel"].id,
        status=PublishingJobStatus.RUNNING,
        idempotency_key="k-running",
    )
    db.add(job)
    db.commit()

    preview = api.get(f"/api/projects/{gaming}/deletion", headers=headers).json()
    assert preview["can_delete"] is False
    assert "Standardbereich" in preview["blockers"][0]
    r = api.post(f"/api/projects/{gaming}/delete", headers=headers, json={"confirm_name": "Gaming"})
    assert r.status_code == 409

    r = api.post(
        f"/api/projects/{food.id}/delete", headers=headers, json={"confirm_name": "Ernährung"}
    )
    assert r.status_code == 409
    assert "Veröffentlichung" in r.json()["detail"]


def test_only_admins_delete_projects(api: TestClient, make_user: MakeUser, db: Session) -> None:
    make_user(email="op@example.com", role=UserRole.OPERATOR)
    headers = login(api, "op@example.com")
    food = nutrition(db)
    db.commit()
    assert api.get(f"/api/projects/{food.id}/deletion", headers=headers).status_code == 403
    r = api.post(
        f"/api/projects/{food.id}/delete", headers=headers, json={"confirm_name": "Ernährung"}
    )
    assert r.status_code == 403
