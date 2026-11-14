"""Password hashing (Argon2id), session tokens (JWT) and CSRF tokens."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from core.config import Settings

JWT_ALGORITHM = "HS256"
JWT_AUDIENCE = "gce-dashboard"
SESSION_COOKIE = "gce_session"
CSRF_COOKIE = "gce_csrf"
CSRF_HEADER = "X-CSRF-Token"

_hasher = PasswordHasher()  # argon2id with library defaults (OWASP-compliant)


class WeakPasswordError(ValueError):
    """Password does not satisfy the policy."""


def validate_password_policy(password: str, min_length: int) -> None:
    """Minimum length plus at least three character classes."""
    if len(password) < min_length:
        raise WeakPasswordError(f"Password must have at least {min_length} characters")
    classes = [
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(not c.isalnum() for c in password),
    ]
    if sum(classes) < 3:
        raise WeakPasswordError(
            "Password must contain three of: lowercase, uppercase, digit, symbol"
        )


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# A valid hash of a random value, used to keep login timing constant for unknown users.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


@dataclass(frozen=True)
class SessionClaims:
    user_id: int
    session_version: int
    expires_at: datetime


def create_session_token(settings: Settings, user_id: int, session_version: int) -> str:
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "sv": session_version,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "aud": JWT_AUDIENCE,
    }
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_session_token(settings: Settings, token: str) -> SessionClaims | None:
    """Return the claims, or None for any invalid/expired/tampered token."""
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
            options={"require": ["sub", "exp", "sv", "aud"]},
        )
        return SessionClaims(
            user_id=int(payload["sub"]),
            session_version=int(payload["sv"]),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (jwt.PyJWTError, ValueError, KeyError):
        return None


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(cookie_value: str | None, header_value: str | None) -> bool:
    if not cookie_value or not header_value:
        return False
    return secrets.compare_digest(cookie_value, header_value)
