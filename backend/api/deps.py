"""Shared API dependencies: current user, role checks, CSRF protection."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import UserRole
from core.security import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    csrf_matches,
    decode_session_token,
)
from database.session import get_db
from models.access import User

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]

_ROLE_RANK = {UserRole.VIEWER: 0, UserRole.OPERATOR: 1, UserRole.ADMIN: 2}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


def get_current_user(
    db: DbSession,
    settings: AppSettings,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> User:
    """Resolve the session cookie to an active user, or raise 401."""
    if not session_token:
        raise _unauthorized()
    claims = decode_session_token(settings, session_token)
    if claims is None:
        raise _unauthorized()
    user = db.get(User, claims.user_id)
    if user is None or not user.is_active or user.session_version != claims.session_version:
        raise _unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(minimum: UserRole) -> Callable[[User], User]:
    """Dependency factory: user must have at least ``minimum`` role."""

    def checker(user: CurrentUser) -> User:
        if _ROLE_RANK[user.role] < _ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return checker


def csrf_protect(
    request: Request,
    csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
    csrf_header: Annotated[str | None, Header(alias=CSRF_HEADER)] = None,
) -> None:
    """Double-submit CSRF check for every state-changing request."""
    if request.method in _SAFE_METHODS:
        return
    if not csrf_matches(csrf_cookie, csrf_header):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="CSRF check failed")


Viewer = Annotated[User, Depends(require_role(UserRole.VIEWER))]
Operator = Annotated[User, Depends(require_role(UserRole.OPERATOR))]
Admin = Annotated[User, Depends(require_role(UserRole.ADMIN))]
