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


PRIVATE_SESSION_MINUTES = 365 * 24 * 60


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
    #: "inbox": upload as draft, the creator posts in the app (default, extension E8);
    #: "direct": Direct Post (needs an audited app for anything but private posts).
    tiktok_post_mode: Literal["inbox", "direct"] = "inbox"
    #: Own cap per channel and day (TikTok publishes no fixed number).
    tiktok_daily_post_limit: int = Field(default=5, ge=0, le=1000)

    # --- Meta: Instagram and Facebook Reels (Phase 13, Graph API) ---
    meta_app_id: str = ""
    meta_app_secret: SecretStr = SecretStr("")
    meta_oauth_redirect_uri: str = "http://localhost:3000/api/oauth/meta/callback"
    #: Instagram: 50 API posts per 24 h (content_publishing_limit); Facebook Pages: 30 Reels.
    instagram_daily_post_limit: int = Field(default=50, ge=0, le=50)
    facebook_daily_reels_limit: int = Field(default=30, ge=0, le=30)

    # --- Instagram API with Instagram Login (extension E8, no Facebook Page needed) ---
    #: How Instagram channels connect: "instagram" (Instagram Login, own app id) or
    #: "facebook" (Facebook Login for Business via a Page, Phase 13).
    instagram_login: Literal["instagram", "facebook"] = "instagram"
    instagram_app_id: str = ""
    instagram_app_secret: SecretStr = SecretStr("")
    instagram_oauth_redirect_uri: str = "http://localhost:3000/api/oauth/instagram/callback"

    # --- Cloudflare R2 (extension E8): short-lived public video address for Instagram ---
    r2_account_id: str = ""
    r2_bucket: str = ""
    r2_access_key_id: SecretStr = SecretStr("")
    r2_secret_access_key: SecretStr = SecretStr("")
    #: Lifetime of the presigned address Meta fetches the video from.
    r2_presign_seconds: int = Field(default=900, ge=60, le=3600)

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

    # --- Instant server update (GitHub webhook, 27.11.2026) ---
    #: Folder shared with the server (bind mount): the host writes ``secret`` and the
    #: watcher heartbeat, the backend writes ``trigger`` when GitHub reports a push to main.
    deploy_hook_dir: str = "./data/deploy-hook"
    #: Branch whose pushes start an update (only main receives merged, CI-green changes).
    deploy_hook_branch: str = "main"

    # --- Local file storage (Phase 6: license documents; R2 follows later) ---
    media_root: str = "./data/media"
    max_document_bytes: int = Field(default=10 * 1024 * 1024, gt=0)

    # --- Gameplay analysis and clip production (Phase 7) ---
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    #: Piper voice (decision 16.11.2026): local, free, models below ``piper_voice_dir``.
    piper_bin: str = "piper"
    piper_voice_dir: str = "./data/piper-voices"
    piper_voice_de: str = "de_DE-thorsten-medium"
    piper_voice_en: str = "en_US-ljspeech-high"
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

    #: Invented sample data (fictional games, example feeds, test competitors and test
    #: alarms) while a source is in mock mode. Unset means: on everywhere except
    #: production, so the live dashboard only ever shows real data.
    sample_data: bool | None = None

    # --- Research feeds (extension phase E5). "mock" makes no network calls. ---
    research_sources_mode: Literal["mock", "live"] = "mock"
    research_max_feed_bytes: int = Field(default=2 * 1024**2, gt=0)
    research_items_per_source: int = Field(default=30, ge=1, le=200)
    #: Ideas the idea lab drafts per topic area and run.
    ideas_per_run: int = Field(default=12, ge=1, le=30)

    # --- Media library and own production (extension phase E7) ---
    #: Longer uploads keep only the original; the production cuts them later.
    library_max_rendition_s: float = Field(default=180.0, gt=0)
    library_max_image_bytes: int = Field(default=25 * 1024**2, gt=0)
    #: Sweep for library files whose rendition is still missing.
    library_sweep_seconds: int = Field(default=600, ge=60)
    #: Delete originals of uploaded videos after this many days; 0 keeps them forever.
    library_original_retention_days: int = Field(default=30, ge=0)
    production_max_segments: int = Field(default=12, ge=1, le=30)
    production_min_segment_s: float = Field(default=2.5, gt=0)
    production_max_s: float = Field(default=180.0, gt=0)

    # --- Comments (A3) ---
    #: Answer harmless comments (questions, praise) without asking. Criticism, sensitive
    #: topics and TikTok always go to the operator. Real replies need publishing_allowed.
    comment_auto_reply: bool = True
    #: Test comments under mock posts so the flow can be tried without live channels.
    comment_mock_samples: bool = True
    comments_seconds: int = Field(default=1800, ge=300)
    #: Competitor radar (A5): about 3 YouTube quota units per watched channel and run.
    competitor_seconds: int = Field(default=12 * 3600, ge=3600)
    #: A7: winner recycling and hook tests, once a day
    winner_seconds: int = Field(default=24 * 3600, ge=3600)
    #: A11 trend alarm: check every 30 min (YouTube trending list: 1 quota unit per call).
    trend_alarm_seconds: int = Field(default=30 * 60, ge=300)
    #: Alarm from this score (0-100) on.
    trend_alarm_threshold: int = Field(default=75, ge=1, le=100)
    #: At most this many alarms per day (so the phone stays quiet otherwise).
    trend_alarm_max_per_day: int = Field(default=3, ge=0, le=20)
    #: Video drafts (different angles) per alarm.
    trend_alarm_drafts: int = Field(default=3, ge=1, le=5)
    #: Ignore videos with fewer views.
    trend_alarm_min_views: int = Field(default=50_000, ge=0)
    #: Regions of the YouTube trending list (comma separated, ISO 3166-1 alpha-2).
    trend_alarm_regions: str = "DE,US"
    #: Master switch of the autopilot; each channel must also be switched on.
    trend_autopilot_enabled: bool = False
    #: The autopilot only acts from this score on.
    trend_autopilot_min_score: int = Field(default=85, ge=1, le=100)
    #: A6: copy approved clips to the other platforms of the topic area and language.
    crosspost_enabled: bool = True
    #: Push to the phone via ntfy (Ausbau A4). mock = recorded only, nothing leaves the server.
    push_mode: Literal["mock", "live"] = "mock"
    #: Full topic URL, e.g. https://ntfy.sh/<long-random-topic>; the topic name is the secret.
    push_ntfy_url: SecretStr = SecretStr("")
    #: Optional access token for a protected topic or an own ntfy server.
    push_ntfy_token: SecretStr = SecretStr("")
    #: Dashboard address; a tap on the push opens the matching page (e.g. https://studio.example.de).
    push_click_base_url: str = ""
    #: Lowest level that goes to the phone; everything else stays in the bell.
    push_min_level: Literal["info", "warning", "error", "critical"] = "warning"
    #: No push between these hours (local time), except critical; collected into one morning push.
    push_quiet_start: int = Field(default=22, ge=0, le=23)
    push_quiet_end: int = Field(default=7, ge=0, le=23)
    #: Watchdog for warnings (channels, copyright, reach drops) every 15 minutes.
    watchdog_seconds: int = Field(default=900, ge=60)
    #: Same warning at most once per this many hours.
    watchdog_repeat_hours: int = Field(default=24, ge=1, le=24 * 30)
    #: Chat attachments: at most this many per message.
    chat_max_attachments: int = Field(default=5, ge=1, le=10)
    comment_lookback_days: int = Field(default=14, ge=1, le=90)
    comment_posts_per_run: int = Field(default=20, ge=1, le=100)  # 1 YouTube unit each
    comment_drafts_per_run: int = Field(default=30, ge=1, le=200)
    #: YouTube charges 50 quota units per reply; keep the per-run amount modest.
    comment_replies_per_run: int = Field(default=10, ge=0, le=100)

    # --- Account overview (A2) ---
    #: Days after the first post before a channel is judged (decision 16.11.2026: 90).
    account_review_days: int = Field(default=90, ge=7, le=365)
    #: "Weak" = fewer views per post than this share of the topic area's median.
    account_weak_share: float = Field(default=0.25, gt=0, lt=1)
    #: Lower bound per post when a topic area has too few channels to compare with.
    account_min_views_per_post: int = Field(default=200, ge=0)

    # --- Channel assistant: forwarding addresses for new accounts (Cloudflare Email Routing) ---
    #: ``mock`` only proposes addresses; ``live`` creates routing rules at Cloudflare.
    mail_routing_mode: Literal["mock", "live"] = "mock"
    #: Domain of the addresses, e.g. ``kanalfabrik.de`` (must use Cloudflare Email Routing).
    mail_alias_domain: str = ""
    #: Verified destination address at Cloudflare that every alias forwards to.
    mail_forward_to: str = ""
    cloudflare_zone_id: str = ""
    #: API token with the permission "Zone > Email Routing Rules > Edit" for that zone only.
    cloudflare_api_token: SecretStr = SecretStr("")

    # --- Channel assistant: AI pictures (profile picture + banner) ---
    #: ``off`` draws the pictures locally (gradient + initials); ``cloudflare`` lets an
    #: image model on Cloudflare Workers AI paint them. The Workers Free plan has a
    #: daily free allowance and answers with an error when it is used up (no charge).
    image_ai_mode: Literal["off", "cloudflare"] = "off"
    cloudflare_ai_account_id: str = ""
    #: API token with "Workers AI - Read" and "Workers AI - Edit" (own token, not the mail one).
    cloudflare_ai_token: SecretStr = SecretStr("")
    image_ai_model: str = "@cf/black-forest-labs/flux-1-schnell"
    #: Diffusion steps (flux-1-schnell allows 1-8; more = finer details, more neurons).
    image_ai_steps: int = Field(default=8, ge=1, le=8)
    image_ai_timeout_s: float = Field(default=60.0, ge=5, le=300)

    # --- Bio-link pages, affiliate links, newsletter (A8) ---
    #: Public address of the bio-link pages, e.g. https://links.example.de (own tunnel host).
    public_links_base_url: str = ""
    #: Imprint and privacy page linked from every public page.
    legal_page_url: str = ""
    #: Unconfirmed newsletter sign-ups are deleted after this many days.
    newsletter_pending_days: int = Field(default=7, ge=1, le=30)
    #: Sign-ups per address and bio page within an hour (spam brake).
    newsletter_signups_per_hour: int = Field(default=20, ge=1, le=1000)

    # --- Outgoing e-mail (A8 newsletter confirmation, A10 weekly report) ---
    #: ``mock`` keeps every mail in the dashboard outbox; ``smtp`` really sends.
    mail_mode: Literal["mock", "smtp"] = "mock"
    mail_from: str = ""
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")

    # --- Weekly report (A10) ---
    report_enabled: bool = True
    #: Recipient of the weekly report; empty = only in the dashboard outbox.
    report_email: str = ""
    #: 0 = Monday … 6 = Sunday, local time (TZ).
    report_weekday: int = Field(default=0, ge=0, le=6)
    report_hour: int = Field(default=8, ge=0, le=23)

    @property
    def session_minutes(self) -> int:
        """Lifetime of a dashboard login.

        In private operation (one user, every request already checked by Cloudflare
        Access) the operator stays logged in: one year, extended on every use.
        Otherwise ``ACCESS_TOKEN_EXPIRE_MINUTES`` (default 30), also extended on use."""
        if self.single_user_mode and self.access_guard == "cloudflare":
            return PRIVATE_SESSION_MINUTES
        return self.access_token_expire_minutes

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

    @property
    def sample_data_enabled(self) -> bool:
        """Mock sources may invent sample data (never in production unless asked)."""
        if self.sample_data is not None:
            return self.sample_data
        return self.app_env != "production"

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
