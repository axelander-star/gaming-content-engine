"""Storage report and clean-up rules (services/housekeeping.py, app/housekeeping.py)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import LibraryKind, LibraryOrigin, LibraryStatus
from models.library import LibraryItem
from models.projects import ContentProject
from services import housekeeping

pytestmark = pytest.mark.integration

DAY = 86400


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(
        update={"media_root": str(tmp_path / "media"), "backup_dir": str(tmp_path / "backups")}
    )


def _file(root: Path, rel: str, size: int, age_s: float = 0) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    if age_s:
        old = time.time() - age_s
        os.utime(path, (old, old))
    return path


def _item(db: Session, rel: str, size: int, *, archived: bool = False) -> LibraryItem:
    project = ContentProject(slug=f"p{size}", name=f"P{size}", languages=["de"], priority=100)
    db.add(project)
    db.flush()
    item = LibraryItem(
        content_project_id=project.id,
        kind=LibraryKind.VIDEO,
        origin=LibraryOrigin.UPLOAD,
        status=LibraryStatus.READY,
        title="Test",
        content_type="video/mp4",
        original_uri=f"local://{rel}",
        original_sha256=f"{size:064d}",
        size_bytes=size,
        duration_s=30.0,
        rights={"note": "keep local://library/thumbs/kept.jpg too"},
    )
    if archived:
        from datetime import UTC, datetime

        item.archived_at = datetime.now(UTC)
    db.add(item)
    db.flush()
    return item


def test_cleanup_is_a_dry_run_by_default_and_never_touches_referenced_files(
    db: Session, settings: Settings
) -> None:
    root = Path(settings.media_root)
    kept = _file(root, "library/video/kept.mp4", 1000, age_s=30 * DAY)
    in_json = _file(root, "library/thumbs/kept.jpg", 10, age_s=30 * DAY)
    orphan = _file(root, "variants/orphan.mp4", 500, age_s=30 * DAY)
    young_orphan = _file(root, "variants/new.mp4", 70, age_s=1 * DAY)
    old_tmp = _file(root, "tmp/render-1/out.mp4", 300, age_s=7 * 3600)
    new_tmp = _file(root, "tmp/render-2/out.mp4", 30, age_s=600)
    upload_part = _file(root, "tmp/uploads/abc.part", 40, age_s=30 * DAY)
    _item(db, "library/video/kept.mp4", 1000)

    dry = housekeeping.cleanup(db, settings)
    assert not dry.applied and dry.refused is None
    assert dry.tmp == [old_tmp]
    assert dry.orphans == [orphan]
    assert dry.freed_bytes == 800
    assert all(p.exists() for p in (kept, in_json, orphan, old_tmp))  # nothing deleted

    done = housekeeping.cleanup(db, settings, apply=True)
    assert done.freed_bytes == 800
    assert not orphan.exists() and not old_tmp.exists()
    # referenced (column or JSON), too young, or owned by the upload purge: untouched
    for path in (kept, in_json, young_orphan, new_tmp, upload_part):
        assert path.exists(), path


def test_orphan_rule_refuses_when_the_database_references_nothing(
    db: Session, settings: Settings
) -> None:
    root = Path(settings.media_root)
    stored = _file(root, "library/video/a.mp4", 100, age_s=30 * DAY)
    old_tmp = _file(root, "tmp/x.mp4", 5, age_s=DAY)
    if housekeeping.referenced_paths(db):
        pytest.skip("test database already references files")
    res = housekeeping.cleanup(db, settings, apply=True)
    assert res.refused and "Falsche Datenbank" in res.refused
    assert res.orphans == [] and stored.exists()
    assert res.tmp == [old_tmp] and not old_tmp.exists()  # scratch rule still works


def test_storage_report_measures_folders_and_projects_a_year(
    db: Session, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    root = Path(settings.media_root)
    _file(root, "library/video/a.mp4", 3_000_000)
    _file(root, "library/renditions/a.mp4", 2_000_000)
    _file(root, "variants/v.mp4", 1_000_000)
    _file(Path(settings.backup_dir), "gce-1.dump.enc", 400)
    _item(db, "library/video/a.mp4", 3_000_000, archived=True)

    rep = housekeeping.storage_report(db, settings)
    usage = {f.folder: (f.files, f.bytes) for f in rep.media}
    assert usage == {
        "library/renditions": (1, 2_000_000),
        "library/video": (1, 3_000_000),
        "variants": (1, 1_000_000),
    }
    assert rep.media_bytes == 6_000_000
    assert rep.backup_files == 1 and rep.backup_bytes == 400
    assert rep.database_bytes and rep.database_bytes > 0
    assert rep.archived_bytes == 3_000_000
    assert rep.mb_per_video_minute == pytest.approx(6.0)  # 3 MB per 30 s


def test_cli_report_and_cleanup(
    db: Session,
    settings: Settings,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import housekeeping as cli

    root = Path(settings.media_root)
    _file(root, "library/video/a.mp4", 3_000_000)
    _file(root, "tmp/old.mp4", 9, age_s=DAY)
    _item(db, "library/video/a.mp4", 3_000_000)

    class _Maker:
        def __call__(self) -> _Ctx:
            return _Ctx()

    class _Ctx:
        def __enter__(self) -> Session:
            return db

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: _Maker())

    assert cli.main(["report", "--json", "--minutes-per-week", "10"]) == 0
    out = json.loads(capsys.readouterr().out)
    # 6 MB per minute, doubled for the 9:16 version, 10 minutes a week, 52 weeks
    assert out["projected_year_mb"] == pytest.approx(6.0 * 2 * 10 * 52)

    assert cli.main(["report"]) == 0
    assert "Hochrechnung 1 Jahr" in capsys.readouterr().out

    assert cli.main(["cleanup"]) == 0
    text = capsys.readouterr().out
    assert "Probelauf" in text and (root / "tmp/old.mp4").exists()
    assert cli.main(["cleanup", "--apply"]) == 0
    assert "gelöscht" in capsys.readouterr().out and not (root / "tmp/old.mp4").exists()
