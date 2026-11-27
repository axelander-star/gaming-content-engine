"""Instant server update after a merge (27.11.2026).

GitHub sends a signed ``push`` event to ``/api/hooks/github`` (own tunnel host,
Caddy ``:8083``). If the signature matches and the push went to main, the backend
drops a ``trigger`` file into a folder shared with the server. A small watcher on
the server (``scripts/auto_update_watch.sh``, started by cron every minute) sees
the file within seconds and runs the normal ``scripts/auto_update.sh``: green
main only, database backup, rollback on failure. The backend itself never
deploys, holds no Docker access and runs no commands; the five-minute cron check
stays as fallback.

Files in ``DEPLOY_HOOK_DIR``:

``secret``       webhook secret, written by the server (``auto_update.sh``)
``trigger``      written here, removed by the watcher when it starts the update
``last-hook``    last accepted webhook (JSON), for the dashboard
``watcher``      heartbeat of the watcher (touched every minute)
``last-update``  result of the last update run (JSON, written by the server)
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.config import Settings

SECRET_FILE = "secret"  # noqa: S105 - file name, not a secret
TRIGGER_FILE = "trigger"
LAST_HOOK_FILE = "last-hook"
WATCHER_FILE = "watcher"
LAST_UPDATE_FILE = "last-update"
#: Push payloads are a few KB; anything larger is not a push we care about.
MAX_BODY_BYTES = 1024 * 1024
#: The watcher touches its heartbeat once a minute; allow for a long deploy.
WATCHER_STALE_S = 20 * 60
MIN_SECRET_LEN = 32


class HookError(Exception):
    """The request was refused; ``status`` is the HTTP status to answer with."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def hook_dir(settings: Settings) -> Path:
    return Path(settings.deploy_hook_dir)


def read_secret(settings: Settings) -> str | None:
    """The shared secret, or ``None`` while the server has not created it yet."""
    try:
        secret = (hook_dir(settings) / SECRET_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return secret if len(secret) >= MIN_SECRET_LEN else None


def signature_ok(secret: str, body: bytes, header: str | None) -> bool:
    """GitHub's ``X-Hub-Signature-256``: ``sha256=`` + HMAC-SHA256 of the raw body."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256=").strip().lower())


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Write atomically, so the watcher never reads half a file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


@dataclass(frozen=True)
class HookResult:
    status: int
    action: str  # "pong" | "triggered" | "ignored"
    detail: str


def handle(
    settings: Settings,
    body: bytes,
    event: str | None,
    signature: str | None,
    delivery: str | None,
    now: datetime | None = None,
) -> HookResult:
    """Check one webhook call and, for a push to main, request the update."""
    if len(body) > MAX_BODY_BYTES:
        raise HookError(413, "payload too large")
    secret = read_secret(settings)
    if secret is None:
        raise HookError(503, "instant update is not set up on the server yet")
    if not signature_ok(secret, body, signature):
        raise HookError(401, "invalid signature")
    now = now or datetime.now(UTC)
    if event == "ping":
        result = HookResult(200, "pong", "webhook connected")
    elif event != "push":
        result = HookResult(200, "ignored", f"event {event!r} is not used")
    else:
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise HookError(400, "body is not JSON") from exc
        if not isinstance(payload, dict):
            raise HookError(400, "body is not a JSON object")
        ref = str(payload.get("ref") or "")
        branch = settings.deploy_hook_branch
        if ref != f"refs/heads/{branch}":
            result = HookResult(200, "ignored", f"push to {ref or '?'} (only {branch} deploys)")
        elif payload.get("deleted"):
            result = HookResult(200, "ignored", "branch deleted")
        else:
            commit = str(payload.get("after") or "")[:40]
            _write_json(
                hook_dir(settings) / TRIGGER_FILE,
                {"commit": commit, "delivery": delivery or "", "at": now.isoformat()},
            )
            result = HookResult(202, "triggered", f"update to {commit[:7]} requested")
    _write_json(
        hook_dir(settings) / LAST_HOOK_FILE,
        {"at": now.isoformat(), "event": event or "", "action": result.action,
         "detail": result.detail},
    )  # fmt: skip
    return result


@dataclass(frozen=True)
class Status:
    secret_ready: bool
    secret: str | None
    watcher_seen_at: str | None
    watcher_active: bool
    pending: bool
    last_hook: dict[str, Any] | None
    last_update: dict[str, Any] | None


def status(settings: Settings, now: datetime | None = None) -> Status:
    """State for the dashboard: is everything connected, what happened last."""
    now = now or datetime.now(UTC)
    folder = hook_dir(settings)
    secret = read_secret(settings)
    seen: datetime | None = None
    with contextlib.suppress(OSError):
        seen = datetime.fromtimestamp((folder / WATCHER_FILE).stat().st_mtime, UTC)
    return Status(
        secret_ready=secret is not None,
        secret=secret,
        watcher_seen_at=seen.isoformat() if seen else None,
        watcher_active=seen is not None and (now - seen).total_seconds() < WATCHER_STALE_S,
        pending=(folder / TRIGGER_FILE).exists(),
        last_hook=_read_json(folder / LAST_HOOK_FILE),
        last_update=_read_json(folder / LAST_UPDATE_FILE),
    )
