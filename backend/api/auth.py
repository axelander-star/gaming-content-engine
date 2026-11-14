"""Login, logout and current-user endpoints (cookie-based sessions)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from redis import Redis
from sqlalchemy import select

from api.deps import AppSettings, CurrentUser, DbSession, csrf_protect
from api.schemas import UserOut
from core.config import Settings
from core.security import (
    CSRF_COOKIE,
    DUMMY_HASH,
    SESSION_COOKIE,
    create_session_token,
    hash_password,
    needs_rehash,
    new_csrf_token,
    verify_password,
)
from models.access import User
from services import audit
from services.queue import get_redis
from services.rate_limit import LoginRateLimiter

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


def _limiter(settings: Settings, client: Redis) -> LoginRateLimiter:
    return LoginRateLimiter(
        client, settings.login_max_failures, settings.login_lockout_minutes * 60
    )


def _set_session_cookies(response: Response, settings: Settings, token: str) -> None:
    max_age = settings.access_token_expire_minutes * 60
    common = {
        "max_age": max_age,
        "secure": settings.session_cookie_secure,
        "samesite": "strict",
        "path": "/",
    }
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)  # type: ignore[arg-type]
    response.set_cookie(CSRF_COOKIE, new_csrf_token(), httponly=False, **common)  # type: ignore[arg-type]


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


@router.post("/login", response_model=UserOut)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: AppSettings,
    redis_client: Annotated[Redis, Depends(get_redis)],
) -> User:
    """Check credentials, set an HttpOnly session cookie and a CSRF cookie."""
    email = body.email.lower()
    ip = request.client.host if request.client else "unknown"
    limiter = _limiter(settings, redis_client)
    keys = (f"email:{email}", f"ip:{ip}")
    if any(limiter.is_locked(k) for k in keys):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed logins, try again later"
        )

    user = db.scalar(select(User).where(User.email == email))
    # Always run a hash verification so response time does not reveal unknown accounts.
    valid = verify_password(user.password_hash if user else DUMMY_HASH, body.password)
    if user is None or not valid or not user.is_active:
        for k in keys:
            limiter.register_failure(k)
        audit.record(
            db,
            "auth.login_failed",
            user_id=user.id if user else None,
            message=f"email={email} ip={ip}",
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    for k in keys:
        limiter.reset(k)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.last_login_at = datetime.now(UTC)
    audit.record(db, "auth.login", user_id=user.id, message=f"ip={ip}")
    db.commit()
    _set_session_cookies(
        response, settings, create_session_token(settings, user.id, user.session_version)
    )
    return user


@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(csrf_protect)]
)
def logout(response: Response, user: CurrentUser, db: DbSession) -> Response:
    audit.record(db, "auth.logout", user_id=user.id)
    db.commit()
    _clear_session_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post(
    "/logout-all", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(csrf_protect)]
)
def logout_all(response: Response, user: CurrentUser, db: DbSession) -> Response:
    """Invalidate every session of the current user (all devices)."""
    user.session_version += 1
    audit.record(db, "auth.logout_all", user_id=user.id)
    db.commit()
    _clear_session_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
