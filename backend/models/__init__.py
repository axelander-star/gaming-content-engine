"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from models.access import AuditLog, Notification, SystemSetting, User
from models.ai import AICall
from models.analytics import AnalyticsSnapshot, LearningVersion, Metric
from models.assistant import ChatAction, ChatMessage
from models.channels import Channel, ChannelCredential, Platform
from models.control import AgentDecision, AgentRun, AgentState, Cost
from models.planning import ContentFocus, EditorialDay
from models.production import (
    Clip,
    GameplayFile,
    QualityCheck,
    Scene,
    Script,
    Subtitle,
    Variant,
    Voiceover,
)
from models.projects import ContentProject
from models.publishing import Post, PublishingJob, StrategyVersion
from models.rights import (
    Asset,
    Creator,
    License,
    LicenseDocument,
    PublisherPolicy,
    RightsCheck,
    Source,
)
from models.trends import Game, Trend, TrendReport
from models.uploads import UploadSession

__all__ = [
    "AICall",
    "AgentDecision",
    "AgentRun",
    "AgentState",
    "AnalyticsSnapshot",
    "Asset",
    "AuditLog",
    "Channel",
    "ChannelCredential",
    "ChatAction",
    "ChatMessage",
    "Clip",
    "ContentFocus",
    "ContentProject",
    "Cost",
    "Creator",
    "EditorialDay",
    "Game",
    "GameplayFile",
    "LearningVersion",
    "License",
    "LicenseDocument",
    "Metric",
    "Notification",
    "Platform",
    "Post",
    "PublisherPolicy",
    "PublishingJob",
    "QualityCheck",
    "RightsCheck",
    "Scene",
    "Script",
    "Source",
    "StrategyVersion",
    "Subtitle",
    "SystemSetting",
    "Trend",
    "TrendReport",
    "UploadSession",
    "User",
    "Variant",
    "Voiceover",
]

# Fills and checks the content project of new content on every flush.
import services.projects  # noqa: F401  (registers the session listener)
