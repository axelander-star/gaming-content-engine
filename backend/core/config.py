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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_name: str = "gaming-content-engine"
    log_level: str = "INFO"

    secret_key: SecretStr = SecretStr(PLACEHOLDER)
    credentials_encryption_key: SecretStr = SecretStr(PLACEHOLDER)

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
            for name in ("secret_key", "credentials_encryption_key"):
                value: SecretStr = getattr(self, name)
                if value.get_secret_value() in ("", PLACEHOLDER):
                    raise ValueError(f"{name.upper()} must be set in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance (call ``get_settings.cache_clear()`` in tests)."""
    return Settings()
