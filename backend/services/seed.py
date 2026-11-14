"""Idempotent base data: the four platforms and the eight DE/EN channels.

Channels are created *not connected*, *paused* and with ``max_posts_per_day=0``
so nothing can be published until the operator configures them.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import ChannelAuthStatus, Language, PlatformCode
from models.channels import Channel, Platform

PLATFORM_NAMES: dict[PlatformCode, str] = {
    PlatformCode.YOUTUBE: "YouTube Shorts",
    PlatformCode.TIKTOK: "TikTok",
    PlatformCode.INSTAGRAM: "Instagram Reels",
    PlatformCode.FACEBOOK: "Facebook Reels",
}


def seed_base_data(session: Session) -> dict[str, int]:
    """Create missing platforms and channels. Returns counts of created rows."""
    created = {"platforms": 0, "channels": 0}
    for code, name in PLATFORM_NAMES.items():
        platform = session.scalar(select(Platform).where(Platform.code == code))
        if platform is None:
            platform = Platform(code=code, name=name)
            session.add(platform)
            session.flush()
            created["platforms"] += 1
        for lang in Language:
            channel_name = f"{name} {lang.value.upper()}"
            exists = session.scalar(
                select(Channel.id).where(
                    Channel.platform_id == platform.id, Channel.language == lang
                )
            )
            if exists is None:
                session.add(
                    Channel(
                        platform_id=platform.id,
                        language=lang,
                        name=channel_name,
                        auth_status=ChannelAuthStatus.NOT_CONNECTED,
                        is_paused=True,
                        min_posts_per_day=0,
                        max_posts_per_day=0,
                    )
                )
                created["channels"] += 1
    session.flush()
    return created
