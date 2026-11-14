"""Liveness and readiness endpoints (used by Docker, Caddy and Uptime Kuma)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from redis import Redis
from sqlalchemy.orm import Session

from database.session import get_db
from services.health import check_database, check_redis
from services.queue import get_redis

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    redis: bool


@router.get("", response_model=LivenessResponse)
def liveness() -> LivenessResponse:
    """The process is up. Does not touch dependencies."""
    return LivenessResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
def readiness(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    redis_client: Annotated[Redis, Depends(get_redis)],
) -> ReadinessResponse:
    """All dependencies reachable. Returns 503 if any is down (no error details leaked)."""
    db_ok = check_database(db)
    redis_ok = check_redis(redis_client)
    ok = db_ok and redis_ok
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ok" if ok else "degraded", database=db_ok, redis=redis_ok)
