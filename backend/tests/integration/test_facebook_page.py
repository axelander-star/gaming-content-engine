"""Agent 27: the Facebook Page behind an Instagram channel runs as its own channel.

Meta is never contacted: every HTTP call goes to an ``httpx.MockTransport``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import crypto
from core.config import Settings, get_settings
from core.enums import (
    ChannelAuthStatus,
    ChannelSetupStatus,
    Language,
    PlatformCode,
    UserRole,
    VideoStatus,
)
from models import Channel, ChannelCredential, User
from models.access import Notification
from models.channel_setup import ChannelSetupTask
from models.production import Variant
from services import branding, facebook_page, meta, platform
from tests.conftest import login
from tests.factories import build_chain
from tests.integration.test_publishing import FakeGoogle

pytestmark = pytest.mark.integration

G = meta.GRAPH
PAGE_ID = "P1"


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeGoogle:
    f = FakeGoogle()
    monkeypatch.setattr(platform, "TRANSPORT", httpx.MockTransport(f))
    return f


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(update={"media_root": str(tmp_path / "media")})


def instagram(
    db: Session, settings: Settings, scopes: list[str] | None = None, task: bool = True
) -> tuple[Channel, Variant]:
    """A Meta-connected Instagram channel (from the channel assistant) with one video."""
    chain = build_chain(db)
    ig = db.scalar(
        select(Channel).where(
            Channel.platform.has(code=PlatformCode.INSTAGRAM),
            Channel.language == chain.variant.language,
        )
    )
    assert ig is not None
    ig.auth_status, ig.is_paused = ChannelAuthStatus.AUTHORIZED, False
    ig.min_posts_per_day, ig.max_posts_per_day, ig.min_interval_minutes = 1, 3, 120
    db.add(
        ChannelCredential(
            channel_id=ig.id,
            provider=meta.PROVIDER,
            access_token_enc=crypto.encrypt(settings, "page-token"),
            scopes=list(meta.INSTAGRAM_SCOPES) if scopes is None else scopes,
            external_account_id="1784",
            external_account_name="@schockfakten",
            last_refreshed_at=datetime.now(UTC) - timedelta(minutes=5),
        )
    )
    if task:
        row = ChannelSetupTask(
            content_project_id=ig.content_project_id,
            platform="instagram",
            language=Language.DE,
            status=ChannelSetupStatus.DONE,
            display_name="Schockfakten",
            handle="schockfakten",
            bio="Krasse Fakten, die du garantiert noch nicht kanntest – jeden Tag neu, "
            "kurz erklärt und mit Quelle. Folge für mehr!",
            text_source="template",
            avatar_uri=branding.store_png(settings, branding.avatar_png("Schockfakten", "x")),
            channel_id=ig.id,
        )
        db.add(row)
        db.flush()
        ig.strategy = {"setup_task_id": row.id}
    variant = chain.variant
    variant.channel_id = ig.id
    variant.status = VideoStatus.READY_TO_PUBLISH
    variant.title = "Wusstest du das?"
    variant.description = "Ein krasser Fakt über Oktopusse."
    variant.storage_uri = "mock://final.mp4"
    variant.sha256 = "ab" * 32
    db.flush()
    return ig, variant


def page_found(fake: FakeGoogle) -> None:
    fake.on("GET", f"{G}/me?", httpx.Response(200, json={"id": PAGE_ID, "name": "Schockfakten"}))


def test_instagram_page_becomes_a_channel_with_the_same_bounds(
    db: Session, settings: Settings, fake: FakeGoogle
) -> None:
    ig, _ = instagram(db, settings)
    page_found(fake)

    fb = facebook_page.link_from_instagram(db, settings, ig)

    assert fb.platform.code == PlatformCode.FACEBOOK
    assert fb.content_project_id == ig.content_project_id and fb.language == ig.language
    assert fb.external_channel_id == PAGE_ID
    assert fb.auth_status == ChannelAuthStatus.AUTHORIZED
    assert (fb.min_posts_per_day, fb.max_posts_per_day, fb.min_interval_minutes) == (1, 3, 120)
    assert fb.is_paused is False
    assert fb.strategy["mirror_of"] == ig.id and fb.strategy["missing_permissions"] == []
    assert ig.strategy["facebook_page_channel_id"] == fb.id
    cred = db.scalar(select(ChannelCredential).where(ChannelCredential.channel_id == fb.id))
    assert cred is not None and crypto.decrypt(settings, cred.access_token_enc or "") == (
        "page-token"
    )
    assert cred.external_account_name == "Schockfakten"
    # the Page was looked up with the Instagram channel's Page token
    sent = fake.sent("GET", f"{G}/me?")[0]
    assert sent.url.params["access_token"] == "page-token"

    again = facebook_page.link_from_instagram(db, settings, ig)
    assert again.id == fb.id  # the same Page never becomes a second channel


def test_missing_permissions_keep_the_page_restricted(
    db: Session, settings: Settings, fake: FakeGoogle
) -> None:
    ig, _ = instagram(db, settings, scopes=["instagram_basic", "instagram_content_publish"])
    page_found(fake)

    fb = facebook_page.link_from_instagram(db, settings, ig)

    assert fb.auth_status == ChannelAuthStatus.CONNECTED_RESTRICTED
    assert fb.strategy["missing_permissions"] == list(facebook_page.NEEDED.values())
    problems = facebook_page.check(db, settings, fb, datetime.now(UTC))
    assert any("Rechte" in p for p in problems)
    key = f"fb_permissions:{fb.id}"
    note = db.scalar(select(Notification).where(Notification.dedup_key == key))
    assert note is not None and "Meta-Login-Konfiguration" in (note.body or "")


def test_instagram_login_without_page_is_not_taken_over(db: Session, settings: Settings) -> None:
    ig, _ = instagram(db, settings)
    cred = db.scalar(select(ChannelCredential).where(ChannelCredential.channel_id == ig.id))
    assert cred is not None
    cred.provider = "instagram"
    with pytest.raises(facebook_page.PageError):
        facebook_page.link_from_instagram(db, settings, ig)


def _profile_routes(fake: FakeGoogle, cover: httpx.Response | None = None) -> None:
    fake.on(
        "POST",
        f"{G}/{PAGE_ID}/photos",
        httpx.Response(200, json={"id": "photo-avatar"}),
        httpx.Response(200, json={"id": "photo-cover"}),
    )
    fake.on("POST", f"{G}/{PAGE_ID}/picture", httpx.Response(200, json={"success": True}))
    fake.on(
        "POST",
        f"{G}/{PAGE_ID}?",
        httpx.Response(200, json={"success": True}),
        cover or httpx.Response(200, json={"success": True}),
    )


def test_profile_gets_description_picture_and_cover(
    db: Session, settings: Settings, fake: FakeGoogle
) -> None:
    ig, _ = instagram(db, settings)
    page_found(fake)
    fb = facebook_page.link_from_instagram(db, settings, ig)
    _profile_routes(fake)

    result = facebook_page.sync_profile(db, settings, fb)

    assert result.ok, result.error
    assert result.applied == ["Beschreibung", "Profilbild", "Titelbild"]
    page_posts = fake.sent("POST", f"{G}/{PAGE_ID}?")
    about = page_posts[0].url.params["about"]
    assert len(about) <= facebook_page.ABOUT_MAX and about.startswith("Krasse Fakten")
    assert page_posts[1].url.params["cover"] == "photo-cover"
    photos = fake.sent("POST", f"{G}/{PAGE_ID}/photos")
    assert all(p.url.params["published"] == "false" for p in photos)  # never in the feed
    assert b'name="source"' in photos[0].content and b"\x89PNG" in photos[1].content
    picture = fake.sent("POST", f"{G}/{PAGE_ID}/picture")[0]
    assert picture.url.params["photo"] == "photo-avatar"
    assert fb.strategy["profile_sync"]["ok"] is True
    assert not facebook_page.sync_due(fb, datetime.now(UTC) + timedelta(days=3))


def test_a_refused_cover_is_reported_and_retried_later(
    db: Session, settings: Settings, fake: FakeGoogle
) -> None:
    ig, _ = instagram(db, settings)
    page_found(fake)
    fb = facebook_page.link_from_instagram(db, settings, ig)
    _profile_routes(
        fake,
        cover=httpx.Response(
            403, json={"error": {"message": "Requires business_management", "code": 200}}
        ),
    )

    result = facebook_page.sync_profile(db, settings, fb)

    assert not result.ok
    assert result.applied == ["Beschreibung", "Profilbild"] and result.manual == ["Titelbild"]
    assert result.error and "business_management" in result.error
    now = datetime.now(UTC)
    assert not facebook_page.sync_due(fb, now + timedelta(hours=1))
    assert facebook_page.sync_due(fb, now + timedelta(hours=25))


def test_an_existing_page_is_never_overwritten(
    db: Session, settings: Settings, fake: FakeGoogle
) -> None:
    ig, _ = instagram(db, settings, task=False)
    page_found(fake)
    fb = facebook_page.link_from_instagram(db, settings, ig)

    result = facebook_page.sync_profile(db, settings, fb)

    assert not result.ok and "Kanal-Assistenten" in (result.error or "")
    assert fake.sent("POST", G) == []


def test_instagram_videos_are_mirrored_once(
    db: Session, settings: Settings, fake: FakeGoogle
) -> None:
    ig, variant = instagram(db, settings)
    page_found(fake)
    fb = facebook_page.link_from_instagram(db, settings, ig)

    first = facebook_page.mirror(db, settings)
    second = facebook_page.mirror(db, settings)

    assert len(first["copies"]) == 1 and second["copies"] == []
    copy = db.get(Variant, first["copies"][0]["copy_id"])
    assert copy is not None and copy.channel_id == fb.id
    assert copy.status == VideoStatus.READY_TO_PUBLISH  # the strategy agent decides when
    assert copy.storage_uri == variant.storage_uri and copy.sha256 == variant.sha256
    assert copy.concept["facebook_mirror_of"] == variant.id

    fb.is_paused = True
    variant2 = Variant(
        clip_id=variant.clip_id,
        channel_id=ig.id,
        content_project_id=ig.content_project_id,
        language=ig.language,
        variant_label="B",
        status=VideoStatus.READY_TO_PUBLISH,
        title="Noch ein Fakt",
    )
    db.add(variant2)
    db.flush()
    assert facebook_page.mirror(db, settings)["copies"] == []  # a paused Page gets nothing


def test_agent_round_links_fills_mirrors_and_notices_an_expired_token(
    db: Session, settings: Settings, fake: FakeGoogle
) -> None:
    ig, _ = instagram(db, settings)
    page_found(fake)
    _profile_routes(fake)

    res = facebook_page.run(db, settings)

    fb = facebook_page.page_channel_of(db, ig)
    assert fb is not None and res.linked == [fb.id] and res.synced == [fb.id]
    assert res.copies == 1
    assert fb.strategy["profile_sync"]["ok"] is True

    # a second round right away changes nothing
    again = facebook_page.run(db, settings)
    assert again.linked == [] and again.synced == [] and again.copies == 0

    # six hours later the token check finds an expired token
    fake.routes.clear()
    fake.on(
        "GET",
        f"{G}/me?",
        httpx.Response(400, json={"error": {"message": "Session expired", "code": 190}}),
    )
    facebook_page.check(db, settings, fb, datetime.now(UTC) + timedelta(hours=7))
    assert fb.auth_status == ChannelAuthStatus.EXPIRED


def test_profile_sync_endpoint_for_facebook(
    db: Session,
    settings: Settings,
    fake: FakeGoogle,
    api: TestClient,
    make_user: Callable[..., User],
) -> None:
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    ig, _ = instagram(db, settings)
    page_found(fake)
    fb = facebook_page.link_from_instagram(db, settings, ig)
    make_user("admin@example.com", UserRole.ADMIN)
    db.commit()
    h = login(api, "admin@example.com")
    _profile_routes(fake)

    res = api.post(f"/api/channels/{fb.id}/profile-sync", headers=h)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["profile_sync"]["ok"] is True and body["mirror_of"] == ig.id
    assert body["missing_permissions"] == []


def test_cover_carries_the_instagram_name_and_follows_changes(
    db: Session, settings: Settings, fake: FakeGoogle
) -> None:
    """Regression 28.11.2026: the cover showed the YouTube banner with another name."""
    ig, _ = instagram(db, settings)
    youtube_banner = branding.store_png(settings, branding.banner_png("DailySchock", "x", "y"))
    db.add(
        ChannelSetupTask(
            content_project_id=ig.content_project_id,
            platform="youtube",
            language=Language.DE,
            status=ChannelSetupStatus.DONE,
            display_name="DailySchock",
            handle="dailyschock",
            bio="YouTube",
            text_source="template",
            banner_uri=youtube_banner,
        )
    )
    page_found(fake)
    fb = facebook_page.link_from_instagram(db, settings, ig)
    _profile_routes(fake)

    res = facebook_page.run(db, settings)

    task = db.get(ChannelSetupTask, ig.strategy["setup_task_id"])
    assert task is not None and task.banner_uri and task.banner_uri != youtube_banner
    assert res.synced == [fb.id] and fb.strategy["profile_sync"]["ok"] is True
    assert facebook_page.run(db, settings).synced == []

    # a new bio in the channel assistant goes to the Page by itself
    task.bio = "Neue Beschreibung"
    _profile_routes(fake)
    assert facebook_page.run(db, settings).synced == [fb.id]
    assert fake.sent("POST", f"{G}/{PAGE_ID}?")[-2].url.params["about"] == "Neue Beschreibung"
