"""Domain enumerations shared by models, services and the API."""

from __future__ import annotations

from enum import StrEnum


class Language(StrEnum):
    DE = "de"
    EN = "en"


class PlatformCode(StrEnum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"


class ChannelAuthStatus(StrEnum):
    """Whether a channel may actually publish (PROJECT_SPEC section 11)."""

    NOT_CONNECTED = "not_connected"
    CONNECTED_RESTRICTED = "connected_restricted"
    AUTHORIZED = "authorized"
    EXPIRED = "expired"


class UserRole(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class UploadStatus(StrEnum):
    """Resumable upload session (services/uploads.py)."""

    UPLOADING = "UPLOADING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MaterialStatus(StrEnum):
    """Lifecycle of gameplay material (see docs/ARCHITECTURE.md section 4)."""

    DISCOVERED = "DISCOVERED"
    RIGHTS_PENDING = "RIGHTS_PENDING"
    RIGHTS_APPROVED = "RIGHTS_APPROVED"
    RIGHTS_REJECTED = "RIGHTS_REJECTED"
    ANALYZED = "ANALYZED"
    FAILED = "FAILED"


class VideoStatus(StrEnum):
    """Lifecycle of a video variant (see docs/ARCHITECTURE.md section 4)."""

    SCENE_SELECTED = "SCENE_SELECTED"
    EDITING = "EDITING"
    LOCALIZATION = "LOCALIZATION"
    VOICEOVER = "VOICEOVER"
    SUBTITLES = "SUBTITLES"
    QUALITY_CHECK = "QUALITY_CHECK"
    QUALITY_APPROVED = "QUALITY_APPROVED"
    QUALITY_REJECTED = "QUALITY_REJECTED"
    READY_TO_PUBLISH = "READY_TO_PUBLISH"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    ANALYTICS_PENDING = "ANALYTICS_PENDING"
    ANALYZED = "ANALYZED"
    ARCHIVED = "ARCHIVED"
    FAILED = "FAILED"


class SourceType(StrEnum):
    OWN_UPLOAD = "own_upload"
    LICENSED_CREATOR = "licensed_creator"
    PARTNER = "partner"
    CONTRACT = "contract"
    OTHER_LICENSED = "other_licensed"


class LicenseStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"


class PolicyStatus(StrEnum):
    """Commercial-use policy of a game publisher (curated by the operator)."""

    PERMITTED = "permitted"  # publisher allows commercial short-form use of licensed footage
    LICENSE_REQUIRED = "license_required"  # only with explicit permission of the rights holder
    FORBIDDEN = "forbidden"


class AssetKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    MUSIC = "music"
    IMAGE = "image"


class PublishingJobStatus(StrEnum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class PublishingMode(StrEnum):
    MOCK = "mock"
    LIVE = "live"


class MetricWindow(StrEnum):
    """Measurement windows from PROJECT_SPEC section 3."""

    H1 = "1h"
    H6 = "6h"
    H24 = "24h"
    H48 = "48h"
    D7 = "7d"
    OTHER = "other"


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class CostCategory(StrEnum):
    SERVER = "server"
    STORAGE = "storage"
    BACKUP = "backup"
    DOMAIN = "domain"
    AI = "ai"
    TTS = "tts"
    API = "api"
    OTHER = "other"


class NotificationLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
