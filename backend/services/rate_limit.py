"""Login throttling in Redis: too many failures lock the key for a while."""

from __future__ import annotations

import hashlib

from redis import Redis


class LoginRateLimiter:
    def __init__(self, client: Redis, max_failures: int, lockout_seconds: int) -> None:
        self._r = client
        self._max = max_failures
        self._ttl = lockout_seconds

    @staticmethod
    def _key(identifier: str) -> str:
        digest = hashlib.sha256(identifier.lower().encode()).hexdigest()[:32]
        return f"login-fail:{digest}"

    def is_locked(self, identifier: str) -> bool:
        value = self._r.get(self._key(identifier))
        return value is not None and int(value) >= self._max

    def register_failure(self, identifier: str) -> int:
        key = self._key(identifier)
        pipe = self._r.pipeline()
        pipe.incr(key)
        pipe.expire(key, self._ttl)
        count, _ = pipe.execute()
        return int(count)

    def reset(self, identifier: str) -> None:
        self._r.delete(self._key(identifier))
