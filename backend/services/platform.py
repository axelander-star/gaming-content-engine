"""Shared pieces of the platform integrations (Phase 12/13).

* error classes every publisher raises, so the publishing agent handles all
  platforms the same way,
* the signed OAuth ``state`` (channel, user, provider; 10 minutes),
* the HTTP client for TikTok and Meta; tests replace :data:`TRANSPORT` with an
  ``httpx.MockTransport`` and never reach a platform.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt

from core.config import Settings
from core.enums import PlatformCode

STATE_TTL = timedelta(minutes=10)

#: Replaced by tests with ``httpx.MockTransport``; ``None`` = real network.
TRANSPORT: httpx.BaseTransport | None = None


class PlatformError(RuntimeError):
    """Permanent error from a platform (bad request, forbidden, rejected video, …)."""

    def __init__(self, message: str, status: int | None = None, reason: str | None = None):
        super().__init__(message)
        self.status = status
        self.reason = reason


class AuthExpiredError(PlatformError):
    """The stored access is no longer valid; the channel must be connected again."""


class RestrictedError(PlatformError):
    """The connection works but may not publish (e.g. TikTok app not audited yet)."""


class TransientError(PlatformError):
    """Temporary problem (quota, rate limit, 5xx, network); try again later."""


class NotConfiguredError(RuntimeError):
    """The platform's OAuth client / app is not configured."""


def http_client(timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(transport=TRANSPORT, timeout=timeout)


def json_of(res: httpx.Response) -> dict[str, Any]:
    try:
        data = res.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def provider_for(platform: PlatformCode, settings: Settings | None = None) -> str:
    """OAuth provider of a platform: Facebook (and Instagram via a Page) use the Meta
    login; with ``INSTAGRAM_LOGIN=instagram`` Instagram has its own login (E8)."""
    if (
        platform == PlatformCode.INSTAGRAM
        and settings is not None
        and settings.instagram_login == "instagram"
    ):
        return "instagram"
    if platform in (PlatformCode.INSTAGRAM, PlatformCode.FACEBOOK):
        return "meta"
    return platform.value


def make_state(settings: Settings, provider: str, channel_id: int, user_id: int) -> str:
    now = datetime.now(UTC)
    payload = {"ch": channel_id, "u": user_id, "p": provider, "iat": now, "exp": now + STATE_TTL}
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm="HS256")


def read_state(settings: Settings, provider: str, state: str) -> tuple[int, int]:
    """Channel and user id from a state issued by :func:`make_state` for ``provider``."""
    try:
        data = jwt.decode(state, settings.secret_key.get_secret_value(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise PlatformError("Ungültiger oder abgelaufener Anmeldevorgang") from exc
    if data.get("p") != provider:
        raise PlatformError("Ungültiger Anmeldevorgang")
    return int(data["ch"]), int(data["u"])
