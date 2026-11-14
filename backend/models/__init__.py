"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from models.access import AuditLog, Notification, SystemSetting, User
from models.analytics import AnalyticsSnapshot, Metric
from models.channels import Channel, Platform
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
from models.publishing import Post, PublishingJob
from models.rights import Asset, Creator, License, Source
from models.trends import Game, Trend, TrendReport

__all__ = [
    "AgentDecision",
    "AgentRun",
    "AgentState",
    "AnalyticsSnapshot",
    "Asset",
    "AuditLog",
    "Channel",
    "Clip",
    "Cost",
    "Creator",
    "Game",
    "GameplayFile",
    "License",
    "Metric",
    "Notification",
    "Platform",
    "Post",
    "PublishingJob",
    "QualityCheck",
    "Scene",
    "Script",
    "Source",
    "Subtitle",
    "SystemSetting",
    "Trend",
    "TrendReport",
    "User",
    "Variant",
    "Voiceover",
]
