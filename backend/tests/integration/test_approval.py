"""Extension E8: approval center, library posts and the platform adapters.

No platform and no Cloudflare service is contacted: every HTTP call goes to an
``httpx.MockTransport``. Live publishing is only switched on inside single tests.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import crypto
from core.config import Settings, get_settings
from core.enums import (
    AgentRunStatus,
    ChannelAuthStatus,
    Language,
    LibraryKind,
    LibraryOrigin,
    LibraryStatus,
    PlatformCode,
    PublishingJobStatus,
    PublishingMode,
    UserRole,
    VideoStatus,
)
from models import Channel, ChannelCredential, User
from models.channels import Platform
from models.library import LibraryItem
from models.production import QualityCheck, Variant
from models.projects import ContentProject
from models.publishing import Post, PublishingJob
from services import (
    approval,
    gates,
    instagram,
    media,
    orchestrator,
    platform,
    publishers,
    r2,
    storage,
    tiktok,
    youtube,
)
from services.controls import update_runtime_controls
from services.projects import ProjectMismatchError
from services.seed import seed_base_data
from tests.conftest import login
from tests.integration.test_publishing import FakeGoogle

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed"),
]

MakeUser = Callable[..., User]
NOW = datetime(2026, 11, 16, 7, 0, tzinfo=UTC)  # Monday, 08:00 in Berlin


@pytest.fixture(scope="module")
def vertical(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("appr") / "vertical.mp4"
    return media.make_test_video(
        get_settings(), path, width=720, height=1280, calm_s=2, action_s=2, tail_s=1
    )


@pytest.fixture(scope="module")
def landscape(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("appr") / "landscape.mp4"
    return media.make_test_video(get_settings(), path, calm_s=2, action_s=2, tail_s=1)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(
        update={"media_root": str(tmp_path / "media"), "publish_status_interval_seconds": 0}
    )


@pytest.fixture
def food(db: Session) -> ContentProject:
    seed_base_data(db, demo_channels=True)
    project = ContentProject(slug="ernaehrung", name="Ernährung", languages=["de"], priority=200)
    db.add(project)
    db.flush()
    return project


def make_channel(db: Session, project: ContentProject, code: PlatformCode) -> Channel:
    plat = db.scalar(select(Platform).where(Platform.code == code))
    assert plat is not None
    plat.is_paused = False
    channel = Channel(
        platform_id=plat.id,
        content_project_id=project.id,
        language=Language.DE,
        name=f"{project.name} {plat.name}",
        auth_status=ChannelAuthStatus.NOT_CONNECTED,
        is_paused=False,
        min_posts_per_day=0,
        max_posts_per_day=3,
        min_interval_minutes=60,
    )
    db.add(channel)
    db.flush()
    return channel


@pytest.fixture
def channels(db: Session, food: ContentProject) -> dict[PlatformCode, Channel]:
    return {code: make_channel(db, food, code) for code in PlatformCode}


def make_item(
    db: Session,
    settings: Settings,
    project: ContentProject,
    src: Path,
    *,
    origin: LibraryOrigin = LibraryOrigin.UPLOAD,
    rights: dict[str, Any] | None = None,
) -> LibraryItem:
    stored = storage.store_path(settings, src, "library/originals", ".mp4", move=False)
    info = media.probe(settings, src)
    item = LibraryItem(
        content_project_id=project.id,
        kind=LibraryKind.VIDEO,
        origin=origin,
        status=LibraryStatus.READY,
        title="Haferflocken richtig lagern",
        filename=src.name,
        content_type="video/mp4",
        original_uri=stored.uri,
        original_sha256=stored.sha256,
        size_bytes=stored.size,
        duration_s=info.duration_s,
        width=info.width,
        height=info.height,
        orientation="portrait" if (info.height or 0) > (info.width or 0) else "landscape",
        rendition_uri=stored.uri if (info.height or 0) > (info.width or 0) else None,
        rights=rights
        if rights is not None
        else {"kind": "own_upload", "confirmed_by_user_id": 1, "statement": "x"},
        tags=["Ernährung", "Vorrat"],
        note="Drei Tipps, damit Haferflocken lange frisch bleiben.",
    )
    db.add(item)
    db.flush()
    return item


def prepare(
    db: Session, settings: Settings, item: LibraryItem, *chs: Channel, **kw: Any
) -> list[Variant]:
    return approval.prepare(db, settings, item.id, [c.id for c in chs], None, now=NOW, **kw)


# --- texts and options -----------------------------------------------------------------


def test_hashtags_are_cleaned_and_limited() -> None:
    assert approval.clean_hashtags("#Hafer, #hafer frühstück #ok!") == ["Hafer", "frühstück"]
    assert approval.clean_hashtags([f"t{i}" for i in range(40)], 30)[-1] == "t29"


def test_options_have_safe_defaults_and_publish_at_forces_private() -> None:
    yt = approval.clean_options(PlatformCode.YOUTUBE, None, NOW)
    assert yt["privacy"] == "private" and yt["format"] == "short" and yt["publish_at"] is None
    assert approval.clean_options(PlatformCode.TIKTOK, None, NOW) == {"mode": "inbox"}
    later = (NOW + timedelta(days=1)).isoformat()
    timed = approval.clean_options(
        PlatformCode.YOUTUBE, {"privacy": "public", "publish_at": later}, NOW
    )
    assert timed["privacy"] == "private" and timed["publish_at"].startswith("2026-11-17T07:00")
    for bad in (
        {"privacy": "everyone"},
        {"publish_at": "2026-11-17T08:00"},  # no time zone
        {"publish_at": NOW.isoformat()},  # not in the future
        {"category_id": "Food"},
        {"unknown": 1},
    ):
        with pytest.raises(approval.ApprovalError):
            approval.clean_options(PlatformCode.YOUTUBE, bad, NOW)
    with pytest.raises(approval.ApprovalError):
        approval.clean_options(PlatformCode.TIKTOK, {"mode": "public"}, NOW)


def test_youtube_resource_carries_options() -> None:
    body = youtube.video_resource(
        "T",
        "D",
        "de",
        "public",
        synthetic_voice=True,
        tags=["a"],
        category_id="26",
        made_for_kids=False,
        publish_at="2026-11-17T07:00:00+00:00",
    )
    assert body["snippet"]["categoryId"] == "26" and body["snippet"]["tags"] == ["a"]
    assert body["status"] == {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": True,
        "publishAt": "2026-11-17T07:00:00+00:00",
    }


# --- prepare, approve, withdraw ----------------------------------------------------------


def test_prepare_creates_one_checked_post_per_channel(
    db: Session,
    settings: Settings,
    food: ContentProject,
    channels: dict[PlatformCode, Channel],
    vertical: Path,
) -> None:
    item = make_item(db, settings, food, vertical)
    posts = prepare(
        db, settings, item, channels[PlatformCode.YOUTUBE], channels[PlatformCode.TIKTOK]
    )
    assert len(posts) == 2
    for v in posts:
        assert v.status == VideoStatus.QUALITY_APPROVED and v.clip_id is None
        assert v.library_item_id == item.id and v.content_project_id == food.id
        assert v.storage_uri == item.rendition_uri and v.sha256 == item.original_sha256
        assert v.title == item.title and "Ernährung" in v.hashtags
        qc = db.scalar(select(QualityCheck).where(QualityCheck.variant_id == v.id))
        assert qc is not None and qc.passed and qc.checks["source"] == "library"
        assert {c["name"] for c in qc.checks["items"]} == {
            "duration",
            "resolution",
            "vertical",
            "decode",
        }
    assert posts[1].publish_options == {"mode": "inbox"}
    # the same video cannot be prepared twice for one channel
    with pytest.raises(approval.ApprovalError) as err:
        prepare(db, settings, item, channels[PlatformCode.YOUTUBE])
    assert err.value.status_code == 409


def test_wrong_area_and_landscape_video_are_refused(
    db: Session,
    settings: Settings,
    food: ContentProject,
    channels: dict[PlatformCode, Channel],
    landscape: Path,
    vertical: Path,
) -> None:
    gaming = db.scalar(select(Channel).where(Channel.content_project_id != food.id))
    assert gaming is not None
    item = make_item(db, settings, food, vertical)
    with pytest.raises(approval.ApprovalError, match="anderen Themenbereich"):
        prepare(db, settings, item, gaming)
    # even a direct variant cannot cross topic areas
    with pytest.raises(ProjectMismatchError):
        db.add(
            Variant(
                library_item_id=item.id,
                channel_id=gaming.id,
                language=Language.DE,
                variant_label="A",
                status=VideoStatus.QUALITY_APPROVED,
            )
        )
        db.flush()
    db.rollback()


def test_landscape_needs_youtube_video_format(
    db: Session,
    settings: Settings,
    food: ContentProject,
    channels: dict[PlatformCode, Channel],
    landscape: Path,
) -> None:
    item = make_item(db, settings, food, landscape)
    with pytest.raises(approval.ApprovalError, match="Hochformat nötig"):
        prepare(db, settings, item, channels[PlatformCode.INSTAGRAM])
    texts = {channels[PlatformCode.YOUTUBE].id: {"title": "Quer", "options": {"format": "video"}}}
    (post,) = prepare(db, settings, item, channels[PlatformCode.YOUTUBE], texts=texts)
    assert post.publish_options["format"] == "video" and post.storage_uri == item.original_uri


def test_rights_are_required(
    db: Session,
    settings: Settings,
    food: ContentProject,
    channels: dict[PlatformCode, Channel],
    vertical: Path,
) -> None:
    item = make_item(db, settings, food, vertical, rights={"kind": "own_upload"})
    with pytest.raises(approval.ApprovalError, match="Rechtebestätigung"):
        prepare(db, settings, item, channels[PlatformCode.YOUTUBE])
    item.origin = LibraryOrigin.GENERATED
    item.rights = {"kind": "generated", "third_party_video": True}
    with pytest.raises(approval.ApprovalError, match="Fremdvideo"):
        prepare(db, settings, item, channels[PlatformCode.YOUTUBE])
    item.rights = {"kind": "generated", "third_party_video": False}
    assert len(prepare(db, settings, item, channels[PlatformCode.YOUTUBE])) == 1


def test_approve_withdraw_and_discard(
    db: Session,
    settings: Settings,
    food: ContentProject,
    channels: dict[PlatformCode, Channel],
    vertical: Path,
) -> None:
    item = make_item(db, settings, food, vertical)
    yt, ig = prepare(
        db, settings, item, channels[PlatformCode.YOUTUBE], channels[PlatformCode.INSTAGRAM]
    )
    approval.update(db, yt, title="  ", hashtags="#a #b")
    with pytest.raises(approval.ApprovalError, match="Titel fehlt"):
        approval.approve(db, yt, None)
    approval.update(db, yt, title="Haferflocken lagern", options={"privacy": "unlisted"})
    approval.approve(db, yt, None)
    assert yt.status == VideoStatus.READY_TO_PUBLISH and yt.hashtags == ["a", "b"]
    assert yt.publish_options["privacy"] == "unlisted"
    with pytest.raises(approval.ApprovalError):
        approval.update(db, yt, title="Neu")  # approved posts are locked
    approval.withdraw(db, yt, None)
    assert yt.status == VideoStatus.QUALITY_APPROVED
    approval.discard(db, ig, None)
    assert ig.status == VideoStatus.ARCHIVED
    # an archived library video blocks approval
    item.archived_at = datetime.now(UTC)
    with pytest.raises(approval.ApprovalError, match="archiviert"):
        approval.approve(db, yt, None)


def test_library_posts_skip_the_clip_pipeline(
    db: Session,
    settings: Settings,
    food: ContentProject,
    channels: dict[PlatformCode, Channel],
    vertical: Path,
) -> None:
    item = make_item(db, settings, food, vertical)
    (v,) = prepare(db, settings, item, channels[PlatformCode.YOUTUBE])
    v.status = VideoStatus.EDITING  # simulate a broken state
    db.flush()
    run = orchestrator.run_agent(
        db, settings, "creative_director", {"entity_type": "variants", "entity_id": v.id}
    )
    assert run.status == AgentRunStatus.SKIPPED and run.output["gate"] == "library_video"
    assert gates.source_key(v) == -item.id


# --- strategy and publishing --------------------------------------------------------------


def test_approved_post_is_planned_and_mock_published(
    db: Session,
    settings: Settings,
    food: ContentProject,
    channels: dict[PlatformCode, Channel],
    vertical: Path,
) -> None:
    channel = channels[PlatformCode.YOUTUBE]
    item = make_item(db, settings, food, vertical)
    (v,) = prepare(db, settings, item, channel)
    approval.approve(db, v, None)
    db.flush()
    run = orchestrator.run_agent(
        db,
        settings,
        "publishing_strategy",
        {"sweep": True, "channel_id": channel.id, "now": NOW.isoformat()},
    )
    assert run.status == AgentRunStatus.SUCCEEDED, run.output
    job = db.scalar(select(PublishingJob).where(PublishingJob.variant_id == v.id))
    assert job is not None and job.mode == PublishingMode.MOCK
    assert v.status == VideoStatus.SCHEDULED
    # withdrawing a planned post cancels the job
    approval.withdraw(db, v, None)
    assert job.status == PublishingJobStatus.CANCELLED and v.status == VideoStatus.QUALITY_APPROVED
    approval.approve(db, v, None)
    v.status = VideoStatus.SCHEDULED
    job2 = PublishingJob(
        variant_id=v.id,
        channel_id=channel.id,
        status=PublishingJobStatus.SCHEDULED,
        mode=PublishingMode.MOCK,
        scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
        idempotency_key=f"appr-{v.id}",
    )
    db.add(job2)
    db.flush()
    run = orchestrator.run_agent(
        db, settings, "publishing", {"entity_type": "variants", "entity_id": v.id}
    )
    assert run.status == AgentRunStatus.SUCCEEDED, run.output
    post = db.scalar(select(Post).where(Post.variant_id == v.id))
    assert post is not None and post.is_mock and v.status == VideoStatus.PUBLISHED


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeGoogle:
    f = FakeGoogle()
    monkeypatch.setattr(platform, "TRANSPORT", httpx.MockTransport(f))
    monkeypatch.setattr(youtube, "TRANSPORT", httpx.MockTransport(f))
    return f


@pytest.fixture
def live(
    settings: Settings, db: Session, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Settings]:
    import agents.publishing as agent_module

    monkeypatch.setattr(agent_module, "get_redis", lambda: redis_client)
    update_runtime_controls(db, None, auto_publish_enabled=True)
    yield settings.model_copy(
        update={
            "publishing_mode": "live",
            "auto_publish_enabled": True,
            "instagram_app_id": "ig-app",
            "instagram_app_secret": SecretStr("ig-secret"),
            "r2_account_id": "acc",
            "r2_bucket": "gce-out",
            "r2_access_key_id": SecretStr("AKID"),
            "r2_secret_access_key": SecretStr("SECRET"),
        }
    )


def ready_live_post(
    db: Session,
    settings: Settings,
    food: ContentProject,
    channel: Channel,
    src: Path,
    provider: str,
    scopes: list[str],
    options: dict[str, Any] | None = None,
) -> Variant:
    item = make_item(db, settings, food, src)
    texts = {
        channel.id: {
            "title": "Hafer",
            "description": "Tipps",
            "hashtags": ["hafer"],
            "options": options or {},
        }
    }
    (v,) = prepare(db, settings, item, channel, texts=texts)
    approval.approve(db, v, None)
    v.status = VideoStatus.SCHEDULED
    channel.auth_status = ChannelAuthStatus.AUTHORIZED
    db.add(
        ChannelCredential(
            channel_id=channel.id,
            provider=provider,
            access_token_enc=crypto.encrypt(settings, "tok"),
            expires_at=datetime.now(UTC) + timedelta(days=50),
            last_refreshed_at=datetime.now(UTC),
            scopes=scopes,
            external_account_id="1789",
        )
    )
    db.add(
        PublishingJob(
            variant_id=v.id,
            channel_id=channel.id,
            status=PublishingJobStatus.SCHEDULED,
            mode=PublishingMode.LIVE,
            scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
            idempotency_key=f"live-{v.id}",
        )
    )
    db.flush()
    return v


def run_publish(db: Session, settings: Settings, v: Variant) -> Any:
    return orchestrator.run_agent(
        db, settings, "publishing", {"entity_type": "variants", "entity_id": v.id}
    )


def test_youtube_live_upload_uses_post_options(
    db: Session,
    live: Settings,
    food: ContentProject,
    channels: dict[PlatformCode, Channel],
    vertical: Path,
    fake: FakeGoogle,
) -> None:
    session_url = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=e8"
    fake.on("POST", youtube.UPLOAD_URL, httpx.Response(200, headers={"Location": session_url}))
    fake.on(
        "PUT",
        session_url,
        httpx.Response(201, json={"id": "yt8", "status": {"privacyStatus": "unlisted"}}),
    )
    v = ready_live_post(
        db,
        live,
        food,
        channels[PlatformCode.YOUTUBE],
        vertical,
        "youtube",
        list(youtube.SCOPES),
        {"privacy": "unlisted", "format": "video", "category_id": "26"},
    )
    run = run_publish(db, live, v)
    assert run.status == AgentRunStatus.SUCCEEDED, run.output
    body = json.loads(fake.sent("POST", youtube.UPLOAD_URL)[0].content)
    assert body["status"]["privacyStatus"] == "unlisted"
    assert body["snippet"]["categoryId"] == "26" and body["snippet"]["tags"] == ["hafer"]
    assert body["snippet"]["description"].endswith("#hafer")
    post = db.scalar(select(Post).where(Post.variant_id == v.id))
    assert post is not None and post.url == "https://www.youtube.com/watch?v=yt8"


TT = tiktok.API


def tt_ok(data: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": data, "error": {"code": "ok", "message": ""}})


def test_tiktok_uploads_a_draft_to_the_inbox(
    monkeypatch: pytest.MonkeyPatch,
    db: Session,
    live: Settings,
    food: ContentProject,
    channels: dict[PlatformCode, Channel],
    vertical: Path,
    fake: FakeGoogle,
) -> None:
    upload_url = "https://open-upload.tiktokapis.com/video/?upload_id=e8"
    fake.on("POST", tiktok.INBOX_INIT_URL, tt_ok({"publish_id": "p8", "upload_url": upload_url}))
    fake.on("PUT", upload_url, httpx.Response(201))
    fake.on(
        "POST",
        tiktok.STATUS_URL,
        tt_ok({"status": "PROCESSING_UPLOAD"}),
        tt_ok({"status": "SEND_TO_USER_INBOX"}),
    )
    v = ready_live_post(
        db, live, food, channels[PlatformCode.TIKTOK], vertical, "tiktok", [tiktok.UPLOAD_SCOPE]
    )
    # the token refresh is covered by the Phase 13 tests
    monkeypatch.setattr(tiktok, "access_token", lambda *_a, **_k: "tok")
    run = run_publish(db, live, v)
    assert run.status == AgentRunStatus.SUCCEEDED, run.output
    assert run.output["privacy"] == "draft" and run.output["external_id"] == "p8"
    init = json.loads(fake.sent("POST", tiktok.INBOX_INIT_URL)[0].content)
    assert init["source_info"]["source"] == "FILE_UPLOAD" and "post_info" not in init
    assert not fake.sent("POST", tiktok.INIT_URL)  # no direct post


def test_instagram_login_publishes_via_short_lived_r2_address(
    db: Session,
    live: Settings,
    food: ContentProject,
    channels: dict[PlatformCode, Channel],
    vertical: Path,
    fake: FakeGoogle,
) -> None:
    g = instagram.GRAPH
    r2_prefix = "https://acc.r2.cloudflarestorage.com/gce-out/outgoing/"
    fake.on("PUT", r2_prefix, httpx.Response(200))
    fake.on("DELETE", r2_prefix, httpx.Response(204))
    fake.on(
        "GET",
        f"{g}/1789/content_publishing_limit",
        httpx.Response(200, json={"data": [{"quota_usage": 2, "config": {"quota_total": 100}}]}),
    )
    fake.on("POST", f"{g}/1789/media_publish", httpx.Response(200, json={"id": "m8"}))
    fake.on("POST", f"{g}/1789/media", httpx.Response(200, json={"id": "c8"}))
    fake.on(
        "GET",
        f"{g}/c8",
        httpx.Response(200, json={"status_code": "IN_PROGRESS"}),
        httpx.Response(200, json={"status_code": "FINISHED"}),
    )
    fake.on(
        "GET",
        f"{g}/m8",
        httpx.Response(200, json={"permalink": "https://www.instagram.com/reel/x/"}),
    )
    v = ready_live_post(
        db,
        live,
        food,
        channels[PlatformCode.INSTAGRAM],
        vertical,
        "instagram",
        list(instagram.SCOPES),
    )
    run = run_publish(db, live, v)
    assert run.status == AgentRunStatus.SUCCEEDED, run.output
    container = fake.sent("POST", f"{g}/1789/media")[0]
    params = parse_qs(urlparse(str(container.url)).query)
    assert params["media_type"] == ["REELS"] and params["share_to_feed"] == ["true"]
    video_url = params["video_url"][0]
    assert video_url.startswith(r2_prefix) and "X-Amz-Expires=900" in video_url
    assert params["caption"][0].endswith("#hafer")
    assert fake.sent("PUT", r2_prefix) and fake.sent("DELETE", r2_prefix)  # removed again
    post = db.scalar(select(Post).where(Post.variant_id == v.id))
    assert post is not None and post.external_post_id == "m8"


def test_instagram_login_without_r2_is_not_configured(
    db: Session,
    live: Settings,
    food: ContentProject,
    channels: dict[PlatformCode, Channel],
    vertical: Path,
    fake: FakeGoogle,
) -> None:
    no_r2 = live.model_copy(update={"r2_account_id": ""})
    v = ready_live_post(
        db,
        no_r2,
        food,
        channels[PlatformCode.INSTAGRAM],
        vertical,
        "instagram",
        list(instagram.SCOPES),
    )
    run = run_publish(db, no_r2, v)
    assert run.status == AgentRunStatus.FAILED and fake.requests == []
    assert "Cloudflare R2" in (run.error or "")


def test_instagram_login_connect_and_refresh(
    db: Session,
    live: Settings,
    food: ContentProject,
    channels: dict[PlatformCode, Channel],
    fake: FakeGoogle,
) -> None:
    channel = channels[PlatformCode.INSTAGRAM]
    assert platform.provider_for(PlatformCode.INSTAGRAM, live) == "instagram"
    url = urlparse(instagram.authorization_url(live, "st"))
    q = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == instagram.AUTH_URL
    assert q["scope"] == [",".join(instagram.SCOPES)] and q["response_type"] == ["code"]
    fake.on(
        "POST",
        instagram.TOKEN_URL,
        httpx.Response(
            200,
            json={
                "data": [
                    {
                        "access_token": "short",
                        "user_id": "1789",
                        "permissions": ",".join(instagram.SCOPES),
                    }
                ]
            },
        ),
    )
    fake.on(
        "GET",
        f"{instagram.GRAPH_ROOT}/access_token",
        httpx.Response(200, json={"access_token": "long", "expires_in": 5_184_000}),
    )
    fake.on(
        "GET",
        f"{instagram.GRAPH}/me",
        httpx.Response(200, json={"user_id": "1789", "username": "hafer_de"}),
    )
    cred = instagram.connect(db, live, channel, "code#_", 1)
    assert cred.provider == "instagram" and cred.external_account_name == "@hafer_de"
    assert crypto.decrypt(live, cred.access_token_enc or "") == "long"
    assert "long" not in (cred.access_token_enc or "")
    sent = fake.sent("POST", instagram.TOKEN_URL)[0].content.decode()
    assert "code=code&" in sent + "&" or sent.endswith("code=code")
    # renewal when less than a week is left
    fake.on(
        "GET",
        f"{instagram.GRAPH_ROOT}/refresh_access_token",
        httpx.Response(200, json={"access_token": "renewed", "expires_in": 5_184_000}),
    )
    later = datetime.now(UTC) + timedelta(days=55)
    assert instagram.access_token(db, live, cred, now=later) == "renewed"
    assert cred.expires_at is not None and cred.expires_at > later + timedelta(days=59)
    with pytest.raises(platform.AuthExpiredError):
        instagram.access_token(db, live, cred, now=later + timedelta(days=61))


def test_r2_presign_matches_the_aws_example() -> None:
    url = r2.presign_url(
        "GET",
        "examplebucket.s3.amazonaws.com",
        "/test.txt",
        access_key="AKIA" + "IOSFODNN7EXAMPLE",  # AWS documentation example key
        secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        seconds=86400,
        now=datetime(2013, 5, 24, tzinfo=UTC),
        region="us-east-1",
    )
    # Signature from the AWS Signature Version 4 documentation (presigned URL example).
    assert url.endswith("aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404")


def test_caption_contains_hashtags() -> None:
    v = Variant(title="T", description="D", hashtags=["a", "b"])
    assert publishers._caption(v) == approval.caption(v) == "T\n\nD\n\n#a #b"


# --- API ------------------------------------------------------------------------------------


@pytest.fixture
def client(api: TestClient, settings: Settings) -> Iterator[TestClient]:
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    yield api


def test_api_flow(
    client: TestClient,
    make_user: MakeUser,
    db: Session,
    settings: Settings,
    food: ContentProject,
    channels: dict[PlatformCode, Channel],
    vertical: Path,
) -> None:
    make_user("op@example.com", UserRole.OPERATOR)
    make_user("viewer@example.com", UserRole.VIEWER)
    item = make_item(db, settings, food, vertical)
    yt, tt = channels[PlatformCode.YOUTUBE], channels[PlatformCode.TIKTOK]
    viewer = login(client, "viewer@example.com")
    info = client.get("/api/approval/info").json()
    assert "keine offizielle Schnittstelle" in info["twitch_note"]
    assert {p["code"] for p in info["platforms"]} == {c.value for c in PlatformCode}
    r = client.post(
        "/api/approval/prepare", json={"item_id": item.id, "channel_ids": [yt.id]}, headers=viewer
    )
    assert r.status_code == 403

    op = login(client, "op@example.com")
    s = client.post(
        "/api/approval/suggest", json={"item_id": item.id, "channel_id": yt.id}, headers=op
    )
    assert s.status_code == 200 and s.json()["title"] == item.title, s.text
    body = {
        "item_id": item.id,
        "channel_ids": [yt.id, tt.id],
        "texts": {
            str(yt.id): {
                "title": "Hafer",
                "hashtags": ["#hafer"],
                "options": {"privacy": "unlisted"},
            }
        },
    }
    r = client.post("/api/approval/prepare", json=body, headers=op)
    assert r.status_code == 201, r.text
    posts = {p["platform"]: p for p in r.json()}
    assert posts["youtube"]["status"] == "QUALITY_APPROVED"
    assert posts["youtube"]["options"]["privacy"] == "unlisted"
    assert posts["youtube"]["caption"] == "Hafer\n\n#hafer" and posts["youtube"]["checks"]
    assert posts["tiktok"]["options"] == {"mode": "inbox"}
    pid = posts["youtube"]["id"]
    r = client.patch(f"/api/approval/{pid}", json={"description": "Drei Tipps"}, headers=op)
    assert r.status_code == 200 and r.json()["caption"] == "Hafer\n\nDrei Tipps\n\n#hafer"
    r = client.patch(f"/api/approval/{pid}", json={"options": {"privacy": "x"}}, headers=op)
    assert r.status_code == 422
    r = client.post(f"/api/approval/{pid}/approve", headers=op)
    assert r.status_code == 200 and r.json()["status"] == "READY_TO_PUBLISH"
    listed = client.get("/api/approval", params={"project_id": food.id}).json()
    assert {p["id"] for p in listed} == {p["id"] for p in posts.values()}
    ready = client.get("/api/approval", params={"status": "READY_TO_PUBLISH"}).json()
    assert [p["id"] for p in ready] == [pid]
    r = client.post(f"/api/approval/{pid}/withdraw", headers=op)
    assert r.status_code == 200 and r.json()["status"] == "QUALITY_APPROVED"
    r = client.post(f"/api/approval/{posts['tiktok']['id']}/discard", headers=op)
    assert r.json()["status"] == "ARCHIVED"
    assert client.post("/api/approval/999999/approve", headers=op).status_code == 404
    dup = client.post(
        "/api/approval/prepare", json={"item_id": item.id, "channel_ids": [yt.id]}, headers=op
    )
    assert dup.status_code == 409


# --- security (extension E9) -------------------------------------------------------------


def test_ai_texts_cannot_smuggle_actions_or_overlong_fields() -> None:
    hostile = (
        'Klar! {"title": "' + "X" * 400 + '", "description": "ok", '
        '"hashtags": ["gut", "#böse tag", "<script>"], "channel_ids": [1, 2], '
        '"approve": true, "options": {"privacy": "public"}}'
    )
    texts = approval.parse_texts(hostile, approval.RULES[PlatformCode.YOUTUBE])
    assert set(texts) == {"title", "description", "hashtags"}
    assert len(texts["title"]) == 100 and texts["hashtags"] == ["gut"]
    assert approval.parse_texts("kein JSON", approval.RULES[PlatformCode.TIKTOK]) == {
        "title": "",
        "description": "",
        "hashtags": [],
    }


def test_tokens_never_leave_the_server(
    client: TestClient,
    make_user: MakeUser,
    db: Session,
    settings: Settings,
    channels: dict[PlatformCode, Channel],
) -> None:
    secret = "IGQ-very-secret-token-123"
    channel = channels[PlatformCode.INSTAGRAM]
    enc = crypto.encrypt(settings, secret)
    db.add(
        ChannelCredential(
            channel_id=channel.id,
            provider="instagram",
            access_token_enc=enc,
            scopes=list(instagram.SCOPES),
            external_account_id="1789",
            external_account_name="@hafer_de",
        )
    )
    db.flush()
    make_user("admin@example.com", UserRole.ADMIN)
    login(client, "admin@example.com")
    for path in ("/api/channels", "/api/approval/info", "/api/approval", "/api/overview/dashboard"):
        body = client.get(path).text
        assert secret not in body and enc not in body, path
    listed = next(c for c in client.get("/api/channels").json() if c["id"] == channel.id)
    assert listed["connected_account"] == "@hafer_de"
