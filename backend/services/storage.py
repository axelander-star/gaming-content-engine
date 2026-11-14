"""Local file storage for evidence documents (Cloudflare R2 follows with media in Phase 7+).

Files are content-addressed (``sha256``) and never overwritten, so a stored
license document cannot change afterwards.
"""

from __future__ import annotations

import hashlib
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
