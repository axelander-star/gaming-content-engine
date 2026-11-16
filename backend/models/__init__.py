"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from models.access import AuditLog, Notification, SystemSetting, User
from models.ai import AICall
from models.analytics import AnalyticsSnapshot, LearningVersion, Metric
from models.assistant import ChatAction, ChatMessage
from models.campaigns import Campaign, CampaignSubmission
from models.channel_setup import ChannelSetupTask
from models.channels import Channel, ChannelCredential, Platform
from models.comments import Comment
from models.control import AgentDecision, AgentRun, AgentState, Cost
from models.library import LibraryItem, OwnProduction
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
from models.research import Idea, ResearchItem, ResearchSource
from models.revenue import RevenueEntry
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
    "Campaign",
    "CampaignSubmission",
    "Channel",
    "ChannelCredential",
    "ChannelSetupTask",
    "ChatAction",
    "ChatMessage",
    "Clip",
    "Comment",
    "ContentFocus",
    "ContentProject",
    "Cost",
    "Creator",
    "EditorialDay",
    "Game",
    "GameplayFile",
    "Idea",
    "LearningVersion",
    "LibraryItem",
    "License",
    "LicenseDocument",
    "Metric",
    "Notification",
    "OwnProduction",
    "Platform",
    "Post",
    "PublisherPolicy",
    "PublishingJob",
    "QualityCheck",
    "ResearchItem",
    "ResearchSource",
    "RevenueEntry",
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
