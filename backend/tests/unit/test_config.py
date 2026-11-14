from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from core.config import Settings


def make(**kwargs: Any) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "AUTO_PUBLISH_ENABLED",
        "PUBLISHING_MODE",
        "EMERGENCY_STOP",
        "PAID_API_CALLS_ENABLED",
    ):
        monkeypatch.delenv(var, raising=False)
    s = make()
    assert s.auto_publish_enabled is False
    assert s.publishing_mode == "mock"
    assert s.paid_api_calls_enabled is False
    assert s.emergency_stop is False
    assert s.publishing_allowed is False


def test_publishing_allowed_requires_all_switches() -> None:
    assert make(auto_publish_enabled=True, publishing_mode="live").publishing_allowed is True
    assert make(auto_publish_enabled=True, publishing_mode="mock").publishing_allowed is False
    assert (
        make(
            auto_publish_enabled=True, publishing_mode="live", emergency_stop=True
        ).publishing_allowed
        is False
    )


def test_invalid_publishing_mode_rejected() -> None:
    with pytest.raises(ValidationError):
        make(publishing_mode="yolo")


def test_production_refuses_placeholder_secrets() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        make(app_env="production", secret_key="change-me", session_cookie_secure=True)
    ok = make(
        app_env="production",
        secret_key="x" * 40,
        credentials_encryption_key="y" * 40,
        session_cookie_secure=True,
    )
    assert ok.app_env == "production"


def test_budget_thresholds_must_ascend() -> None:
    with pytest.raises(ValidationError, match="ascending"):
        make(budget_warn_pct=80, budget_reduced_pct=70)


def test_database_url_built_from_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = make(postgres_host="db", postgres_user="u", postgres_password="p", postgres_db="x")
    assert s.database_url == "postgresql+psycopg://u:p@db:5432/x"


def test_secrets_not_in_repr() -> None:
    s = make(secret_key="super-secret-value")
    assert "super-secret-value" not in repr(s)
