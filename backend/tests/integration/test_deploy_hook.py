"""Instant server update: signed GitHub webhook drops a trigger file for the server."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import access_guard
from core.config import Settings, get_settings
from models.access import User
from services import deploy_hook
from tests.conftest import login

pytestmark = pytest.mark.integration

SECRET = "s" * 64
MAIN_PUSH = {"ref": "refs/heads/main", "after": "a" * 40, "deleted": False}


def _sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def hook_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    folder = tmp_path / "deploy-hook"
    folder.mkdir()
    monkeypatch.setenv("DEPLOY_HOOK_DIR", str(folder))
    get_settings.cache_clear()
    yield folder
    get_settings.cache_clear()


@pytest.fixture
def ready(hook_dir: Path) -> Path:
    (hook_dir / "secret").write_text(SECRET + "\n")
    return hook_dir


def _post(
    api: TestClient, payload: object, event: str = "push", signature: str | None = None
) -> tuple[int, dict[str, str]]:
    body = json.dumps(payload).encode()
    r = api.post(
        "/api/hooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": "d-1",
            "X-Hub-Signature-256": signature if signature is not None else _sign(body),
        },
    )
    return r.status_code, r.json()


def test_push_to_main_writes_trigger(api: TestClient, ready: Path) -> None:
    code, data = _post(api, MAIN_PUSH)
    assert code == 202 and data["action"] == "triggered"
    trigger = json.loads((ready / "trigger").read_text())
    assert trigger["commit"] == "a" * 40 and trigger["delivery"] == "d-1"
    assert oct((ready / "trigger").stat().st_mode & 0o777) == "0o644"
    assert json.loads((ready / "last-hook").read_text())["action"] == "triggered"


def test_wrong_or_missing_signature_is_refused(api: TestClient, ready: Path) -> None:
    assert _post(api, MAIN_PUSH, signature=_sign(b"other"))[0] == 401
    foreign = _sign(json.dumps(MAIN_PUSH).encode(), "x" * 64)
    assert _post(api, MAIN_PUSH, signature=foreign)[0] == 401
    assert _post(api, MAIN_PUSH, signature="")[0] == 401
    assert _post(api, MAIN_PUSH, signature="sha1=abc")[0] == 401
    assert not (ready / "trigger").exists()
    assert not (ready / "last-hook").exists()


def test_not_set_up_answers_503(api: TestClient, hook_dir: Path) -> None:
    assert _post(api, MAIN_PUSH)[0] == 503
    (hook_dir / "secret").write_text("too-short")
    assert _post(api, MAIN_PUSH)[0] == 503
    assert not (hook_dir / "trigger").exists()


def test_other_branches_events_and_deletes_are_ignored(api: TestClient, ready: Path) -> None:
    assert _post(api, {**MAIN_PUSH, "ref": "refs/heads/feature"}) == (
        200,
        {"action": "ignored", "detail": "push to refs/heads/feature (only main deploys)"},
    )
    assert _post(api, {**MAIN_PUSH, "deleted": True})[1]["action"] == "ignored"
    assert _post(api, {"zen": "hi"}, event="ping") == (
        200,
        {"action": "pong", "detail": "webhook connected"},
    )
    assert _post(api, {}, event="issues")[1]["action"] == "ignored"
    assert _post(api, ["not", "a", "dict"])[0] == 400
    assert not (ready / "trigger").exists()
    assert json.loads((ready / "last-hook").read_text())["action"] == "ignored"


def test_large_body_is_refused(api: TestClient, ready: Path) -> None:
    payload = {**MAIN_PUSH, "pad": "x" * (deploy_hook.MAX_BODY_BYTES + 10)}
    assert _post(api, payload)[0] == 413
    assert not (ready / "trigger").exists()


def test_hook_path_skips_access_check_but_nothing_else() -> None:
    assert access_guard.is_exempt("/api/hooks/github")
    assert not access_guard.is_exempt("/api/hooksx")
    assert not access_guard.is_exempt("/api/system/deploy-hook")


def test_status_shows_watcher_and_last_runs(ready: Path) -> None:
    settings = Settings()
    now = datetime.now(UTC)
    st = deploy_hook.status(settings, now)
    assert st.secret_ready and st.secret == SECRET
    assert not st.watcher_active and st.watcher_seen_at is None and not st.pending
    (ready / "watcher").touch()
    (ready / "last-update").write_text('{"at": "x", "commit": "abc", "result": "ok"}')
    deploy_hook.handle(settings, json.dumps(MAIN_PUSH).encode(), "push",
                       _sign(json.dumps(MAIN_PUSH).encode()), "d")  # fmt: skip
    st = deploy_hook.status(settings, now)
    assert st.watcher_active and st.pending
    assert st.last_update == {"at": "x", "commit": "abc", "result": "ok"}
    assert st.last_hook is not None and st.last_hook["action"] == "triggered"
    old = (now - timedelta(hours=1)).timestamp()
    os.utime(ready / "watcher", (old, old))
    assert not deploy_hook.status(settings, now).watcher_active


def test_status_endpoint_is_admin_only(
    api: TestClient, ready: Path, make_user: Callable[..., User]
) -> None:
    from core.enums import UserRole

    make_user("viewer@example.com", role=UserRole.VIEWER)
    login(api, "viewer@example.com")
    assert api.get("/api/system/deploy-hook").status_code == 403
    api.cookies.clear()
    make_user()
    login(api, "admin@example.com")
    data = api.get("/api/system/deploy-hook").json()
    assert data["secret_ready"] and data["secret"] == SECRET
    assert data["watcher_active"] is False
