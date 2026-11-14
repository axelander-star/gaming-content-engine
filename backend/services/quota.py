"""Daily API quota counters in Redis (PROJECT_SPEC section 15: respect rate limits)."""

from __future__ import annotations

from datetime import UTC, datetime

from redis import Redis

from services.sources.base import QuotaExceededError


def _key(source: str, now: datetime | None = None) -> str:
    day = (now or datetime.now(UTC)).strftime("%Y%m%d")
    return f"quota:{source}:{day}"


def used(redis: Redis, source: str, now: datetime | None = None) -> int:
    value = redis.get(_key(source, now))
    return int(value) if value is not None else 0


def consume(
    redis: Redis, source: str, units: int, daily_limit: int, now: datetime | None = None
) -> int:
    """Book ``units`` for today or raise if that would exceed ``daily_limit``."""
    key = _key(source, now)
    total = int(redis.incrby(key, units))
    redis.expire(key, 2 * 24 * 3600)
    if total > daily_limit:
        redis.decrby(key, units)
        raise QuotaExceededError(f"{source}: daily quota of {daily_limit} units reached")
    return total
