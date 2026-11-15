"""Storage report and clean-up rules for the media volume (extension phase E10).

Two jobs, both safe to run at any time:

* ``storage_report`` measures what lies where (per folder below ``MEDIA_ROOT``,
  backups, database) and projects the need for a year from the sizes that the
  system itself produced so far.
* ``cleanup`` finds files that nothing needs any more. It deletes only with
  ``apply=True``; the default is a dry run that lists what it would remove.

Rules (see docs/HETZNER_VORBEREITUNG.md):

1. Scratch files in ``MEDIA_ROOT/tmp`` older than ``tmp_hours`` (leftovers of a
   crashed render). Unfinished uploads are skipped: ``uploads.purge_expired``
   owns ``tmp/uploads``.
2. Stored files that no database row references any more and that are older
   than ``orphan_days``. References are collected from every table, including
   JSON columns, so a URI kept in a provenance record still counts.

Nothing referenced is ever deleted, and if the database references no file at
all while files exist, the orphan rule refuses to run (wrong database guard).
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import LibraryKind
from models.library import LibraryItem

_URI = re.compile(r"local://([^\s\"',)\\}\]]+)")
#: Folders below MEDIA_ROOT that cleanup never touches.
_SKIP_TOP = {"tmp"}


@dataclass
class FolderUsage:
    folder: str
    files: int
    bytes: int


@dataclass
class StorageReport:
    media: list[FolderUsage]
    media_bytes: int
    backup_bytes: int
    backup_files: int
    database_bytes: int | None
    library_videos: int
    library_video_bytes: int
    library_video_seconds: float
    archived_bytes: int

    @property
    def mb_per_video_minute(self) -> float | None:
        """Average original size per minute of library video (uploads and own ones)."""
        if self.library_video_seconds <= 0:
            return None
        return self.library_video_bytes / 1e6 / (self.library_video_seconds / 60)

    def as_dict(self) -> dict[str, object]:
        return {
            "media": [f.__dict__ for f in self.media],
            "media_bytes": self.media_bytes,
            "backup_bytes": self.backup_bytes,
            "backup_files": self.backup_files,
            "database_bytes": self.database_bytes,
            "library_videos": self.library_videos,
            "library_video_bytes": self.library_video_bytes,
            "library_video_seconds": self.library_video_seconds,
            "mb_per_video_minute": self.mb_per_video_minute,
            "archived_bytes": self.archived_bytes,
        }


@dataclass
class CleanupResult:
    applied: bool
    tmp: list[Path] = field(default_factory=list)
    orphans: list[Path] = field(default_factory=list)
    freed_bytes: int = 0
    refused: str | None = None

    @property
    def candidates(self) -> list[Path]:
        return self.tmp + self.orphans


def _files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return (p for p in root.rglob("*") if p.is_file() and not p.is_symlink())


def _size(paths: Iterable[Path]) -> tuple[int, int]:
    count = total = 0
    for p in paths:
        try:
            total += p.stat().st_size
            count += 1
        except OSError:
            continue
    return count, total


def folder_usage(media_root: Path) -> list[FolderUsage]:
    """Usage per folder, two levels deep for ``library`` (videos, renditions, ...)."""
    rows: dict[str, list[int]] = {}
    for path in _files(media_root):
        parts = path.relative_to(media_root).parts
        if len(parts) == 1:
            key = "."
        elif parts[0] == "library" and len(parts) > 2:
            key = f"library/{parts[1]}"
        else:
            key = parts[0]
        try:
            size = path.stat().st_size
        except OSError:
            continue
        row = rows.setdefault(key, [0, 0])
        row[0] += 1
        row[1] += size
    return [FolderUsage(k, v[0], v[1]) for k, v in sorted(rows.items())]


def _database_bytes(session: Session) -> int | None:
    if session.get_bind().dialect.name != "postgresql":
        return None
    return int(session.execute(text("SELECT pg_database_size(current_database())")).scalar_one())


def storage_report(session: Session, settings: Settings) -> StorageReport:
    media_root = Path(settings.media_root)
    media = folder_usage(media_root)
    backup_files, backup_bytes = _size(_files(Path(settings.backup_dir)))
    videos = archived = video_bytes = 0
    seconds = 0.0
    for item in session.scalars(select(LibraryItem)):
        size = int(item.size_bytes or 0)
        if item.kind == LibraryKind.VIDEO:
            videos += 1
            video_bytes += size
            seconds += item.duration_s or 0.0
        if item.archived_at is not None:
            archived += size
    return StorageReport(
        media=media,
        media_bytes=sum(f.bytes for f in media),
        backup_bytes=backup_bytes,
        backup_files=backup_files,
        database_bytes=_database_bytes(session),
        library_videos=videos,
        library_video_bytes=video_bytes,
        library_video_seconds=seconds,
        archived_bytes=archived,
    )


def referenced_paths(session: Session) -> set[str]:
    """Every ``local://`` path that any row of any table mentions (JSON included)."""
    found: set[str] = set()
    bind = session.get_bind()
    for table in inspect(bind).get_table_names():
        if table == "alembic_version":
            continue
        quoted = bind.dialect.identifier_preparer.quote(table)
        for (row,) in session.execute(text(f"SELECT CAST(t AS text) FROM {quoted} t")):  # noqa: S608
            if row and "local://" in row:
                found.update(m.group(1) for m in _URI.finditer(row))
    return found


def cleanup(
    session: Session,
    settings: Settings,
    *,
    apply: bool = False,
    tmp_hours: float = 6,
    orphan_days: float = 7,
    now: float | None = None,
) -> CleanupResult:
    now = time.time() if now is None else now
    root = Path(settings.media_root)
    result = CleanupResult(applied=apply)

    tmp_root = root / "tmp"
    for path in _files(tmp_root):
        if path.relative_to(tmp_root).parts[0] == "uploads":
            continue
        if now - path.stat().st_mtime > tmp_hours * 3600:
            result.tmp.append(path)

    stored = [
        p
        for p in _files(root)
        if p.relative_to(root).parts[0] not in _SKIP_TOP and len(p.relative_to(root).parts) > 1
    ]
    refs = referenced_paths(session)
    if stored and not refs:
        result.refused = (
            "Die Datenbank verweist auf keine einzige Datei. Falsche Datenbank? "
            "Verwaiste Dateien werden deshalb nicht angefasst."
        )
    else:
        for path in stored:
            rel = path.relative_to(root).as_posix()
            if rel not in refs and now - path.stat().st_mtime > orphan_days * 86400:
                result.orphans.append(path)

    for path in result.candidates:
        try:
            size = path.stat().st_size
            if apply:
                path.unlink()
            result.freed_bytes += size
        except OSError:
            continue
    return result
