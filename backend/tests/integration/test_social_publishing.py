"""Phase 13: TikTok, Instagram and Facebook connection and publishing.

No platform is contacted: every HTTP call goes to an ``httpx.MockTransport``.
"""

# ruff: noqa: F811 - pytest fixtures imported from test_publishing

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import crypto
from core.config import Settings, get_settings
from core.enums import (
    AgentRunStatus,
    ChannelAuthStatus,
    PlatformCode,
    PublishingJobStatus,
    PublishingMode,
    UserRole,
    VideoStatus,
)
from models import Channel, ChannelCredential, User
from models.access import Notification
from models.publishing import Post
from services import meta, platform, tiktok
from tests.conftest import login
from tests.factories import build_chain
from tests.integration.test_publishing import (
    FakeGoogle,
    live,  # noqa: F401 - fixture
    publish,
    scheduled,
)

UPLOAD = "https://open-upload.tiktokapis.com/video/?upload_id=1"
G = meta.GRAPH


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeGoogle:
    f = FakeGoogle()
    monkeypatch.setattr(platform, "TRANSPORT", httpx.MockTransport(f))
    return f


@pytest.fixture
def base_settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(update={"media_root": str(tmp_path / "media")})


@pytest.fixture
def settings(base_settings: Settings) -> Settings:
    return base_settings.model_copy(
        update={
            "tiktok_client_key": "tt-key",
            "tiktok_client_secret": SecretStr("tt-secret"),
            "tiktok_oauth_redirect_uri": "https://gce.example/api/oauth/tiktok/callback",
            "meta_app_id": "meta-app",
            "meta_app_secret": SecretStr("meta-secret"),
            "meta_oauth_redirect_uri": "https://gce.example/api/oauth/meta/callback",
            "publish_status_interval_seconds": 0,
            # Phase 13 covers Direct Post and Instagram via a Facebook Page; the E8 paths
            # (TikTok drafts, Instagram Login) are tested in test_approval.
            "tiktok_post_mode": "direct",
            "instagram_login": "facebook",
        }
    )


@pytest.fixture
def video(tmp_path: Path) -> Path:
    p = tmp_path / "v.mp4"
    p.write_bytes(b"x" * 1000)
    return p


def ok(data: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": data, "error": {"code": "ok", "message": ""}})


def tt_error(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"data": {}, "error": {"code": code, "message": code}})


CREATOR = {
    "creator_username": "gce_test",
    "privacy_level_options": ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"],
    "comment_disabled": False,
    "duet_disabled": True,
    "stitch_disabled": False,
    "max_video_post_duration_sec": 600,
}


# --- shared -------------------------------------------------------------------------


def test_state_is_bound_to_its_provider(settings: Settings) -> None:
    state = platform.make_state(settings, "tiktok", 4, 2)
    assert platform.read_state(settings, "tiktok", state) == (4, 2)
    with pytest.raises(platform.PlatformError):
        platform.read_state(settings, "meta", state)
    assert platform.provider_for(PlatformCode.INSTAGRAM) == "meta"
    assert platform.provider_for(PlatformCode.FACEBOOK) == "meta"


def test_not_configured(base_settings: Settings) -> None:
    with pytest.raises(platform.NotConfiguredError):
        tiktok.authorization_url(base_settings, "s")
    with pytest.raises(platform.NotConfiguredError):
        meta.authorization_url(base_settings, "s", PlatformCode.FACEBOOK)


# --- TikTok -------------------------------------------------------------------------


def test_tiktok_authorization_url(settings: Settings) -> None:
    url = urlparse(tiktok.authorization_url(settings, "st"))
    q = parse_qs(url.query)
    assert url.netloc == "www.tiktok.com" and url.path == "/v2/auth/authorize/"
    assert q["client_key"] == ["tt-key"] and q["scope"] == ["video.publish,video.upload,video.list"]
    assert q["response_type"] == ["code"] and q["state"] == ["st"]


def test_tiktok_chunk_plan() -> None:
    assert tiktok.chunk_plan(4_194_304) == (4_194_304, 1)
    assert tiktok.chunk_plan(50_000_123) == (50_000_123, 1)
    size = 150_000_123
    assert tiktok.chunk_plan(size) == (10_000_000, 15)
    ranges = tiktok.chunk_ranges(size)
    assert ranges[0] == (0, 9_999_999) and ranges[-1] == (140_000_000, size - 1)
    assert sum(b - a + 1 for a, b in ranges) == size


def test_tiktok_refresh_keeps_the_rotated_token(
    db: Session, settings: Settings, fake: FakeGoogle
) -> None:
    chain = build_chain(db)
    cred = ChannelCredential(
        channel_id=chain.channel.id,
        provider="tiktok",
        access_token_enc=crypto.encrypt(settings, "old"),
        refresh_token_enc=crypto.encrypt(settings, "rt-1"),
        expires_at=datetime.now(UTC),
        scopes=["video.publish"],
    )
    fake.on(
        "POST",
        tiktok.TOKEN_URL,
        httpx.Response(
            200,
            json={
                "access_token": "act-2",
                "refresh_token": "rt-2",
                "expires_in": 86400,
                "refresh_expires_in": 31536000,
                "scope": "video.publish",
                "open_id": "o1",
            },
        ),
    )
    assert tiktok.access_token(db, settings, cred) == "act-2"
    assert crypto.decrypt(settings, cred.refresh_token_enc or "") == "rt-2"
    sent = parse_qs(fake.sent("POST", tiktok.TOKEN_URL)[0].content.decode())
    assert sent["grant_type"] == ["refresh_token"] and sent["refresh_token"] == ["rt-1"]
    cred.expires_at = datetime.now(UTC)
    fake.routes.clear()
    fake.on("POST", tiktok.TOKEN_URL, httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(platform.AuthExpiredError):
        tiktok.access_token(db, settings, cred)


def test_tiktok_direct_post(fake: FakeGoogle, video: Path) -> None:
    fake.on("POST", tiktok.CREATOR_INFO_URL, ok(CREATOR))
    fake.on("POST", tiktok.INIT_URL, ok({"publish_id": "v_pub_1", "upload_url": UPLOAD}))
    fake.on("PUT", UPLOAD, httpx.Response(500), httpx.Response(201))
    fake.on(
        "POST",
        tiktok.STATUS_URL,
        ok({"status": "PROCESSING_UPLOAD"}),
        ok({"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": []}),
    )
    result = tiktok.post_video(
        "act", video, "Titel", "SELF_ONLY", True, polls=3, interval=0, sleep=lambda s: None
    )
    assert result.publish_id == "v_pub_1" and result.status == "PUBLISH_COMPLETE"
    assert result.post_id is None and result.url is None  # private posts get no public id
    init = json.loads(fake.sent("POST", tiktok.INIT_URL)[0].content)
    assert init["post_info"]["privacy_level"] == "SELF_ONLY"
    assert init["post_info"]["is_aigc"] is True and init["post_info"]["disable_duet"] is True
    assert init["source_info"] == {
        "source": "FILE_UPLOAD",
        "video_size": 1000,
        "chunk_size": 1000,
        "total_chunk_count": 1,
    }
    put = fake.sent("PUT", UPLOAD)[-1]
    assert put.headers["Content-Range"] == "bytes 0-999/1000" and len(fake.sent("PUT", UPLOAD)) == 2


def test_tiktok_public_post_gets_a_link(fake: FakeGoogle, video: Path) -> None:
    fake.on("POST", tiktok.CREATOR_INFO_URL, ok(CREATOR))
    fake.on("POST", tiktok.INIT_URL, ok({"publish_id": "p2", "upload_url": UPLOAD}))
    fake.on("PUT", UPLOAD, httpx.Response(201))
    fake.on(
        "POST",
        tiktok.STATUS_URL,
        ok({"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [7300000000001]}),
    )
    r = tiktok.post_video("act", video, "T", "PUBLIC_TO_EVERYONE", False, sleep=lambda s: None)
    assert r.url == "https://www.tiktok.com/@gce_test/video/7300000000001"


def test_tiktok_errors(fake: FakeGoogle, video: Path) -> None:
    def post() -> tiktok.PostResult:
        return tiktok.post_video("act", video, "T", "SELF_ONLY", False, sleep=lambda s: None)

    fake.on(
        "POST",
        tiktok.CREATOR_INFO_URL,
        ok({**CREATOR, "privacy_level_options": ["PUBLIC_TO_EVERYONE"]}),
    )
    with pytest.raises(platform.RestrictedError, match="SELF_ONLY"):
        post()
    fake.routes.clear()
    fake.on("POST", tiktok.CREATOR_INFO_URL, tt_error(200, "spam_risk_too_many_posts"))
    with pytest.raises(platform.TransientError):  # reported with HTTP 200
        post()
    fake.routes.clear()
    fake.on("POST", tiktok.CREATOR_INFO_URL, tt_error(401, "access_token_invalid"))
    with pytest.raises(platform.AuthExpiredError):
        post()
    fake.routes.clear()
    fake.on("POST", tiktok.CREATOR_INFO_URL, ok(CREATOR))
    fake.on(
        "POST", tiktok.INIT_URL, tt_error(403, "unaudited_client_can_only_post_to_private_accounts")
    )
    with pytest.raises(platform.RestrictedError):
        post()
    fake.routes.clear()
    fake.on("POST", tiktok.CREATOR_INFO_URL, ok(CREATOR))
    fake.on("POST", tiktok.INIT_URL, ok({"publish_id": "p", "upload_url": UPLOAD}))
    fake.on("PUT", UPLOAD, httpx.Response(201))
    fake.on("POST", tiktok.STATUS_URL, ok({"status": "FAILED", "fail_reason": "file_format"}))
    with pytest.raises(platform.PlatformError, match="file_format") as err:
        post()
    assert not isinstance(err.value, platform.TransientError)


# --- Meta ---------------------------------------------------------------------------


def test_meta_authorization_url_asks_per_platform(settings: Settings) -> None:
    ig = parse_qs(urlparse(meta.authorization_url(settings, "s", PlatformCode.INSTAGRAM)).query)
    fb = urlparse(meta.authorization_url(settings, "s", PlatformCode.FACEBOOK))
    assert fb.netloc == "www.facebook.com" and fb.path == "/v25.0/dialog/oauth"
    assert "instagram_content_publish" in ig["scope"][0]
    assert parse_qs(fb.query)["scope"] == [
        "pages_show_list,pages_read_engagement,pages_manage_posts,read_insights,"
        "pages_manage_engagement,pages_manage_metadata,business_management"
    ]


PAGE = {
    "id": "111",
    "name": "GCE Seite",
    "access_token": "page-token",
    "tasks": ["CREATE_CONTENT", "MODERATE"],
    "instagram_business_account": {"id": "1784", "username": "gce_ig"},
}


def test_pick_target_needs_exactly_one_fitting_page() -> None:
    assert meta.pick_target([PAGE], PlatformCode.FACEBOOK).account_id == "111"
    ig = meta.pick_target([PAGE], PlatformCode.INSTAGRAM)
    assert ig.account_id == "1784" and ig.name == "@gce_ig" and ig.page_token == "page-token"
    with pytest.raises(platform.PlatformError, match="Mehrere"):
        meta.pick_target([PAGE, {**PAGE, "id": "222"}], PlatformCode.FACEBOOK)
    with pytest.raises(platform.PlatformError, match="Keine"):
        meta.pick_target([{**PAGE, "tasks": ["ANALYZE"]}], PlatformCode.FACEBOOK)
    no_ig = {k: v for k, v in PAGE.items() if k != "instagram_business_account"}
    with pytest.raises(platform.PlatformError, match="Instagram"):
        meta.pick_target([no_ig], PlatformCode.INSTAGRAM)


def test_instagram_reel(fake: FakeGoogle, video: Path) -> None:
    uri = "https://rupload.facebook.com/ig-api-upload/v25.0/C1"
    fake.on(
        "GET",
        f"{G}/1784/content_publishing_limit",
        httpx.Response(
            200,
            json={
                "data": [{"quota_usage": 2, "config": {"quota_total": 50, "quota_duration": 86400}}]
            },
        ),
    )
    fake.on("POST", f"{G}/1784/media?", httpx.Response(200, json={"id": "C1", "uri": uri}))
    fake.on("POST", uri, httpx.Response(200, json={"success": True}))
    fake.on(
        "GET",
        f"{G}/C1",
        httpx.Response(200, json={"status_code": "IN_PROGRESS"}),
        httpx.Response(200, json={"status_code": "FINISHED"}),
    )
    fake.on("POST", f"{G}/1784/media_publish", httpx.Response(200, json={"id": "M9"}))
    fake.on(
        "GET",
        f"{G}/M9",
        httpx.Response(200, json={"permalink": "https://www.instagram.com/reel/abc/"}),
    )
    r = meta.publish_instagram(
        "page-token", "1784", video, "Titel", interval=0, sleep=lambda s: None
    )
    assert r.external_id == "M9" and r.url == "https://www.instagram.com/reel/abc/"
    create = parse_qs(urlparse(str(fake.sent("POST", f"{G}/1784/media?")[0].url)).query)
    assert create["media_type"] == ["REELS"] and create["upload_type"] == ["resumable"]
    up = fake.sent("POST", uri)[0]
    assert up.headers["Authorization"] == "OAuth page-token" and up.headers["file_size"] == "1000"
    assert parse_qs(urlparse(str(fake.sent("POST", f"{G}/1784/media_publish")[0].url)).query)[
        "creation_id"
    ] == ["C1"]


def test_instagram_limits_and_errors(fake: FakeGoogle, video: Path) -> None:
    fake.on(
        "GET",
        f"{G}/1784/content_publishing_limit",
        httpx.Response(200, json={"data": [{"quota_usage": 50, "config": {"quota_total": 50}}]}),
    )
    with pytest.raises(platform.TransientError, match="50"):
        meta.publish_instagram("t", "1784", video, "c", sleep=lambda s: None)
    fake.routes.clear()
    fake.on(
        "GET",
        f"{G}/1784/content_publishing_limit",
        httpx.Response(400, json={"error": {"message": "Session expired", "code": 190}}),
    )
    with pytest.raises(platform.AuthExpiredError):
        meta.publish_instagram("t", "1784", video, "c", sleep=lambda s: None)
    fake.routes.clear()
    fake.on("GET", f"{G}/1784/content_publishing_limit", httpx.Response(200, json={"data": []}))
    fake.on(
        "POST",
        f"{G}/1784/media?",
        httpx.Response(
            200, json={"id": "C2", "uri": "https://rupload.facebook.com/ig-api-upload/v25.0/C2"}
        ),
    )
    fake.on("POST", "https://rupload.facebook.com/", httpx.Response(200, json={"success": True}))
    fake.on("GET", f"{G}/C2", httpx.Response(200, json={"status_code": "ERROR"}))
    with pytest.raises(platform.PlatformError, match="ERROR"):
        meta.publish_instagram("t", "1784", video, "c", interval=0, sleep=lambda s: None)
    assert fake.sent("POST", f"{G}/1784/media_publish") == []


def test_facebook_reel_resumes_after_an_upload_error(fake: FakeGoogle, video: Path) -> None:
    rup = "https://rupload.facebook.com/video-upload/v25.0/V7"
    fake.on(
        "POST",
        f"{G}/111/video_reels",
        httpx.Response(
            200,
            json={"video_id": "V7", "upload_url": "https://rupload.facebook.com/video-upload/V7"},
        ),
        httpx.Response(200, json={"success": True}),
    )
    fake.on("POST", rup, httpx.Response(503), httpx.Response(200, json={"success": True}))
    fake.on(
        "GET",
        f"{G}/V7",
        httpx.Response(
            200,
            json={
                "status": {"uploading_phase": {"status": "in_progress", "bytes_transfered": 400}}
            },
        ),
        httpx.Response(
            200,
            json={
                "status": {
                    "video_status": "ready",
                    "processing_phase": {"status": "complete"},
                    "publishing_phase": {"status": "complete"},
                }
            },
        ),
    )
    r = meta.publish_facebook(
        "page-token", "111", video, "Beschreibung", "Titel", interval=0, sleep=lambda s: None
    )
    assert r.external_id == "V7" and r.status == "complete"
    uploads = fake.sent("POST", rup)
    assert [u.headers["offset"] for u in uploads] == ["0", "400"] and len(uploads[1].content) == 600
    start, finish = fake.sent("POST", f"{G}/111/video_reels")
    assert parse_qs(urlparse(str(start.url)).query)["upload_phase"] == ["start"]
    q = parse_qs(urlparse(str(finish.url)).query)
    assert q["upload_phase"] == ["finish"] and q["video_state"] == ["PUBLISHED"]
    assert q["video_id"] == ["V7"] and q["description"] == ["Beschreibung"]


def test_facebook_rejected_video(fake: FakeGoogle, video: Path) -> None:
    fake.on(
        "POST",
        f"{G}/111/video_reels",
        httpx.Response(200, json={"video_id": "V8"}),
        httpx.Response(200, json={"success": True}),
    )
    fake.on("POST", "https://rupload.facebook.com/", httpx.Response(200, json={"success": True}))
    fake.on(
        "GET",
        f"{G}/V8",
        httpx.Response(
            200,
            json={
                "status": {
                    "processing_phase": {
                        "status": "error",
                        "error": {"message": "Duration must be 3-90s"},
                    }
                }
            },
        ),
    )
    with pytest.raises(platform.PlatformError, match="3-90"):
        meta.publish_facebook("t", "111", video, "d", "t", interval=0, sleep=lambda s: None)


# --- Publishing Agent with the new adapters ------------------------------------------


def authorize(
    db: Session,
    settings: Settings,
    channel_id: int,
    provider: str,
    scopes: list[str],
    account: str = "1784",
) -> Channel:
    channel = db.get(Channel, channel_id)
    assert channel is not None
    channel.auth_status, channel.is_paused = ChannelAuthStatus.AUTHORIZED, False
    channel.platform.is_paused = False
    db.add(
        ChannelCredential(
            channel_id=channel.id,
            provider=provider,
            access_token_enc=crypto.encrypt(settings, "tok"),
            refresh_token_enc=crypto.encrypt(settings, "rt") if provider == "tiktok" else None,
            expires_at=datetime.now(UTC) + timedelta(hours=5) if provider == "tiktok" else None,
            scopes=scopes,
            external_account_id=account,
        )
    )
    db.flush()
    return channel


@pytest.fixture
def live_settings(live: Settings, settings: Settings) -> Settings:
    return settings.model_copy(update={"publishing_mode": "live", "auto_publish_enabled": True})


def test_agent_posts_privately_to_tiktok(
    db: Session, live_settings: Settings, fake: FakeGoogle
) -> None:
    v, job = scheduled(db, live_settings, PublishingMode.LIVE, PlatformCode.TIKTOK)
    authorize(db, live_settings, v.channel_id, "tiktok", ["video.publish"])
    fake.on("POST", tiktok.CREATOR_INFO_URL, ok(CREATOR))
    fake.on("POST", tiktok.INIT_URL, ok({"publish_id": "v_pub_9", "upload_url": UPLOAD}))
    fake.on("PUT", UPLOAD, httpx.Response(201))
    fake.on("POST", tiktok.STATUS_URL, ok({"status": "PUBLISH_COMPLETE"}))
    run = publish(db, live_settings, v)
    assert run.status == AgentRunStatus.SUCCEEDED, run.error
    post = db.scalar(select(Post).where(Post.variant_id == v.id))
    assert post is not None and post.external_post_id == "v_pub_9" and not post.is_mock
    assert run.output["privacy"] == "SELF_ONLY" and v.status == VideoStatus.PUBLISHED
    assert job.status == PublishingJobStatus.SUCCEEDED


def test_agent_marks_unaudited_tiktok_as_restricted(
    db: Session, live_settings: Settings, fake: FakeGoogle
) -> None:
    v, job = scheduled(db, live_settings, PublishingMode.LIVE, PlatformCode.TIKTOK)
    channel = authorize(db, live_settings, v.channel_id, "tiktok", ["video.publish"])
    fake.on("POST", tiktok.CREATOR_INFO_URL, ok(CREATOR))
    fake.on(
        "POST", tiktok.INIT_URL, tt_error(403, "unaudited_client_can_only_post_to_private_accounts")
    )
    run = publish(db, live_settings, v)
    assert run.status == AgentRunStatus.SKIPPED and run.output["gate"] == "channel"
    db.refresh(channel)
    assert channel.auth_status == ChannelAuthStatus.CONNECTED_RESTRICTED
    assert job.status == PublishingJobStatus.SCHEDULED
    assert db.scalar(select(Notification).where(Notification.title.contains("eingeschränkt")))


def test_agent_publishes_facebook_reel(
    db: Session, live_settings: Settings, fake: FakeGoogle
) -> None:
    v, _job = scheduled(db, live_settings, PublishingMode.LIVE, PlatformCode.FACEBOOK)
    authorize(db, live_settings, v.channel_id, "meta", list(meta.FACEBOOK_SCOPES), "111")
    fake.on(
        "POST",
        f"{G}/111/video_reels",
        httpx.Response(200, json={"video_id": "V1"}),
        httpx.Response(200, json={"success": True}),
    )
    fake.on("POST", "https://rupload.facebook.com/", httpx.Response(200, json={"success": True}))
    fake.on(
        "GET",
        f"{G}/V1",
        httpx.Response(200, json={"status": {"publishing_phase": {"status": "complete"}}}),
    )
    run = publish(db, live_settings, v)
    assert run.status == AgentRunStatus.SUCCEEDED, run.error
    assert run.output["external_id"] == "V1" and run.output["privacy"] == "public"


def test_agent_respects_the_daily_reels_limit(
    db: Session, live_settings: Settings, fake: FakeGoogle
) -> None:
    v, job = scheduled(db, live_settings, PublishingMode.LIVE, PlatformCode.INSTAGRAM)
    authorize(db, live_settings, v.channel_id, "meta", list(meta.INSTAGRAM_SCOPES))
    limited = live_settings.model_copy(update={"instagram_daily_post_limit": 0})
    run = publish(db, limited, v)
    assert run.status == AgentRunStatus.SKIPPED and run.output["gate"] == "retry_later"
    assert fake.requests == [] and job.status == PublishingJobStatus.SCHEDULED


def test_agent_needs_the_publish_permission(
    db: Session, live_settings: Settings, fake: FakeGoogle
) -> None:
    v, _job = scheduled(db, live_settings, PublishingMode.LIVE, PlatformCode.INSTAGRAM)
    channel = authorize(db, live_settings, v.channel_id, "meta", ["instagram_basic"])
    run = publish(db, live_settings, v)
    assert run.status == AgentRunStatus.SKIPPED and fake.requests == []
    db.refresh(channel)
    assert channel.auth_status == ChannelAuthStatus.EXPIRED


# --- API ----------------------------------------------------------------------------


def _channel(db: Session, code: PlatformCode) -> Channel:
    chain = build_chain(db)
    channel = db.scalar(
        select(Channel).where(
            Channel.platform.has(code=code), Channel.language == chain.variant.language
        )
    )
    assert channel is not None
    return channel


def _start(api: TestClient, h: dict[str, str], channel: Channel) -> str:
    res = api.post(f"/api/channels/{channel.id}/connect", headers=h)
    return str(parse_qs(urlparse(res.json()["url"]).query)["state"][0])
    return parse_qs(urlparse(res.json()["url"]).query)["state"][0]


def test_tiktok_connect_stays_restricted_until_audited(
    db: Session,
    settings: Settings,
    fake: FakeGoogle,
    api: TestClient,
    make_user: Callable[..., User],
) -> None:
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    channel = _channel(db, PlatformCode.TIKTOK)
    make_user("admin@example.com", UserRole.ADMIN)
    db.commit()
    h = login(api, "admin@example.com")
    state = _start(api, h, channel)
    fake.on(
        "POST",
        tiktok.TOKEN_URL,
        httpx.Response(
            200,
            json={
                "access_token": "act",
                "refresh_token": "rt",
                "expires_in": 86400,
                "scope": "video.publish",
                "open_id": "open-1",
            },
        ),
    )
    fake.on("POST", tiktok.CREATOR_INFO_URL, ok(CREATOR))
    cb = api.get(
        "/api/oauth/tiktok/callback", params={"state": state, "code": "c"}, follow_redirects=False
    )
    assert cb.headers["location"].endswith("tiktok=restricted")
    db.expire_all()
    assert db.get(Channel, channel.id).auth_status == ChannelAuthStatus.CONNECTED_RESTRICTED  # type: ignore[union-attr]
    row = next(c for c in api.get("/api/channels", headers=h).json() if c["id"] == channel.id)
    assert row["connected_account"] == "gce_test" and "act" not in json.dumps(row)

    # a state for TikTok is no ticket for Meta
    wrong = api.get(
        "/api/oauth/meta/callback", params={"state": state, "code": "c"}, follow_redirects=False
    )
    assert wrong.headers["location"].endswith("meta=invalid")

    fake.on("POST", tiktok.REVOKE_URL, httpx.Response(200))
    res = api.post(f"/api/channels/{channel.id}/disconnect", headers=h)
    assert res.json()["auth_status"] == "not_connected" and fake.sent("POST", tiktok.REVOKE_URL)


def test_tiktok_connect_when_audited_and_meta_connect(
    db: Session,
    settings: Settings,
    fake: FakeGoogle,
    api: TestClient,
    make_user: Callable[..., User],
) -> None:
    audited = settings.model_copy(update={"tiktok_app_audited": True})
    api.app.dependency_overrides[get_settings] = lambda: audited  # type: ignore[attr-defined]
    tt = _channel(db, PlatformCode.TIKTOK)
    ig = db.scalar(
        select(Channel).where(
            Channel.platform.has(code=PlatformCode.INSTAGRAM), Channel.language == tt.language
        )
    )
    assert ig is not None
    make_user("admin@example.com", UserRole.ADMIN)
    db.commit()
    h = login(api, "admin@example.com")

    state = _start(api, h, tt)
    fake.on(
        "POST",
        tiktok.TOKEN_URL,
        httpx.Response(
            200,
            json={
                "access_token": "act",
                "refresh_token": "rt",
                "expires_in": 86400,
                "scope": "video.publish",
                "open_id": "open-1",
            },
        ),
    )
    fake.on("POST", tiktok.CREATOR_INFO_URL, ok(CREATOR))
    cb = api.get(
        "/api/oauth/tiktok/callback", params={"state": state, "code": "c"}, follow_redirects=False
    )
    assert cb.headers["location"].endswith("tiktok=connected")

    state = _start(api, h, ig)
    fake.on(
        "GET",
        f"{G}/oauth/access_token",
        httpx.Response(200, json={"access_token": "short"}),
        httpx.Response(200, json={"access_token": "long", "expires_in": 5183944}),
    )
    fake.on("GET", f"{G}/me?", httpx.Response(200, json={"id": "u1"}))
    fake.on("GET", f"{G}/u1/accounts", httpx.Response(200, json={"data": [PAGE]}))
    fake.on(
        "GET",
        f"{G}/me/permissions",
        httpx.Response(
            200,
            json={"data": [{"permission": p, "status": "granted"} for p in meta.INSTAGRAM_SCOPES]},
        ),
    )
    cb = api.get(
        "/api/oauth/meta/callback", params={"state": state, "code": "c"}, follow_redirects=False
    )
    assert cb.headers["location"].endswith("meta=connected"), cb.headers["location"]
    db.expire_all()
    cred = db.scalar(select(ChannelCredential).where(ChannelCredential.channel_id == ig.id))
    assert cred is not None and cred.external_account_id == "1784"
    assert crypto.decrypt(audited, cred.access_token_enc or "") == "page-token"
    channel = db.get(Channel, ig.id)
    assert channel is not None and channel.auth_status == ChannelAuthStatus.AUTHORIZED
    # the Facebook Page behind the Instagram account became a channel of its own
    page = db.scalar(
        select(Channel).where(
            Channel.platform.has(code=PlatformCode.FACEBOOK), Channel.external_channel_id == "u1"
        )
    )
    assert page is not None and page.strategy["mirror_of"] == ig.id
    exchange = parse_qs(urlparse(str(fake.sent("GET", f"{G}/oauth/access_token")[1].url)).query)
    assert exchange["grant_type"] == ["fb_exchange_token"] and exchange["fb_exchange_token"] == [
        "short"
    ]
