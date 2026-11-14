"""Idempotent base data: platforms, the eight DE/EN channels and known publisher policies.

Channels are created *not connected*, *paused* and with ``max_posts_per_day=0``
so nothing can be published until the operator configures them.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import ChannelAuthStatus, Language, PlatformCode, PolicyStatus
from models.channels import Channel, Platform
from models.rights import PublisherPolicy
from models.trends import Game

#: Policies required by the specification itself (section 5). Everything else is
#: researched and entered by the operator; nothing is assumed to be permissive.
KNOWN_POLICIES = (
    {
        "name": "Grand Theft Auto VI",
        "slug": "grand-theft-auto-vi",
        "publisher": "Rockstar Games / Take-Two Interactive",
        "status": PolicyStatus.LICENSE_REQUIRED,
        "notes": (
            "Keine pauschale kommerzielle Freigabe (PROJECT_SPEC Abschnitt 5). Nutzung nur mit "
            "ausdrücklicher, dokumentierter Erlaubnis des Rechteinhabers."
        ),
    },
)

PLATFORM_NAMES: dict[PlatformCode, str] = {
    PlatformCode.YOUTUBE: "YouTube Shorts",
    PlatformCode.TIKTOK: "TikTok",
    PlatformCode.INSTAGRAM: "Instagram Reels",
    PlatformCode.FACEBOOK: "Facebook Reels",
}


def seed_base_data(session: Session) -> dict[str, int]:
    """Create missing platforms and channels. Returns counts of created rows."""
    created = {"platforms": 0, "channels": 0, "policies": 0}
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
    for known in KNOWN_POLICIES:
        game = session.scalar(select(Game).where(Game.slug == known["slug"]))
        if game is None:
            game = Game(name=known["name"], slug=known["slug"], publisher=known["publisher"])
            session.add(game)
            session.flush()
        if session.scalar(select(PublisherPolicy.id).where(PublisherPolicy.game_id == game.id)):
            continue
        session.add(
            PublisherPolicy(
                game_id=game.id,
                status=known["status"],
                publisher=known["publisher"],
                notes=known["notes"],
            )
        )
        game.publisher_policy_notes = str(known["notes"])
        created["policies"] += 1
    session.flush()
    return created
