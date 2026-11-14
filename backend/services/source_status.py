"""Connection status of the trend sources, shown in the dashboard.

After every trend run (and every manual connection test) the outcome per source
is stored in Redis: when it ran, whether it worked, how many requests it used
and the last error. Credentials are never stored here or returned; the API
only says whether they are configured.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from redis import Redis

from core.config import Settings
from services import quota
from services.sources.base import SourceResult

SOURCES = ("youtube", "twitch", "steam")
_KEY = "trend_source_status:{}"


@dataclass(frozen=True)
class SourceInfo:
    name: str
    label: str
    needs_credentials: tuple[str, ...]
    daily_limit_label: str


INFO = {
    "youtube": SourceInfo("youtube", "YouTube Data API v3", ("YOUTUBE_API_KEY",), "Einheiten"),
    "twitch": SourceInfo(
        "twitch", "Twitch Helix", ("TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET"), "Anfragen"
    ),
    "steam": SourceInfo("steam", "Steam Web API", (), "Anfragen"),
}


def configured(settings: Settings, name: str) -> bool:
    if name == "youtube":
        return bool(settings.youtube_api_key.get_secret_value())
    if name == "twitch":
        return bool(settings.twitch_client_id and settings.twitch_client_secret.get_secret_value())
    return True  # Steam's player counts need no key


def daily_limit(settings: Settings, name: str) -> int:
    from services.sources.live import STEAM_DAILY_REQUESTS, TWITCH_DAILY_REQUESTS

    return {
        "youtube": settings.youtube_daily_quota_units,
        "twitch": TWITCH_DAILY_REQUESTS,
        "steam": STEAM_DAILY_REQUESTS,
    }[name]


def record(
    redis: Redis,
    result: SourceResult,
    mode: str,
    kind: str = "run",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Store the outcome of a run or a connection test for one source."""
    now = now or datetime.now(UTC)
    if mode == "mock" and kind == "run":
        state = "mock"  # test data: no real connection was made, never report "connected"
    elif result.skipped:
        state = "skipped"
    elif result.errors and not result.observations and kind == "run":
        state = "error"
    elif result.errors:
        state = "error" if kind == "test" else "partial"
    else:
        state = "ok"
    entry = {
        "state": state,
        "mode": mode,
        "kind": kind,
        "at": now.isoformat(),
        "requests": result.requests,
        "observations": len(result.observations),
        "errors": result.errors[:5],
        "skipped": result.skipped,
        "detail": result.detail,
    }
    previous = _load(redis, result.source) or {}
    if state in ("ok", "partial"):
        entry["last_ok_at"] = now.isoformat()
    else:
        entry["last_ok_at"] = previous.get("last_ok_at")
    redis.set(_KEY.format(result.source), json.dumps(entry), ex=30 * 24 * 3600)
    return entry


def _load(redis: Redis, name: str) -> dict[str, Any] | None:
    raw = redis.get(_KEY.format(name))
    if raw is None:
        return None
    data: dict[str, Any] = json.loads(raw)
    return data


def overview(settings: Settings, redis: Redis) -> list[dict[str, Any]]:
    out = []
    for name in SOURCES:
        info = INFO[name]
        out.append(
            {
                "name": name,
                "label": info.label,
                "mode": settings.trend_sources_mode,
                "configured": configured(settings, name),
                "credentials": list(info.needs_credentials),
                "quota_used": quota.used(redis, name),
                "quota_limit": daily_limit(settings, name),
                "quota_unit": info.daily_limit_label,
                "last": _load(redis, name),
            }
        )
    return out
