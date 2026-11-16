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


class ContentProjectStatus(StrEnum):
    """Lifecycle of a content project (topic area). Only ``active`` projects produce or publish."""

    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


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
    #: Clipping campaign of a rights holder (e.g. Content Rewards); license only for it.
    CAMPAIGN = "campaign"


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


class AICallStatus(StrEnum):
    """One call of the AI layer (extension phase E3)."""

    RESERVED = "reserved"  # cost reserved under the cap, call running
    SUCCEEDED = "succeeded"
    REFUSED = "refused"  # the model declined (stop_reason "refusal")
    FAILED = "failed"  # API or network error
    BLOCKED = "blocked"  # not sent: cap, budget, switch or missing key


class ChatActionStatus(StrEnum):
    """An action the chat assistant carried out (extension phase E4)."""

    DONE = "done"
    UNDONE = "undone"
    FAILED = "failed"


class IdeaStatus(StrEnum):
    """An idea in the idea lab (extension phase E5)."""

    NEW = "new"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class LibraryKind(StrEnum):
    """What a media library file is (extension phase E7)."""

    VIDEO = "video"
    IMAGE = "image"
    AUDIO = "audio"


class LibraryOrigin(StrEnum):
    UPLOAD = "upload"  # own recording or own file, rights confirmed on upload
    GENERATED = "generated"  # made by the own production (text, voice, own images)


class LibraryStatus(StrEnum):
    PROCESSING = "processing"  # stored, rendition and preview still to be made
    READY = "ready"
    FAILED = "failed"


class ProductionStatus(StrEnum):
    """An own production: script -> voice -> picture/text video -> subtitles (E7)."""

    DRAFT = "draft"
    QUEUED = "queued"
    RENDERING = "rendering"
    DONE = "done"
    FAILED = "failed"


class CampaignStatus(StrEnum):
    """A clipping campaign (e.g. Content Rewards) the operator takes part in."""

    ACTIVE = "active"
    PAUSED = "paused"  # no new clips, posts already made stay
    ENDED = "ended"  # budget used up or campaign over


class SubmissionStatus(StrEnum):
    """Link of a published campaign clip that the operator submits by hand."""

    OPEN = "open"  # still to submit
    SUBMITTED = "submitted"
    SKIPPED = "skipped"  # operator decided not to submit


class ChannelSetupStatus(StrEnum):
    """A prepared account the operator still has to create at the platform."""

    OPEN = "open"  # values ready, operator has not created the account yet
    DONE = "done"  # account created, channel added to the engine
    DISMISSED = "dismissed"  # operator does not want this channel


class MailAliasStatus(StrEnum):
    """Forwarding address for a new platform account (Cloudflare Email Routing)."""

    NOT_NEEDED = "not_needed"  # YouTube brand channels live under the business Google account
    MOCK = "mock"  # test mode: address only proposed, nothing created
    CREATED = "created"  # routing rule exists at Cloudflare
    FAILED = "failed"


class RevenueSource(StrEnum):
    """Where money of a channel comes from (account overview)."""

    YOUTUBE = "youtube"  # YouTube partner programme (ads, Shorts fund)
    CONTENT_REWARDS = "content_rewards"  # clipping campaigns
    AFFILIATE = "affiliate"  # partner links in bio/description
    SPONSOR = "sponsor"  # brand deals
    OTHER = "other"
