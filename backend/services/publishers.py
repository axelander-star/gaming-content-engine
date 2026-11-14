"""Publishing adapters per platform (Phase 12/13).

``MockPublisher`` is used whenever publishing is not live: it checks the file and
returns a test id, nothing leaves the system. Live adapters use the official APIs:
YouTube (Phase 12), TikTok, Instagram and Facebook (Phase 13). Every adapter raises
the error classes of :mod:`services.platform`.
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
from services import meta, platform, quota, storage, tiktok, youtube


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
            raise platform.PlatformError("Datei wurde nach der Qualitätsprüfung verändert")
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


def _credential(session: Session, channel: Channel, provider: str, scope: str) -> ChannelCredential:
    cred = session.scalar(
        select(ChannelCredential).where(ChannelCredential.channel_id == channel.id)
    )
    if cred is None or cred.provider != provider:
        raise platform.AuthExpiredError(f"Kanal ist nicht verbunden ({provider})")
    if scope not in (cred.scopes or []):
        raise platform.AuthExpiredError("Veröffentlichungsrecht fehlt; bitte neu verbinden")
    return cred


def _verify_file(variant: Variant, path: Path) -> None:
    if variant.sha256 and storage.sha256_file(path) != variant.sha256:
        raise platform.PlatformError("Datei wurde nach der Qualitätsprüfung verändert")


def _synthetic_voice(session: Session, variant: Variant) -> bool:
    voice = session.scalar(select(Voiceover.id).where(Voiceover.variant_id == variant.id).limit(1))
    return voice is not None


def _caption(variant: Variant) -> str:
    parts = [variant.title or "", variant.description or ""]
    return "\n\n".join(p for p in parts if p).strip()


class TikTokPublisher:
    name = "tiktok"

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    def publish(
        self, session: Session, settings: Settings, channel: Channel, variant: Variant, path: Path
    ) -> PublishResult:
        cred = _credential(session, channel, tiktok.PROVIDER, tiktok.PUBLISH_SCOPE)
        _verify_file(variant, path)
        token = tiktok.access_token(session, settings, cred)
        session.commit()  # a rotated refresh token must survive a failed upload
        quota.consume(self.redis, f"tiktok_post_{channel.id}", 1, settings.tiktok_daily_post_limit)
        result = tiktok.post_video(
            token,
            path,
            _caption(variant),
            settings.tiktok_privacy_level,
            ai_generated=_synthetic_voice(session, variant),
            attempts=settings.publish_upload_attempts,
            polls=settings.publish_status_polls,
            interval=settings.publish_status_interval_seconds,
        )
        # Without a public post id (private posts, moderation pending) the publish id
        # identifies the post.
        return PublishResult(result.post_id or result.publish_id, result.url, result.privacy, False)


class InstagramPublisher:
    name = "instagram"

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    def publish(
        self, session: Session, settings: Settings, channel: Channel, variant: Variant, path: Path
    ) -> PublishResult:
        cred = _credential(
            session, channel, meta.PROVIDER, meta.PUBLISH_SCOPE[PlatformCode.INSTAGRAM]
        )
        _verify_file(variant, path)
        if not cred.external_account_id:
            raise platform.AuthExpiredError("Kein Instagram-Konto gespeichert")
        quota.consume(
            self.redis, f"instagram_post_{channel.id}", 1, settings.instagram_daily_post_limit
        )
        result = meta.publish_instagram(
            meta.page_token(settings, cred),
            cred.external_account_id,
            path,
            _caption(variant),
            attempts=settings.publish_upload_attempts,
            polls=settings.publish_status_polls,
            interval=settings.publish_status_interval_seconds,
        )
        return PublishResult(result.external_id, result.url, "public", False)


class FacebookPublisher:
    name = "facebook"

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    def publish(
        self, session: Session, settings: Settings, channel: Channel, variant: Variant, path: Path
    ) -> PublishResult:
        cred = _credential(
            session, channel, meta.PROVIDER, meta.PUBLISH_SCOPE[PlatformCode.FACEBOOK]
        )
        _verify_file(variant, path)
        if not cred.external_account_id:
            raise platform.AuthExpiredError("Keine Facebook-Seite gespeichert")
        quota.consume(
            self.redis, f"facebook_reels_{channel.id}", 1, settings.facebook_daily_reels_limit
        )
        result = meta.publish_facebook(
            meta.page_token(settings, cred),
            cred.external_account_id,
            path,
            description=_caption(variant),
            title=variant.title or "",
            attempts=settings.publish_upload_attempts,
            polls=settings.publish_status_polls,
            interval=settings.publish_status_interval_seconds,
        )
        return PublishResult(result.external_id, result.url, "public", False)


def live_publisher(platform_code: PlatformCode, redis: Redis) -> Publisher | None:
    """Live adapter of a platform, or ``None`` if there is none."""
    adapters: dict[
        PlatformCode,
        type[YouTubePublisher | TikTokPublisher | InstagramPublisher | FacebookPublisher],
    ] = {
        PlatformCode.YOUTUBE: YouTubePublisher,
        PlatformCode.TIKTOK: TikTokPublisher,
        PlatformCode.INSTAGRAM: InstagramPublisher,
        PlatformCode.FACEBOOK: FacebookPublisher,
    }
    adapter = adapters.get(platform_code)
    return adapter(redis) if adapter else None
