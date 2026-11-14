"""Local file storage (``local://`` URIs below ``MEDIA_ROOT``).

Used for license evidence (Phase 6) and for gameplay files and rendered clips
(Phase 7). Files are content-addressed (``sha256``) and never overwritten, so a
stored file cannot change afterwards. Cloudflare R2 needs credentials from the
operator; until then everything stays in the local volume (see docs/SECURITY.md).
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from core.config import Settings

DOCUMENT_TYPES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}
#: Magic bytes so a file cannot pretend to be a PDF or image.
_SIGNATURES = {
    "application/pdf": (b"%PDF-",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
}


class StorageError(ValueError):
    pass


@dataclass(frozen=True)
class StoredFile:
    uri: str
    sha256: str
    size: int


def store_document(settings: Settings, data: bytes, content_type: str, folder: str) -> StoredFile:
    if content_type not in DOCUMENT_TYPES:
        raise StorageError("Only PDF, PNG or JPEG documents are accepted")
    if not data:
        raise StorageError("Empty file")
    if len(data) > settings.max_document_bytes:
        raise StorageError(f"File larger than {settings.max_document_bytes} bytes")
    if not data.startswith(_SIGNATURES[content_type]):
        raise StorageError("File content does not match its type")
    digest = hashlib.sha256(data).hexdigest()
    rel = Path(folder) / f"{digest}{DOCUMENT_TYPES[content_type]}"
    path = Path(settings.media_root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    return StoredFile(uri=f"local://{rel.as_posix()}", sha256=digest, size=len(data))


def resolve(settings: Settings, uri: str) -> Path:
    """Filesystem path of a ``local://`` URI, refusing paths outside the media root."""
    if not uri.startswith("local://"):
        raise StorageError("Not a local file")
    root = Path(settings.media_root).resolve()
    path = (root / uri.removeprefix("local://")).resolve()
    if root not in path.parents:
        raise StorageError("Invalid path")
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def store_path(
    settings: Settings, src: Path, folder: str, suffix: str, *, move: bool = True
) -> StoredFile:
    """Put an existing file into the content-addressed store (moved by default)."""
    digest = sha256_file(src)
    rel = Path(folder) / f"{digest}{suffix}"
    path = Path(settings.media_root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    size = src.stat().st_size
    if path.exists():
        if move:
            src.unlink()
    elif move:
        shutil.move(str(src), path)
    else:
        shutil.copyfile(src, path)
    return StoredFile(uri=f"local://{rel.as_posix()}", sha256=digest, size=size)


def work_dir(settings: Settings) -> Path:
    """Scratch space on the same volume, so finished files can be moved, not copied."""
    path = Path(settings.media_root) / "tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path
