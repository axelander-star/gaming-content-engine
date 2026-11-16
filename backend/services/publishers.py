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
from services import instagram, meta, platform, quota, r2, storage, tiktok, youtube


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
        opts = variant.publish_options or {}
        tags = list(variant.hashtags or [])
        description = variant.description or ""
        if tags:
            description = f"{description}\n\n{' '.join('#' + t for t in tags)}".strip()
        resource = youtube.video_resource(
            title=variant.title or "",
            description=description,
            language=variant.language.value,
            privacy=str(opts.get("privacy") or settings.youtube_upload_privacy),
            synthetic_voice=voice is not None,
            tags=tags,
            category_id=str(opts.get("category_id") or youtube.GAMING_CATEGORY),
            made_for_kids=bool(opts.get("made_for_kids", False)),
            publish_at=opts.get("publish_at"),
        )
        quota.consume(self.redis, "youtube_upload", 1, settings.youtube_daily_upload_limit)
        result = youtube.upload(token, path, resource, attempts=settings.publish_upload_attempts)
        url = result.url
        if opts.get("format") == "video":
            url = f"https://www.youtube.com/watch?v={result.video_id}"
        return PublishResult(result.video_id, url, result.privacy, False)


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
    # A copy for another platform (A6) has the voice of its original.
    origin = (variant.concept or {}).get("crosspost_of")
    vid = origin if isinstance(origin, int) and not isinstance(origin, bool) else variant.id
    voice = session.scalar(select(Voiceover.id).where(Voiceover.variant_id == vid).limit(1))
    return voice is not None


def _caption(variant: Variant) -> str:
    """Title, description and hashtags (hashtags since extension E8)."""
    tags = " ".join(f"#{t}" for t in (variant.hashtags or []))
    parts = [variant.title or "", variant.description or "", tags]
    return "\n\n".join(p for p in parts if p).strip()


class TikTokPublisher:
    name = "tiktok"

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    def publish(
        self, session: Session, settings: Settings, channel: Channel, variant: Variant, path: Path
    ) -> PublishResult:
        mode = str((variant.publish_options or {}).get("mode") or settings.tiktok_post_mode)
        scope = tiktok.UPLOAD_SCOPE if mode == "inbox" else tiktok.PUBLISH_SCOPE
        cred = _credential(session, channel, tiktok.PROVIDER, scope)
        _verify_file(variant, path)
        token = tiktok.access_token(session, settings, cred)
        session.commit()  # a rotated refresh token must survive a failed upload
        quota.consume(self.redis, f"tiktok_post_{channel.id}", 1, settings.tiktok_daily_post_limit)
        if mode == "inbox":
            draft = tiktok.upload_draft(
                token,
                path,
                attempts=settings.publish_upload_attempts,
                polls=settings.publish_status_polls,
                interval=settings.publish_status_interval_seconds,
            )
            # A draft has no public post yet: the creator finishes it in the TikTok app.
            return PublishResult(draft.publish_id, None, "draft", False)
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
        stored = session.scalar(
            select(ChannelCredential).where(ChannelCredential.channel_id == channel.id)
        )
        if stored is not None and stored.provider == instagram.PROVIDER:
            return self._instagram_login(session, settings, channel, variant, path)
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

    def _instagram_login(
        self, session: Session, settings: Settings, channel: Channel, variant: Variant, path: Path
    ) -> PublishResult:
        """Instagram Login (no Facebook Page): Meta fetches the video from a short-lived
        presigned R2 address, which is removed again afterwards."""
        cred = _credential(session, channel, instagram.PROVIDER, instagram.PUBLISH_SCOPE)
        _verify_file(variant, path)
        if not cred.external_account_id:
            raise platform.AuthExpiredError("Kein Instagram-Konto gespeichert")
        if not r2.configured(settings):
            raise platform.NotConfiguredError(
                "Instagram-Login braucht Cloudflare R2 für eine kurzlebige Video-Adresse"
            )
        token = instagram.access_token(session, settings, cred)
        session.commit()  # a renewed token must survive a failed upload
        quota.consume(
            self.redis, f"instagram_post_{channel.id}", 1, settings.instagram_daily_post_limit
        )
        key = f"outgoing/{variant.sha256 or variant.id}-{uuid.uuid4().hex[:8]}.mp4"
        url = r2.public_video_url(settings, key, path)
        try:
            result = instagram.publish_reel(
                token,
                cred.external_account_id,
                url,
                _caption(variant),
                share_to_feed=bool((variant.publish_options or {}).get("share_to_feed", True)),
                polls=settings.publish_status_polls,
                interval=settings.publish_status_interval_seconds,
            )
        finally:
            r2.delete(settings, key)
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
