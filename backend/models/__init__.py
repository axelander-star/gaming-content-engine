"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from models.access import AuditLog, Notification, SystemSetting, User
from models.analytics import AnalyticsSnapshot, LearningVersion, Metric
from models.channels import Channel, ChannelCredential, Platform
from models.control import AgentDecision, AgentRun, AgentState, Cost
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

__all__ = [
    "AgentDecision",
    "AgentRun",
    "AgentState",
    "AnalyticsSnapshot",
    "Asset",
    "AuditLog",
    "Channel",
    "ChannelCredential",
    "Clip",
    "Cost",
    "Creator",
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
    "User",
    "Variant",
    "Voiceover",
]
