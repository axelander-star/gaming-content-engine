from __future__ import annotations

from datetime import UTC, datetime

import jwt
import pytest

from core.config import Settings
from core.security import (
    WeakPasswordError,
    create_session_token,
    csrf_matches,
    decode_session_token,
    hash_password,
    validate_password_policy,
    verify_password,
)


def settings(**kw: object) -> Settings:
    return Settings(_env_file=None, secret_key="k" * 40, **kw)  # type: ignore[arg-type]


def test_hash_and_verify() -> None:
    h = hash_password("Richtig-Passwort-1")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "Richtig-Passwort-1")
    assert not verify_password(h, "falsch")
    assert not verify_password("not-a-hash", "x")


@pytest.mark.parametrize("pw", ["kurz", "alleskleinbuchstaben", "ALLESGROSS123456"])
def test_weak_passwords_rejected(pw: str) -> None:
    with pytest.raises(WeakPasswordError):
        validate_password_policy(pw, 12)


def test_strong_password_accepted() -> None:
    validate_password_policy("Sicher-Passwort-2026", 12)


def test_token_roundtrip() -> None:
    s = settings()
    claims = decode_session_token(s, create_session_token(s, user_id=7, session_version=3))
    assert claims is not None
    assert (claims.user_id, claims.session_version) == (7, 3)
    assert claims.expires_at > datetime.now(UTC)


def test_token_with_other_key_rejected() -> None:
    token = create_session_token(settings(), 1, 1)
    other = Settings(_env_file=None, secret_key="x" * 40)
    assert decode_session_token(other, token) is None


def test_expired_token_rejected() -> None:
    s = settings()
    token = jwt.encode(
        {"sub": "1", "sv": 1, "exp": 1, "aud": "gce-dashboard"},
        s.secret_key.get_secret_value(),
        algorithm="HS256",
    )
    assert decode_session_token(s, token) is None


def test_alg_none_rejected() -> None:
    token = jwt.encode(
        {"sub": "1", "sv": 1, "exp": 9999999999, "aud": "gce-dashboard"}, key="", algorithm="none"
    )
    assert decode_session_token(settings(), token) is None


def test_csrf_compare() -> None:
    assert csrf_matches("abc", "abc")
    assert not csrf_matches("abc", "abd")
    assert not csrf_matches(None, "abc")
    assert not csrf_matches("abc", None)


def test_production_requires_secure_cookies() -> None:
    with pytest.raises(ValueError, match="SESSION_COOKIE_SECURE"):
        Settings(
            _env_file=None,
            app_env="production",
            secret_key="a" * 40,
            credentials_encryption_key="b" * 40,
            session_cookie_secure=False,
        )
