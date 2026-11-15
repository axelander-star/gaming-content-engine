"""Redis connection and job queue (RQ).

Queues are named by priority. Jobs get a deterministic ``job_id`` so the same
logical job cannot be enqueued twice while it is still known to Redis.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from redis import Redis
from rq import Queue
from rq.job import Job

from core.config import get_settings

QUEUE_NAMES = ("high", "default", "low", "research")
_JOB_ID_INVALID = re.compile(r"[^A-Za-z0-9_-]")


def normalize_job_id(job_id: str) -> str:
    """RQ only accepts letters, digits, ``_`` and ``-``; map everything else to ``-``."""
    return _JOB_ID_INVALID.sub("-", job_id)


@lru_cache
def get_redis() -> Redis:
    s = get_settings()
    password = s.redis_password.get_secret_value() or None
    return Redis(
        host=s.redis_host,
        port=s.redis_port,
        db=s.redis_db,
        password=password,
        socket_connect_timeout=3,
        socket_timeout=10,
    )


def get_queue(name: str = "default", connection: Redis | None = None) -> Queue:
    if name not in QUEUE_NAMES:
        raise ValueError(f"Unknown queue '{name}'. Allowed: {QUEUE_NAMES}")
    return Queue(
        name,
        connection=connection or get_redis(),
        default_timeout=get_settings().queue_default_timeout_s,
    )


def enqueue_unique(
    func: Callable[..., Any],
    job_id: str,
    *args: Any,
    queue: str = "default",
    connection: Redis | None = None,
    **kwargs: Any,
) -> Job:
    """Enqueue ``func`` unless a job with ``job_id`` is already queued or running.

    Returns the existing job in that case (idempotent enqueue).
    """
    job_id = normalize_job_id(job_id)
    q = get_queue(queue, connection)
    existing = q.fetch_job(job_id)
    if existing is not None and existing.get_status(refresh=True) in {
        "queued",
        "started",
        "deferred",
        "scheduled",
    }:
        return existing
    return q.enqueue(func, *args, job_id=job_id, **kwargs)
