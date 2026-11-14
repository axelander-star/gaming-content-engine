"""Dependency checks for readiness probes."""

from __future__ import annotations

import logging

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def check_database(session: Session) -> bool:
    try:
        session.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        log.warning("database health check failed", exc_info=True)
        return False


def check_redis(client: Redis) -> bool:
    try:
        return bool(client.ping())
    except RedisError:
        log.warning("redis health check failed", exc_info=True)
        return False
