"""Application settings loaded from environment variables.

All safety switches default to the safe value (no publishing, mock mode, no paid
calls). In ``production`` the settings refuse to start with placeholder secrets.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER = "change-me"


class Settings(BaseSettings):
    """Typed runtime configuration. Field names map to upper-case env vars."""

    # ``.env`` in the repository root (docker compose) and in ``backend/`` (local run);
    # empty values count as "not set", so a blank line never overrides a real value.
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_name: str = "gaming-content-engine"
    log_level: str = "INFO"

    secret_key: SecretStr = SecretStr(PLACEHOLDER)
    credentials_encryption_key: SecretStr = SecretStr(PLACEHOLDER)

    # --- Sessions / login (Phase 3) ---
    access_token_expire_minutes: int = Field(default=30, gt=0, le=24 * 60)
    session_cookie_secure: bool = True  # set False only for local HTTP development
    login_max_failures: int = Field(default=5, gt=0)
    login_lockout_minutes: int = Field(default=15, gt=0)
    password_min_length: int = Field(default=12, ge=8)

    # --- Safety switches (PROJECT_SPEC section 15) ---
    auto_publish_enabled: bool = False
    publishing_mode: Literal["mock", "live"] = "mock"
    emergency_stop: bool = False
    paid_api_calls_enabled: bool = False

    # --- Budget (PROJECT_SPEC section 13) ---
    monthly_budget_eur: float = Field(default=50.0, ge=0)
    budget_warn_pct: int = Field(default=50, ge=0, le=100)
    budget_reduced_pct: int = Field(default=70, ge=0, le=100)
    budget_priority_only_pct: int = Field(default=85, ge=0, le=100)
    budget_stop_paid_pct: int = Field(default=95, ge=0, le=100)

    # --- PostgreSQL ---
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "gce"
    postgres_user: str = "gce"
    postgres_password: SecretStr = SecretStr("")
    database_url_override: str | None = Field(default=None, alias="DATABASE_URL")

    # --- Redis ---
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: SecretStr = SecretStr("")
    redis_db: int = 0
    queue_default_timeout_s: int = Field(default=600, gt=0)

    # --- Agents / scheduler (Phase 4) ---
    master_tick_seconds: int = Field(default=300, ge=10)
    budget_check_seconds: int = Field(default=3600, ge=60)
    master_batch_size: int = Field(default=25, ge=1, le=1000)
    agent_max_retries: int = Field(default=3, ge=0, le=20)
    agent_retry_base_delay_s: int = Field(default=300, ge=0)
    trend_research_seconds: int = Field(default=6 * 3600, ge=300)
    game_intelligence_seconds: int = Field(default=24 * 3600, ge=300)
    rights_sweep_seconds: int = Field(default=24 * 3600, ge=300)  # license expiry monitoring
    material_needs_seconds: int = Field(default=24 * 3600, ge=300)

    # --- Local file storage (Phase 6: license documents; R2 follows later) ---
    media_root: str = "./data/media"
    max_document_bytes: int = Field(default=10 * 1024 * 1024, gt=0)

    # --- Trend sources (Phase 5). "mock" needs no keys and makes no network calls. ---
    trend_sources_mode: Literal["mock", "live"] = "mock"
    youtube_api_key: SecretStr = SecretStr("")
    youtube_daily_quota_units: int = Field(default=2000, ge=0)  # own cap below Google's quota
    twitch_client_id: str = ""
    twitch_client_secret: SecretStr = SecretStr("")
    twitch_max_requests_per_run: int = Field(default=20, ge=0)
    steam_max_requests_per_run: int = Field(default=30, ge=0)
    http_timeout_s: float = Field(default=10.0, gt=0)

    @property
    def database_url(self) -> str:
        """SQLAlchemy URL for psycopg 3."""
        if self.database_url_override:
            return self.database_url_override
        pw = self.postgres_password.get_secret_value()
        auth = f"{self.postgres_user}:{pw}" if pw else self.postgres_user
        return (
            f"postgresql+psycopg://{auth}@{self.postgres_host}:"
            f"{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def publishing_allowed(self) -> bool:
        """True only if every global switch permits a real publication."""
        return (
            self.auto_publish_enabled and self.publishing_mode == "live" and not self.emergency_stop
        )

    @model_validator(mode="after")
    def _check_consistency(self) -> Settings:
        thresholds = [
            self.budget_warn_pct,
            self.budget_reduced_pct,
            self.budget_priority_only_pct,
            self.budget_stop_paid_pct,
        ]
        if thresholds != sorted(thresholds):
            raise ValueError("Budget thresholds must be ascending (warn <= reduced <= ...)")
        if self.app_env == "production":
            if not self.session_cookie_secure:
                raise ValueError("SESSION_COOKIE_SECURE must be true in production")
            for name in ("secret_key", "credentials_encryption_key"):
                value: SecretStr = getattr(self, name)
                if value.get_secret_value() in ("", PLACEHOLDER):
                    raise ValueError(f"{name.upper()} must be set in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance (call ``get_settings.cache_clear()`` in tests)."""
    return Settings()
