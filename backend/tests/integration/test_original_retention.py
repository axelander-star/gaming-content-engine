"""Originals of uploaded videos are deleted after 30 days (operator decision 16.11.2026)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import (
    AgentRunStatus,
    ChannelAuthStatus,
    Language,
    LibraryKind,
    LibraryOrigin,
    LibraryStatus,
    PlatformCode,
    UserRole,
    VideoStatus,
)
from models import Channel, User
from models.access import AuditLog
from models.channels import Platform
from models.library import LibraryItem
from models.production import Variant
from models.projects import ContentProject
from services import library, orchestrator
from services.seed import seed_base_data
from tests.conftest import login

pytestmark = pytest.mark.integration

NOW = datetime(2026, 12, 20, 12, 0, tzinfo=UTC)
OLD = NOW - timedelta(days=31)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(update={"media_root": str(tmp_path / "media")})


@pytest.fixture
def project(db: Session) -> ContentProject:
    p = ContentProject(slug="ernaehrung", name="Ernährung", languages=["de"], priority=100)
    db.add(p)
    db.flush()
    return p


class Maker:
    def __init__(self, db: Session, settings: Settings, project: ContentProject) -> None:
        self.db, self.root, self.project, self.n = db, Path(settings.media_root), project, 0

    def file(self, rel: str, size: int = 1000) -> str:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"v" * size)
        return f"local://{rel}"

    def item(
        self,
        *,
        created: datetime = OLD,
        vertical: bool = False,
        origin: LibraryOrigin = LibraryOrigin.UPLOAD,
        original: str | None = None,
        project: ContentProject | None = None,
    ) -> LibraryItem:
        self.n += 1
        orig = original or self.file(f"library/video/o{self.n}.mp4", 5000)
        rend = orig if vertical else self.file(f"library/renditions/r{self.n}.mp4", 2000)
        item = LibraryItem(
            content_project_id=(project or self.project).id,
            kind=LibraryKind.VIDEO,
            origin=origin,
            status=LibraryStatus.READY,
            title=f"Aufnahme {self.n}",
            content_type="video/mp4",
            original_uri=orig,
            original_sha256=f"{self.n:064d}",
            size_bytes=5000,
            rendition_uri=rend,
            rights={"confirmed_by_user_id": 1},
            created_at=created,
        )
        self.db.add(item)
        self.db.flush()
        return item

    def path(self, uri: str | None) -> Path:
        assert uri is not None
        return self.root / uri.removeprefix("local://")


@pytest.fixture
def make(db: Session, settings: Settings, project: ContentProject) -> Maker:
    return Maker(db, settings, project)


def test_original_goes_after_30_days_and_the_916_version_stays(
    db: Session, settings: Settings, make: Maker
) -> None:
    item = make.item()
    young = make.item(created=NOW - timedelta(days=10))
    generated = make.item(origin=LibraryOrigin.GENERATED)
    original, rendition = make.path(item.original_uri), make.path(item.rendition_uri)

    done = library.expire_originals(db, settings, NOW)
    assert done == [{"item_id": item.id, "bytes": 5000, "archived": False}]
    assert not original.exists() and rendition.exists()
    assert item.original_deleted_at == NOW and item.archived_at is None
    assert library.has_separate_rendition(item)  # still usable for posts
    for kept in (young, generated):
        assert kept.original_deleted_at is None and make.path(kept.original_uri).exists()
    assert db.scalar(select(AuditLog).where(AuditLog.action == "library.original_deleted"))
    assert library.expire_originals(db, settings, NOW) == []  # idempotent


def test_vertical_upload_is_archived_but_waits_for_an_open_post(
    db: Session, settings: Settings, make: Maker
) -> None:
    seed_base_data(db, demo_channels=True)
    plat = db.scalar(select(Platform).where(Platform.code == PlatformCode.YOUTUBE))
    assert plat is not None
    channel = Channel(
        platform_id=plat.id,
        content_project_id=make.project.id,
        language=Language.DE,
        name="YouTube Ernährung",
        auth_status=ChannelAuthStatus.NOT_CONNECTED,
    )
    db.add(channel)
    alone = make.item(vertical=True)
    posted = make.item(vertical=True)
    db.flush()
    post = Variant(
        library_item_id=posted.id,
        channel_id=channel.id,
        language=Language.DE,
        variant_label="A",
        status=VideoStatus.READY_TO_PUBLISH,
    )
    db.add(post)
    db.flush()

    done = library.expire_originals(db, settings, NOW)
    assert [d["item_id"] for d in done] == [alone.id] and done[0]["archived"]
    assert alone.archived_at == NOW and alone.rendition_uri is None
    assert not make.path(alone.original_uri).exists()
    assert posted.original_deleted_at is None and make.path(posted.original_uri).exists()

    post.status = VideoStatus.PUBLISHED  # once the post is out, the rule applies
    db.flush()
    assert [d["item_id"] for d in library.expire_originals(db, settings, NOW)] == [posted.id]


def test_shared_file_and_switched_off_retention(
    db: Session, settings: Settings, make: Maker
) -> None:
    other = ContentProject(slug="gaming2", name="Gaming 2", languages=["de"], priority=50)
    db.add(other)
    db.flush()
    old = make.item()
    # same content uploaded later into another topic area: same stored file
    newer = make.item(created=NOW - timedelta(days=5), original=old.original_uri, project=other)
    off = settings.model_copy(update={"library_original_retention_days": 0})
    assert library.expire_originals(db, off, NOW) == []
    assert library.expire_originals(db, settings, NOW) == []  # still needed by ``newer``
    assert make.path(old.original_uri).exists()
    later = NOW + timedelta(days=30)
    assert {d["item_id"] for d in library.expire_originals(db, settings, later)} == {
        old.id,
        newer.id,
    }
    assert not make.path(old.original_uri).exists()


def test_sweep_and_api(
    db: Session,
    settings: Settings,
    make: Maker,
    api: TestClient,
    make_user: Callable[..., User],
) -> None:
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    seed_base_data(db, demo_channels=True)
    real_old = datetime.now(UTC) - timedelta(days=31)
    kept = make.item(created=real_old)
    gone = make.item(created=real_old, vertical=True)
    make_user("op@example.com", UserRole.OPERATOR)
    db.commit()

    run = orchestrator.run_agent(db, settings, "media_library", {"sweep": True})
    assert run.status == AgentRunStatus.SUCCEEDED, run.output
    assert {d["item_id"] for d in run.output["originals_deleted"]} == {kept.id, gone.id}

    h = login(api, "op@example.com")
    info = api.get("/api/library/info", headers=h).json()
    assert info["original_retention_days"] == 30
    row = api.get(f"/api/library/{kept.id}", headers=h).json()
    assert row["has_original"] is False and row["has_rendition"] is True
    assert api.get(f"/api/library/{kept.id}/file", params={"which": "original"}).status_code == 410
    assert api.get(f"/api/library/{kept.id}/file", params={"which": "rendition"}).status_code == 200
    res = api.post(f"/api/library/{gone.id}/restore", headers=h)
    assert res.status_code == 409 and "nicht mehr nutzbar" in res.json()["detail"]
