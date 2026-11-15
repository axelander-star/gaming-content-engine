"""Login, sessions, CSRF, rate limiting and user management."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import UserRole
from models.access import AuditLog, User
from tests.conftest import STRONG_PASSWORD, login

pytestmark = pytest.mark.integration

MakeUser = Callable[..., User]


def test_login_sets_httponly_session_and_csrf_cookie(api: TestClient, make_user: MakeUser) -> None:
    make_user()
    r = api.post(
        "/api/auth/login", json={"email": "Admin@Example.com", "password": STRONG_PASSWORD}
    )
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
    assert "password_hash" not in r.json()
    set_cookie = r.headers.get_list("set-cookie")
    session = next(c for c in set_cookie if c.startswith("gce_session="))
    csrf = next(c for c in set_cookie if c.startswith("gce_csrf="))
    assert "HttpOnly" in session and "SameSite=strict" in session
    assert "HttpOnly" not in csrf


def test_me_requires_login(api: TestClient) -> None:
    assert api.get("/api/auth/me").status_code == 401


def test_me_after_login(api: TestClient, make_user: MakeUser) -> None:
    make_user()
    login(api, "admin@example.com")
    assert api.get("/api/auth/me").json()["email"] == "admin@example.com"


def test_wrong_password_and_unknown_user_look_identical(
    api: TestClient, make_user: MakeUser
) -> None:
    make_user()
    a = api.post("/api/auth/login", json={"email": "admin@example.com", "password": "falsch"})
    b = api.post("/api/auth/login", json={"email": "nobody@example.com", "password": "falsch"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_inactive_user_cannot_login(api: TestClient, make_user: MakeUser) -> None:
    make_user(is_active=False)
    r = api.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": STRONG_PASSWORD}
    )
    assert r.status_code == 401


def test_login_lockout_after_repeated_failures(api: TestClient, make_user: MakeUser) -> None:
    make_user()
    for _ in range(5):
        api.post("/api/auth/login", json={"email": "admin@example.com", "password": "falsch"})
    r = api.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": STRONG_PASSWORD}
    )
    assert r.status_code == 429


def test_login_and_failure_are_audited(api: TestClient, make_user: MakeUser, db: Session) -> None:
    make_user()
    api.post("/api/auth/login", json={"email": "admin@example.com", "password": "falsch"})
    login(api, "admin@example.com")
    actions = set(db.scalars(select(AuditLog.action)))
    assert {"auth.login_failed", "auth.login"} <= actions


def test_tampered_token_rejected(api: TestClient, make_user: MakeUser) -> None:
    make_user()
    login(api, "admin@example.com")
    token = api.cookies["gce_session"]
    tampered = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")
    # replace, not add: with httpx2 a second cookie of the same name would be sent too
    api.cookies.clear()
    api.cookies.set("gce_session", tampered)
    assert api.get("/api/auth/me").status_code == 401


def test_unsafe_request_without_csrf_header_rejected(api: TestClient, make_user: MakeUser) -> None:
    make_user()
    login(api, "admin@example.com")
    assert api.post("/api/auth/logout").status_code == 403


def test_logout_clears_session(api: TestClient, make_user: MakeUser) -> None:
    make_user()
    headers = login(api, "admin@example.com")
    assert api.post("/api/auth/logout", headers=headers).status_code == 204
    assert api.get("/api/auth/me").status_code == 401


def test_logout_all_invalidates_existing_tokens(api: TestClient, make_user: MakeUser) -> None:
    make_user()
    headers = login(api, "admin@example.com")
    old_token = api.cookies["gce_session"]
    assert api.post("/api/auth/logout-all", headers=headers).status_code == 204
    api.cookies.set("gce_session", old_token)
    assert api.get("/api/auth/me").status_code == 401


# --- user management ---------------------------------------------------------


def test_viewer_cannot_list_users(api: TestClient, make_user: MakeUser) -> None:
    make_user(email="viewer@example.com", role=UserRole.VIEWER)
    login(api, "viewer@example.com")
    assert api.get("/api/users").status_code == 403


def test_admin_creates_user_with_strong_password_only(api: TestClient, make_user: MakeUser) -> None:
    make_user()
    headers = login(api, "admin@example.com")
    weak = api.post(
        "/api/users", headers=headers, json={"email": "op@example.com", "password": "kurz"}
    )
    assert weak.status_code == 422
    ok = api.post(
        "/api/users",
        headers=headers,
        json={"email": "op@example.com", "password": STRONG_PASSWORD, "role": "operator"},
    )
    assert ok.status_code == 201
    assert ok.json()["role"] == "operator"
    dup = api.post(
        "/api/users", headers=headers, json={"email": "OP@example.com", "password": STRONG_PASSWORD}
    )
    assert dup.status_code == 409


def test_last_admin_cannot_be_demoted(api: TestClient, make_user: MakeUser) -> None:
    admin = make_user()
    headers = login(api, "admin@example.com")
    r = api.patch(f"/api/users/{admin.id}", headers=headers, json={"role": "viewer"})
    assert r.status_code == 409


def test_role_change_forces_relogin(api: TestClient, make_user: MakeUser, db: Session) -> None:
    make_user()
    other = make_user(email="second@example.com")
    headers = login(api, "admin@example.com")
    r = api.patch(f"/api/users/{other.id}", headers=headers, json={"role": "viewer"})
    assert r.status_code == 200
    db.refresh(other)
    assert other.session_version == 2
