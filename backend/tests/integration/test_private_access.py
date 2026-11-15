"""Private operation: Cloudflare Access check and single-user mode."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import create_admin
from core import access_guard
from core.config import Settings, get_settings
from models.access import User
from tests.conftest import STRONG_PASSWORD, login

pytestmark = pytest.mark.integration

MakeUser = Callable[..., User]
TEAM = "example-team.cloudflareaccess.com"
AUD = "a1b2c3d4e5f6-test-audience"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(
    key: Any = KEY,
    aud: str = AUD,
    iss: str = f"https://{TEAM}",
    email: str = "owner@example.com",
    exp_offset: int = 600,
) -> str:
    now = int(time.time())
    claims = {
        "aud": [aud],
        "iss": iss,
        "email": email,
        "iat": now,
        "exp": now + exp_offset,
        "sub": "user-1",
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})


@pytest.fixture
def guarded(
    monkeypatch: pytest.MonkeyPatch, db: Session, redis_client: Redis
) -> Iterator[TestClient]:
    """API with ACCESS_GUARD=cloudflare; the team's public key is the test key."""
    from app.main import create_app
    from database.session import get_db
    from services.queue import get_redis

    monkeypatch.setenv("ACCESS_GUARD", "cloudflare")
    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", TEAM)
    monkeypatch.setenv("CF_ACCESS_AUD", AUD)
    monkeypatch.setenv("CF_ACCESS_ALLOWED_EMAILS", "Owner@example.com")
    monkeypatch.setattr(access_guard, "signing_key", lambda _s, _t: KEY.public_key())
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_redis] = lambda: redis_client
    try:
        with TestClient(app) as client:
            yield client
    finally:
        get_settings.cache_clear()


def test_request_without_access_token_is_rejected(guarded: TestClient) -> None:
    assert guarded.get("/api/auth/me").status_code == 403
    resp = guarded.post("/api/auth/login", json={"email": "a@b.de", "password": "x"})
    assert resp.status_code == 403
    assert guarded.get("/api/oauth/youtube/callback").status_code == 403


def test_health_stays_reachable_for_container_checks(guarded: TestClient) -> None:
    assert guarded.get("/api/health").status_code == 200


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda: _token(key=OTHER_KEY), id="foreign-signature"),
        pytest.param(lambda: _token(aud="other-app"), id="wrong-audience"),
        pytest.param(lambda: _token(iss="https://evil.cloudflareaccess.com"), id="wrong-issuer"),
        pytest.param(lambda: _token(exp_offset=-120), id="expired"),
        pytest.param(lambda: _token(email="stranger@example.com"), id="not-allow-listed"),
        pytest.param(lambda: "not-a-jwt", id="garbage"),
    ],
)
def test_invalid_access_tokens_are_rejected(guarded: TestClient, token: Callable[[], str]) -> None:
    r = guarded.get("/api/auth/me", headers={access_guard.HEADER: token()})
    assert r.status_code == 403


def test_valid_access_token_reaches_normal_login(guarded: TestClient, make_user: MakeUser) -> None:
    make_user()
    headers = {access_guard.HEADER: _token()}
    # Passing Access is not enough: the app login is still required.
    assert guarded.get("/api/auth/me", headers=headers).status_code == 401
    r = guarded.post(
        "/api/auth/login",
        headers=headers,
        json={"email": "admin@example.com", "password": STRONG_PASSWORD},
    )
    assert r.status_code == 200
    assert guarded.get("/api/auth/me", headers=headers).status_code == 200


def test_access_cookie_is_accepted(guarded: TestClient) -> None:
    guarded.cookies.set(access_guard.COOKIE, _token())
    assert guarded.get("/api/auth/me").status_code == 401  # passed Access, not logged in


def test_cloudflare_guard_needs_team_and_audience() -> None:
    with pytest.raises(ValueError, match="CF_ACCESS_TEAM_DOMAIN"):
        Settings(access_guard="cloudflare", cf_access_team_domain="", cf_access_aud="")


def test_single_user_mode_blocks_new_accounts(
    api: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_user()
    monkeypatch.setenv("SINGLE_USER_MODE", "true")
    get_settings.cache_clear()
    try:
        headers = login(api, "admin@example.com")
        r = api.post(
            "/api/users",
            headers=headers,
            json={"email": "second@example.com", "password": STRONG_PASSWORD},
        )
        assert r.status_code == 403
    finally:
        get_settings.cache_clear()


def test_single_user_mode_cli_refuses_second_admin(
    db: Session, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_user()
    conn = db.connection()
    monkeypatch.setattr(
        create_admin,
        "get_sessionmaker",
        lambda: lambda: Session(bind=conn, join_transaction_mode="create_savepoint"),
    )
    monkeypatch.setenv("SINGLE_USER_MODE", "true")
    monkeypatch.setenv("GCE_ADMIN_PASSWORD", STRONG_PASSWORD)
    get_settings.cache_clear()
    try:
        assert create_admin.main(["--email", "second@example.com"]) == 3
        assert db.scalar(select(func.count()).select_from(User)) == 1
        # Resetting the existing account keeps working.
        assert create_admin.main(["--email", "admin@example.com"]) == 0
    finally:
        get_settings.cache_clear()
