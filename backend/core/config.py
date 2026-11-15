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
    #: Previous keys during a rotation, comma-separated (Phase 15); empty otherwise.
    credentials_encryption_key_old: SecretStr = SecretStr("")

    # --- Sessions / login (Phase 3) ---
    access_token_expire_minutes: int = Field(default=30, gt=0, le=24 * 60)
    session_cookie_secure: bool = True  # set False only for local HTTP development
    login_max_failures: int = Field(default=5, gt=0)
    login_lockout_minutes: int = Field(default=15, gt=0)
    password_min_length: int = Field(default=12, ge=8)

    # --- Private operation (single operator behind Cloudflare Access) ---
    #: Refuse to create further accounts once one exists (dashboard and CLI).
    single_user_mode: bool = False
    #: ``cloudflare``: every API request (except ``/api/health``) must carry a valid
    #: Cloudflare Access token. ``none``: no check (local development, tests).
    access_guard: Literal["none", "cloudflare"] = "none"
    #: Team domain of the Zero Trust organisation, e.g. ``myteam.cloudflareaccess.com``.
    cf_access_team_domain: str = ""
    #: Application Audience (AUD) tag of the Access application.
    cf_access_aud: str = ""
    #: Optional comma-separated allow list of e-mail addresses (second check behind Access).
    cf_access_allowed_emails: str = ""

    # --- Safety switches (PROJECT_SPEC section 15) ---
    auto_publish_enabled: bool = False
    publishing_mode: Literal["mock", "live"] = "mock"
    emergency_stop: bool = False
    paid_api_calls_enabled: bool = False

    # --- Publishing (Phase 12) ---
    #: Google OAuth client (web application) for connecting YouTube channels.
    youtube_oauth_client_id: str = ""
    youtube_oauth_client_secret: SecretStr = SecretStr("")
    youtube_oauth_redirect_uri: str = "http://localhost:3000/api/oauth/youtube/callback"
    #: Visibility of uploads; stays private until the operator decides otherwise.
    youtube_upload_privacy: Literal["private", "unlisted", "public"] = "private"
    #: videos.insert has its own bucket of 100 calls per day (official quota calculator).
    youtube_daily_upload_limit: int = Field(default=100, ge=0, le=100_000)
    publish_upload_attempts: int = Field(default=5, ge=1, le=20)
    #: Status checks after an upload until the platform reports the post (Phase 13).
    publish_status_polls: int = Field(default=10, ge=1, le=60)
    publish_status_interval_seconds: float = Field(default=30.0, ge=0, le=600)

    # --- TikTok (Phase 13, Content Posting API) ---
    tiktok_client_key: str = ""
    tiktok_client_secret: SecretStr = SecretStr("")
    #: TikTok only accepts https redirect URIs; on the server use the dashboard domain.
    tiktok_oauth_redirect_uri: str = "http://localhost:3000/api/oauth/tiktok/callback"
    #: Unaudited apps may only post privately; SELF_ONLY stays the default.
    tiktok_privacy_level: Literal[
        "SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "PUBLIC_TO_EVERYONE"
    ] = "SELF_ONLY"
    #: Set only once TikTok has audited the app; until then channels stay restricted.
    tiktok_app_audited: bool = False
    #: Own cap per channel and day (TikTok publishes no fixed number).
    tiktok_daily_post_limit: int = Field(default=5, ge=0, le=1000)

    # --- Meta: Instagram and Facebook Reels (Phase 13, Graph API) ---
    meta_app_id: str = ""
    meta_app_secret: SecretStr = SecretStr("")
    meta_oauth_redirect_uri: str = "http://localhost:3000/api/oauth/meta/callback"
    #: Instagram: 50 API posts per 24 h (content_publishing_limit); Facebook Pages: 30 Reels.
    instagram_daily_post_limit: int = Field(default=50, ge=0, le=50)
    facebook_daily_reels_limit: int = Field(default=30, ge=0, le=30)

    # --- Budget (PROJECT_SPEC section 13) ---
    monthly_budget_eur: float = Field(default=50.0, ge=0)
    budget_warn_pct: int = Field(default=50, ge=0, le=100)
    budget_reduced_pct: int = Field(default=70, ge=0, le=100)
    budget_priority_only_pct: int = Field(default=85, ge=0, le=100)
    budget_stop_paid_pct: int = Field(default=95, ge=0, le=100)
    #: Fixed monthly costs (Phase 14). Enter the current provider prices; they count
    #: fully against the month's budget because they run even when production pauses.
    server_monthly_eur: float = Field(default=0.0, ge=0)
    other_fixed_monthly_eur: float = Field(default=0.0, ge=0)  # backups, domain, …
    #: Storage price per GB and month (e.g. object storage), for the cost estimate.
    storage_eur_per_gb_month: float = Field(default=0.0, ge=0)

    # --- AI layer (extension phase E3) ---
    #: Claude API key. Only in the server environment or a secrets manager, never in git.
    anthropic_api_key: SecretStr = SecretStr("")
    #: Hard monthly ceiling for AI calls in US dollars (operator decision 15.11.2026).
    #: The dashboard can lower the cap, never raise it above this value.
    ai_monthly_cap_usd_max: float = Field(default=20.0, ge=0, le=1000)
    #: Cheap model for short texts (titles, descriptions, hooks).
    ai_model_text: str = "claude-haiku-5-5"
    #: Model for chat, ideas and planning.
    ai_model_reasoning: str = "claude-sonnet-5-5"
    #: Conversion for booking AI costs into the EUR budget; update when the rate moves.
    eur_per_usd: float = Field(default=0.92, gt=0, le=10)
    #: Longest prompt (characters) one call may send; keeps every call small and bounded.
    ai_max_input_chars: int = Field(default=60_000, ge=1000, le=400_000)
    ai_request_timeout_s: float = Field(default=60.0, gt=0, le=600)

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
    #: Minutes between two planning runs of the Publishing Strategy Agent per channel.
    strategy_interval_minutes: int = Field(default=60, ge=1, le=24 * 60)
    agent_max_retries: int = Field(default=3, ge=0, le=20)
    agent_retry_base_delay_s: int = Field(default=300, ge=0)
    trend_research_seconds: int = Field(default=6 * 3600, ge=300)
    #: Analytics sweep (Phase 14): measures posts at 1 h, 6 h, 24 h, 48 h, 7 days.
    analytics_seconds: int = Field(default=1800, ge=60)
    analytics_batch_size: int = Field(default=500, ge=1, le=10_000)
    #: Learning Agent (Phase 14): evaluates trials and derives new factors.
    learning_seconds: int = Field(default=6 * 3600, ge=300)
    game_intelligence_seconds: int = Field(default=24 * 3600, ge=300)
    rights_sweep_seconds: int = Field(default=24 * 3600, ge=300)  # license expiry monitoring
    material_needs_seconds: int = Field(default=24 * 3600, ge=300)
    #: Research and idea lab (extension phase E5).
    research_seconds: int = Field(default=6 * 3600, ge=300)
    ideas_seconds: int = Field(default=24 * 3600, ge=300)

    # --- Operations (Phase 15): monitoring, alerts, backups ---
    #: How often the scheduler runs the system checks (and pushes to Uptime Kuma).
    monitor_seconds: int = Field(default=60, ge=15)
    #: Optional Uptime Kuma push monitor URL (``.../api/push/<token>``); contains a token.
    uptime_kuma_push_url: SecretStr = SecretStr("")
    disk_warn_pct: float = Field(default=80.0, gt=0, le=100)
    disk_critical_pct: float = Field(default=90.0, gt=0, le=100)
    #: A job waiting longer than this in a queue counts as backlog.
    queue_wait_warn_s: int = Field(default=1800, ge=60)
    #: Failed agent runs in the last 24 h (share of all runs) before a warning.
    agent_error_warn_ratio: float = Field(default=0.2, gt=0, le=1)
    backup_dir: str = "./data/backups"
    #: Symmetric key for the GnuPG-encrypted dumps. Without it no backup is written.
    backup_passphrase: SecretStr = SecretStr("")
    backup_hour: int = Field(default=3, ge=0, le=23)  # local time (TZ)
    backup_keep_days: int = Field(default=14, ge=1)
    backup_keep_min: int = Field(default=3, ge=1)  # never prune below this many dumps
    backup_max_age_hours: int = Field(default=30, ge=1)  # older last backup = alert
    backup_timeout_s: int = Field(default=3600, ge=60)
    timezone: str = Field(default="Europe/Berlin", alias="TZ")

    # --- Local file storage (Phase 6: license documents; R2 follows later) ---
    media_root: str = "./data/media"
    max_document_bytes: int = Field(default=10 * 1024 * 1024, gt=0)

    # --- Gameplay analysis and clip production (Phase 7) ---
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    production_job_timeout_s: int = Field(default=3600, ge=60)
    max_upload_bytes: int = Field(default=4 * 1024**3, gt=0)  # one gameplay file
    #: Resumable uploads: size of one part. Cloudflare passes at most 100 MB per
    #: request on the free plan, so parts stay well below that.
    upload_chunk_bytes: int = Field(default=16 * 1024**2, ge=256 * 1024, le=64 * 1024**2)
    #: Unfinished upload sessions (and their partial files) are removed after this time.
    upload_session_ttl_hours: int = Field(default=24, ge=1, le=24 * 14)
    min_material_s: float = Field(default=10.0, gt=0)
    max_material_s: float = Field(default=4 * 3600.0, gt=0)
    min_source_height: int = Field(default=720, ge=144)  # shorter side of the source
    analysis_sample_fps: float = Field(default=2.0, gt=0, le=10)
    clip_target_s: float = Field(default=30.0, gt=0)
    clip_min_s: float = Field(default=15.0, gt=0)
    clip_max_s: float = Field(default=60.0, gt=0)
    max_clips_per_material: int = Field(default=3, ge=0, le=20)
    min_scene_score: float = Field(default=0.35, ge=0, le=1)
    render_preset: Literal[
        "ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"
    ] = "medium"
    render_crf: int = Field(default=20, ge=14, le=30)
    render_max_fps: float = Field(default=60.0, gt=0)
    render_slot_ttl_s: int = Field(default=2 * 3600, ge=60)  # stale slot after a crash
    max_clip_bytes: int = Field(default=250 * 1024**2, gt=0)  # conservative own limit

    # --- Trend sources (Phase 5). "mock" needs no keys and makes no network calls. ---
    trend_sources_mode: Literal["mock", "live"] = "mock"
    youtube_api_key: SecretStr = SecretStr("")
    youtube_daily_quota_units: int = Field(default=2000, ge=0)  # own cap below Google's quota
    twitch_client_id: str = ""
    twitch_client_secret: SecretStr = SecretStr("")
    twitch_max_requests_per_run: int = Field(default=20, ge=0)
    steam_max_requests_per_run: int = Field(default=30, ge=0)
    http_timeout_s: float = Field(default=10.0, gt=0)

    # --- Research feeds (extension phase E5). "mock" makes no network calls. ---
    research_sources_mode: Literal["mock", "live"] = "mock"
    research_max_feed_bytes: int = Field(default=2 * 1024**2, gt=0)
    research_items_per_source: int = Field(default=30, ge=1, le=200)
    #: Ideas the idea lab drafts per topic area and run.
    ideas_per_run: int = Field(default=5, ge=1, le=20)

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
    def cf_access_emails(self) -> set[str]:
        """Allowed e-mail addresses (lower case); empty means "any user Access lets in"."""
        return {e.strip().lower() for e in self.cf_access_allowed_emails.split(",") if e.strip()}

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
        if self.access_guard == "cloudflare" and not (
            self.cf_access_team_domain.strip() and self.cf_access_aud.strip()
        ):
            raise ValueError(
                "ACCESS_GUARD=cloudflare needs CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD"
            )
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
