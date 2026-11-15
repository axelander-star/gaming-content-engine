"""Resumable uploads in parts (services/uploads.py, api/uploads.py)."""

from __future__ import annotations

import hashlib
import os
import shutil
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import UploadStatus, UserRole
from models import GameplayFile, User
from models.uploads import UploadSession
from services import media, storage, uploads
from tests.conftest import login
from tests.factories import build_chain

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed"),
]

CHUNK = 256 * 1024
MakeUser = Callable[..., User]


@pytest.fixture(scope="module")
def video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = media.make_test_video(get_settings(), tmp_path_factory.mktemp("up") / "720p.mp4")
    assert path.stat().st_size > 2 * CHUNK  # the tests need several parts
    return path


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(
        update={"media_root": str(tmp_path / "media"), "upload_chunk_bytes": CHUNK}
    )


@pytest.fixture
def client(api: TestClient, settings: Settings) -> Iterator[TestClient]:
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    yield api


@pytest.fixture
def op(client: TestClient, make_user: MakeUser) -> dict[str, str]:
    make_user("op@example.com", UserRole.OPERATOR)
    return login(client, "op@example.com")


def _params(db: Session) -> dict[str, Any]:
    chain = build_chain(db)
    return {
        "source_id": chain.license.source_id,
        "license_id": chain.license.id,
        "game_id": chain.gameplay_file.game_id,
        "title": "Testmaterial",
    }


def _create(
    client: TestClient, h: dict[str, str], data: bytes, params: dict[str, Any], **extra: Any
) -> Any:
    body = {
        "purpose": "material",
        "filename": "clip.mp4",
        "size_bytes": len(data),
        "content_type": "video/mp4",
        "params": params,
        **extra,
    }
    return client.post("/api/uploads", json=body, headers=h)


def _send(client: TestClient, h: dict[str, str], uid: str, data: bytes, offset: int) -> Any:
    return client.patch(
        f"/api/uploads/{uid}",
        content=data[offset : offset + CHUNK],
        headers={**h, "Upload-Offset": str(offset), "Content-Type": "application/octet-stream"},
    )


def _send_all(client: TestClient, h: dict[str, str], uid: str, data: bytes, start: int = 0) -> None:
    offset = start
    while offset < len(data):
        r = _send(client, h, uid, data, offset)
        assert r.status_code == 200, r.text
        offset = r.json()["received_bytes"]


def test_upload_in_parts_registers_material(
    client: TestClient, op: dict[str, str], db: Session, video: Path, settings: Settings
) -> None:
    data = video.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    created = _create(client, op, data, _params(db), sha256=sha)
    assert created.status_code == 201, created.text
    up = created.json()
    assert up["chunk_bytes"] == CHUNK and up["received_bytes"] == 0 and up["status"] == "UPLOADING"
    _send_all(client, op, up["id"], data)

    done = client.post(f"/api/uploads/{up['id']}/complete", headers=op)
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "COMPLETED", body
    material = db.get(GameplayFile, body["result"]["material_id"])
    assert material is not None and material.sha256 == sha
    assert (material.width, material.height) == (1280, 720)
    assert storage.resolve(settings, material.storage_uri).is_file()
    assert not list(uploads.upload_dir(settings).iterdir())  # partial file gone

    again = client.post(f"/api/uploads/{up['id']}/complete", headers=op)
    assert again.status_code == 200 and again.json()["result"] == body["result"]
    assert (
        db.scalar(select(func.count()).select_from(GameplayFile).where(GameplayFile.sha256 == sha))
        == 1
    )


def test_resume_after_interruption(
    client: TestClient, op: dict[str, str], db: Session, video: Path
) -> None:
    data = video.read_bytes()
    uid = _create(client, op, data, _params(db)).json()["id"]
    assert _send(client, op, uid, data, 0).status_code == 200

    # The client lost the answer and sends the first part again: 409 + where to go on.
    dup = _send(client, op, uid, data, 0)
    assert dup.status_code == 409 and dup.headers["Upload-Offset"] == str(CHUNK)
    # A jump ahead is refused as well.
    jump = _send(client, op, uid, data, 2 * CHUNK)
    assert jump.status_code == 409 and jump.headers["Upload-Offset"] == str(CHUNK)

    # After a reconnect the client asks where to continue.
    state = client.get(f"/api/uploads/{uid}", headers=op).json()
    assert state["received_bytes"] == CHUNK
    _send_all(client, op, uid, data, start=state["received_bytes"])
    assert client.post(f"/api/uploads/{uid}/complete", headers=op).json()["status"] == "COMPLETED"


def test_part_checks(client: TestClient, op: dict[str, str], db: Session, video: Path) -> None:
    data = video.read_bytes()
    uid = _create(client, op, data, _params(db)).json()["id"]
    part = data[:CHUNK]
    bad = client.patch(
        f"/api/uploads/{uid}",
        content=part,
        headers={**op, "Upload-Offset": "0", "X-Chunk-Sha256": "0" * 64},
    )
    assert bad.status_code == 422
    good = client.patch(
        f"/api/uploads/{uid}",
        content=part,
        headers={**op, "Upload-Offset": "0", "X-Chunk-Sha256": hashlib.sha256(part).hexdigest()},
    )
    assert good.status_code == 200 and good.json()["received_bytes"] == CHUNK
    too_big = client.patch(
        f"/api/uploads/{uid}",
        content=data[CHUNK : 3 * CHUNK],
        headers={**op, "Upload-Offset": str(CHUNK)},
    )
    assert too_big.status_code == 413
    early = client.post(f"/api/uploads/{uid}/complete", headers=op)
    assert early.status_code == 409 and early.headers["Upload-Offset"] == str(CHUNK)
    no_csrf = client.patch(
        f"/api/uploads/{uid}", content=b"x", headers={"Upload-Offset": str(CHUNK)}
    )
    assert no_csrf.status_code == 403


def test_part_beyond_declared_size(client: TestClient, op: dict[str, str], db: Session) -> None:
    uid = _create(client, op, b"x" * 1000, _params(db)).json()["id"]
    r = client.patch(
        f"/api/uploads/{uid}", content=b"y" * 1001, headers={**op, "Upload-Offset": "0"}
    )
    assert r.status_code == 413


def test_create_validation(
    client: TestClient, op: dict[str, str], db: Session, settings: Settings
) -> None:
    params = _params(db)
    assert _create(client, op, b"x", params, content_type="text/plain").status_code == 422
    assert _create(client, op, b"x", params, purpose="unknown").status_code == 422
    huge = _create(client, op, b"x", params, size_bytes=settings.max_upload_bytes + 1)
    assert huge.status_code == 413
    wrong_license = _create(client, op, b"x", {**params, "source_id": params["source_id"] + 999})
    assert wrong_license.status_code == 422, wrong_license.text
    extra_field = _create(client, op, b"x", {**params, "evil": 1})
    assert extra_field.status_code == 422
    assert _create(client, op, b"x", params, sha256="nothex" * 9 + "abcdefghij").status_code == 422


def test_upload_belongs_to_its_user(
    client: TestClient, op: dict[str, str], db: Session, make_user: MakeUser
) -> None:
    uid = _create(client, op, b"x" * 10, _params(db)).json()["id"]
    make_user("op2@example.com", UserRole.OPERATOR)
    other = login(client, "op2@example.com")
    assert client.get(f"/api/uploads/{uid}", headers=other).status_code == 404
    assert client.delete(f"/api/uploads/{uid}", headers=other).status_code == 404
    make_user("viewer@example.com", UserRole.VIEWER)
    viewer = login(client, "viewer@example.com")
    assert client.get(f"/api/uploads/{uid}", headers=viewer).status_code == 403


def test_failed_processing_and_checksum(
    client: TestClient, op: dict[str, str], db: Session, settings: Settings, video: Path
) -> None:
    junk = os.urandom(CHUNK + 100)
    uid = _create(client, op, junk, _params(db)).json()["id"]
    _send_all(client, op, uid, junk)
    r = client.post(f"/api/uploads/{uid}/complete", headers=op).json()
    assert r["status"] == "FAILED" and "readable" in r["error_message"]
    assert not list(uploads.upload_dir(settings).iterdir())

    data = video.read_bytes()
    uid = _create(client, op, data, _params(db), sha256="a" * 64).json()["id"]
    _send_all(client, op, uid, data)
    r = client.post(f"/api/uploads/{uid}/complete", headers=op).json()
    assert r["status"] == "FAILED" and "SHA-256" in r["error_message"]
    assert (
        client.patch(
            f"/api/uploads/{uid}", content=b"x", headers={**op, "Upload-Offset": "0"}
        ).status_code
        == 409
    )


def test_cancel_removes_partial_file(
    client: TestClient, op: dict[str, str], db: Session, settings: Settings, video: Path
) -> None:
    data = video.read_bytes()
    uid = _create(client, op, data, _params(db)).json()["id"]
    _send(client, op, uid, data, 0)
    assert (uploads.upload_dir(settings) / f"{uid}.part").stat().st_size == CHUNK
    r = client.delete(f"/api/uploads/{uid}", headers=op)
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    assert not (uploads.upload_dir(settings) / f"{uid}.part").exists()


def test_purge_expired_sessions_and_stray_files(
    client: TestClient, op: dict[str, str], db: Session, settings: Settings
) -> None:
    uid = _create(client, op, b"x" * 10, _params(db)).json()["id"]
    fresh = _create(client, op, b"x" * 10, _params(db)).json()["id"]
    session = db.get(UploadSession, uid)
    assert session is not None
    session.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    stray_old = uploads.upload_dir(settings) / "deadbeef.part"
    stray_old.write_bytes(b"old")
    old = time.time() - uploads.STRAY_MIN_AGE_S - 10
    os.utime(stray_old, (old, old))
    stray_new = uploads.upload_dir(settings) / "cafebabe.part"
    stray_new.write_bytes(b"new")
    db.flush()

    assert uploads.purge_expired(db, settings) == 2
    assert session.status == UploadStatus.CANCELLED
    assert not (uploads.upload_dir(settings) / f"{uid}.part").exists()
    assert (uploads.upload_dir(settings) / f"{fresh}.part").exists()
    assert not stray_old.exists() and stray_new.exists()
    expired = client.patch(
        f"/api/uploads/{uid}", content=b"x", headers={**op, "Upload-Offset": "0"}
    )
    assert expired.status_code == 409
