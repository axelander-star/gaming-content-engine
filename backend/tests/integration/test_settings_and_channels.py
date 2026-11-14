"""Emergency stop, auto-publish switch, operator settings and channel controls."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from core.config import get_settings
from core.enums import UserRole
from models.access import User
from services.controls import effective_controls
from services.seed import seed_base_data
from tests.conftest import login

pytestmark = pytest.mark.integration

MakeUser = Callable[..., User]


def test_defaults_are_safe(api: TestClient, make_user: MakeUser) -> None:
    make_user(role=UserRole.VIEWER, email="v@example.com")
    login(api, "v@example.com")
    controls = api.get("/api/settings").json()["controls"]
    assert controls["emergency_stop"] is False
    assert controls["auto_publish_enabled"] is False
    assert controls["publishing_allowed"] is False
    assert controls["publishing_mode"] == "mock"


def test_viewer_cannot_change_controls(api: TestClient, make_user: MakeUser) -> None:
    make_user(role=UserRole.VIEWER, email="v@example.com")
    headers = login(api, "v@example.com")
    r = api.patch("/api/settings/controls", headers=headers, json={"emergency_stop": True})
    assert r.status_code == 403


def test_operator_can_activate_but_not_release_emergency_stop(
    api: TestClient, make_user: MakeUser
) -> None:
    make_user(role=UserRole.OPERATOR, email="op@example.com")
    headers = login(api, "op@example.com")
    on = api.patch("/api/settings/controls", headers=headers, json={"emergency_stop": True})
    assert on.status_code == 200
    assert on.json()["emergency_stop"] is True
    off = api.patch("/api/settings/controls", headers=headers, json={"emergency_stop": False})
    assert off.status_code == 403


def test_admin_releases_emergency_stop_and_change_is_audited(
    api: TestClient, make_user: MakeUser, db: Session
) -> None:
    make_user()
    headers = login(api, "admin@example.com")
    api.patch("/api/settings/controls", headers=headers, json={"emergency_stop": True})
    r = api.patch("/api/settings/controls", headers=headers, json={"emergency_stop": False})
    assert r.json()["emergency_stop"] is False
    from sqlalchemy import select

    from models.access import AuditLog

    logs = db.scalars(select(AuditLog).where(AuditLog.action == "settings.controls.update")).all()
    assert len(logs) == 2
    assert logs[-1].before == {"emergency_stop": True, "auto_publish_enabled": False}


def test_auto_publish_blocked_by_server_configuration(api: TestClient, make_user: MakeUser) -> None:
    make_user()
    headers = login(api, "admin@example.com")
    r = api.patch("/api/settings/controls", headers=headers, json={"auto_publish_enabled": True})
    assert r.status_code == 409


def test_publishing_needs_env_db_and_live_mode(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.controls import update_runtime_controls

    monkeypatch.setenv("AUTO_PUBLISH_ENABLED", "true")
    get_settings.cache_clear()
    try:
        update_runtime_controls(db, user_id=None, auto_publish_enabled=True)
        assert effective_controls(db, get_settings()).publishing_allowed is False  # still mock
        monkeypatch.setenv("PUBLISHING_MODE", "live")
        get_settings.cache_clear()
        assert effective_controls(db, get_settings()).publishing_allowed is True
        update_runtime_controls(db, user_id=None, emergency_stop=True)
        assert effective_controls(db, get_settings()).publishing_allowed is False
    finally:
        get_settings.cache_clear()


def test_operations_settings_validation(api: TestClient, make_user: MakeUser) -> None:
    make_user()
    headers = login(api, "admin@example.com")
    ok = api.patch(
        "/api/settings/operations",
        headers=headers,
        json={"monthly_budget_eur": 40, "max_parallel_render_jobs": 2},
    )
    assert ok.status_code == 200
    assert ok.json()["monthly_budget_eur"] == 40
    bad = api.patch(
        "/api/settings/operations", headers=headers, json={"max_parallel_render_jobs": 0}
    )
    assert bad.status_code == 422
    unknown = api.patch("/api/settings/operations", headers=headers, json={"foo": 1})
    assert unknown.status_code == 422


def test_operator_cannot_change_operations(api: TestClient, make_user: MakeUser) -> None:
    make_user(role=UserRole.OPERATOR, email="op@example.com")
    headers = login(api, "op@example.com")
    r = api.patch("/api/settings/operations", headers=headers, json={"monthly_budget_eur": 1})
    assert r.status_code == 403


def test_channels_pause_resume_and_limits(
    api: TestClient, make_user: MakeUser, db: Session
) -> None:
    seed_base_data(db)
    make_user(role=UserRole.OPERATOR, email="op@example.com")
    make_user()
    op_headers = login(api, "op@example.com")
    channels = api.get("/api/channels").json()
    assert len(channels) == 8
    cid = channels[0]["id"]
    assert api.post(f"/api/channels/{cid}/pause", headers=op_headers).status_code == 200
    assert api.post(f"/api/channels/{cid}/resume", headers=op_headers).status_code == 403

    admin_headers = login(api, "admin@example.com")
    assert (
        api.post(f"/api/channels/{cid}/resume", headers=admin_headers).json()["is_paused"] is False
    )
    bad = api.put(
        f"/api/channels/{cid}/limits",
        headers=admin_headers,
        json={"min_posts_per_day": 3, "max_posts_per_day": 1, "min_interval_minutes": 30},
    )
    assert bad.status_code == 422
    good = api.put(
        f"/api/channels/{cid}/limits",
        headers=admin_headers,
        json={"min_posts_per_day": 0, "max_posts_per_day": 3, "min_interval_minutes": 90},
    )
    assert good.json()["max_posts_per_day"] == 3


def test_overview_counts(api: TestClient, make_user: MakeUser, db: Session) -> None:
    seed_base_data(db)
    make_user(role=UserRole.VIEWER, email="v@example.com")
    login(api, "v@example.com")
    data = api.get("/api/overview").json()
    assert data["channels_total"] == 8
    assert data["channels_active"] == 0
    assert data["published_videos"] == 0
    assert data["controls"]["publishing_allowed"] is False


def test_protected_endpoints_require_login(api: TestClient) -> None:
    for path in ("/api/settings", "/api/channels", "/api/overview", "/api/users"):
        assert api.get(path).status_code == 401, path
