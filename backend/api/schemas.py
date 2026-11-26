"""Response schemas shared by several routers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from core.enums import ChannelAuthStatus, Language, PlatformCode, UserRole


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str | None
    role: UserRole
    is_active: bool
    last_login_at: datetime | None


class ChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    language: Language
    platform: PlatformCode
    #: Topic area of the channel; content of other projects never goes here.
    content_project_id: int
    content_project: str
    auth_status: ChannelAuthStatus
    is_paused: bool
    min_posts_per_day: int
    max_posts_per_day: int
    min_interval_minutes: int
    #: Name of the connected platform account (Phase 12); tokens are never returned.
    connected_account: str | None = None
    #: Last transfer of the prepared profile (description, keywords, banner) to YouTube.
    profile_sync: dict[str, Any] | None = None
