"""Publishing adapters per platform (Phase 12/13).

``MockPublisher`` is used whenever publishing is not live: it checks the file and
returns a test id, nothing leaves the system. Live adapters exist only for
platforms whose official API integration is built (Phase 12: YouTube). A platform
without a live adapter is "not available"; its videos wait.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import PlatformCode
from models.channels import Channel, ChannelCredential
from models.production import Variant, Voiceover
from services import quota, storage, youtube


@dataclass(frozen=True)
class PublishResult:
    external_id: str
    url: str | None
    privacy: str
    is_mock: bool


class Publisher(Protocol):
    name: str

    def publish(
        self, session: Session, settings: Settings, channel: Channel, variant: Variant, path: Path
    ) -> PublishResult: ...


class MockPublisher:
    name = "mock"

    def publish(
        self, session: Session, settings: Settings, channel: Channel, variant: Variant, path: Path
    ) -> PublishResult:
        if variant.sha256 and storage.sha256_file(path) != variant.sha256:
            raise youtube.YouTubeError("Datei wurde nach der Qualitätsprüfung verändert")
        return PublishResult(f"mock-{variant.id}-{uuid.uuid4().hex[:8]}", None, "mock", True)


class YouTubePublisher:
    name = "youtube"

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    def publish(
        self, session: Session, settings: Settings, channel: Channel, variant: Variant, path: Path
    ) -> PublishResult:
        cred = session.scalar(
            select(ChannelCredential).where(ChannelCredential.channel_id == channel.id)
        )
        if cred is None:
            raise youtube.AuthExpiredError("Kanal ist nicht mit YouTube verbunden")
        if youtube.UPLOAD_SCOPE not in (cred.scopes or []):
            raise youtube.AuthExpiredError("Upload-Berechtigung fehlt; bitte neu verbinden")
        if variant.sha256 and storage.sha256_file(path) != variant.sha256:
            raise youtube.YouTubeError("Datei wurde nach der Qualitätsprüfung verändert")
        token = youtube.access_token(session, settings, cred)
        voice = session.scalar(
            select(Voiceover.id).where(Voiceover.variant_id == variant.id).limit(1)
        )
        resource = youtube.video_resource(
            title=variant.title or "",
            description=variant.description or "",
            language=variant.language.value,
            privacy=settings.youtube_upload_privacy,
            synthetic_voice=voice is not None,
        )
        quota.consume(self.redis, "youtube_upload", 1, settings.youtube_daily_upload_limit)
        result = youtube.upload(token, path, resource, attempts=settings.publish_upload_attempts)
        return PublishResult(result.video_id, result.url, result.privacy, False)


def live_publisher(platform: PlatformCode, redis: Redis) -> Publisher | None:
    """Live adapter of a platform, or ``None`` while it is not built yet."""
    if platform == PlatformCode.YOUTUBE:
        return YouTubePublisher(redis)
    return None
