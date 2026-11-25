"""Trend data sources (YouTube, Twitch, Steam) with mock and live adapters."""

from __future__ import annotations

from datetime import datetime

from redis import Redis

from core.config import Settings
from services.sources.base import TrendSource

SOURCE_ORDER = ("twitch", "steam", "youtube")  # twitch discovers games, youtube matches names


def get_sources(
    settings: Settings, redis: Redis | None = None, now: datetime | None = None
) -> list[TrendSource]:
    """Configured sources in fetch order. Mock mode never touches the network.

    Without sample data (production) mock mode has no sources at all, so no
    fictional games end up next to real data.
    """
    if settings.trend_sources_mode == "mock":
        if not settings.sample_data_enabled:
            return []
        from services.sources.mock import MockSource

        return [MockSource(name, now) for name in SOURCE_ORDER]
    if redis is None:
        raise ValueError("live sources need Redis for quota counting")
    from services.sources.live import SteamSource, TwitchSource, YouTubeSource

    return [
        TwitchSource(settings, redis),
        SteamSource(settings, redis),
        YouTubeSource(settings, redis),
    ]
