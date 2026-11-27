"""Phase 12: YouTube connection, resumable upload and the Publishing Agent.

Google is never contacted: every HTTP call goes to an ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
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
    MaterialStatus,
    PlatformCode,
    PublishingJobStatus,
    PublishingMode,
    UserRole,
    VideoStatus,
)
from models import Channel, ChannelCredential, User, Variant
from models.access import Notification
from models.production import QualityCheck
from models.publishing import Post, PublishingJob
from services import orchestrator, storage, youtube
from services.controls import update_runtime_controls
from tests.conftest import login
from tests.factories import build_chain

UPLOAD_SESSION = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=abc"


class FakeGoogle:
    """Scripted answers per (method, url prefix); records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: list[tuple[str, str, list[httpx.Response]]] = []

    def on(self, method: str, prefix: str, *responses: httpx.Response) -> None:
        self.routes.append((method, prefix, list(responses)))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for method, prefix, responses in self.routes:
            if request.method == method and str(request.url).startswith(prefix) and responses:
                return responses.pop(0) if len(responses) > 1 else responses[0]
        return httpx.Response(599, json={"error": "unexpected request"})

    def sent(self, method: str, prefix: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and str(r.url).startswith(prefix)]


@pytest.fixture
def google(monkeypatch: pytest.MonkeyPatch) -> FakeGoogle:
    fake = FakeGoogle()
    monkeypatch.setattr(youtube, "TRANSPORT", httpx.MockTransport(fake))
    return fake


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(
        update={
            "media_root": str(tmp_path / "media"),
            "youtube_oauth_client_id": "client-id.apps.googleusercontent.com",
            "youtube_oauth_client_secret": SecretStr("client-secret"),
            "youtube_oauth_redirect_uri": "https://gce.example/api/oauth/youtube/callback",
        }
    )


def token_response(**extra: Any) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "access_token": "ya29.access",
            "expires_in": 3599,
            "refresh_token": "1//refresh",
            "scope": " ".join(youtube.SCOPES),
            "token_type": "Bearer",
            **extra,
        },
    )


def channel_response() -> httpx.Response:
    return httpx.Response(
        200, json={"items": [{"id": "UC123", "snippet": {"title": "Mein Kanal"}}]}
    )


# --- crypto and OAuth ---------------------------------------------------------------


def test_tokens_are_encrypted_and_need_the_key(settings: Settings) -> None:
    enc = crypto.encrypt(settings, "1//refresh")
    assert "refresh" not in enc and crypto.decrypt(settings, enc) == "1//refresh"
    other = settings.model_copy(update={"credentials_encryption_key": SecretStr("another-key")})
    with pytest.raises(crypto.CredentialError):
        crypto.decrypt(other, enc)


def test_authorization_url_asks_for_offline_upload_access(settings: Settings) -> None:
    state = youtube.make_state(settings, 7, 3)
    url = urlparse(youtube.authorization_url(settings, state))
    q = parse_qs(url.query)
    assert url.netloc == "accounts.google.com" and url.path == "/o/oauth2/v2/auth"
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent select_account"]
    assert youtube.UPLOAD_SCOPE in q["scope"][0].split()
    assert q["redirect_uri"] == [settings.youtube_oauth_redirect_uri]
    assert youtube.read_state(settings, q["state"][0]) == (7, 3)
    with pytest.raises(youtube.YouTubeError):
        youtube.read_state(settings, state[:-2] + "xx")
    with pytest.raises(youtube.NotConfiguredError):
        youtube.authorization_url(get_settings(), state)


def test_refresh_and_expired_grant(db: Session, settings: Settings, google: FakeGoogle) -> None:
    chain = build_chain(db)
    cred = ChannelCredential(
        channel_id=chain.channel.id,
        provider="youtube",
        access_token_enc=crypto.encrypt(settings, "old"),
        refresh_token_enc=crypto.encrypt(settings, "1//refresh"),
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    google.on("POST", youtube.TOKEN_URL, token_response(refresh_token=None, access_token="new"))
    assert youtube.access_token(db, settings, cred) == "new"
    sent = parse_qs(google.sent("POST", youtube.TOKEN_URL)[0].content.decode())
    assert sent["grant_type"] == ["refresh_token"] and sent["refresh_token"] == ["1//refresh"]
    assert crypto.decrypt(settings, cred.refresh_token_enc or "") == "1//refresh"  # kept
    assert youtube.access_token(db, settings, cred) == "new"  # still valid: no new request
    assert len(google.sent("POST", youtube.TOKEN_URL)) == 1

    cred.expires_at = datetime.now(UTC)
    google.routes.clear()
    google.on("POST", youtube.TOKEN_URL, httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(youtube.AuthExpiredError):
        youtube.access_token(db, settings, cred)


# --- resumable upload ---------------------------------------------------------------


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "v.mp4"
    path.write_bytes(b"\x00" * 1000)
    return path


def resource() -> dict[str, Any]:
    return youtube.video_resource("Titel", "Text #GamingDeutsch", "de", "private", True)


def test_upload_resumes_after_server_error(google: FakeGoogle, video: Path) -> None:
    google.on("POST", youtube.UPLOAD_URL, httpx.Response(200, headers={"Location": UPLOAD_SESSION}))
    google.on(
        "PUT",
        UPLOAD_SESSION,
        httpx.Response(503),  # first upload attempt
        httpx.Response(308, headers={"Range": "bytes=0-399"}),  # status query
        httpx.Response(201, json={"id": "vid123", "status": {"privacyStatus": "private"}}),
    )
    result = youtube.upload("tok", video, resource(), sleep=lambda s: None)
    assert result.video_id == "vid123" and result.privacy == "private"
    assert result.url == "https://www.youtube.com/shorts/vid123"
    start = google.sent("POST", youtube.UPLOAD_URL)[0]
    assert start.url.params["uploadType"] == "resumable"
    assert start.headers["X-Upload-Content-Length"] == "1000"
    body = json.loads(start.content)
    assert body["status"]["privacyStatus"] == "private"  # never left to the public default
    assert body["status"]["containsSyntheticMedia"] is True
    assert body["snippet"]["categoryId"] == "20"
    puts = google.sent("PUT", UPLOAD_SESSION)
    assert puts[1].headers["Content-Range"] == "bytes */1000"
    assert puts[2].headers["Content-Range"] == "bytes 400-999/1000"
    assert len(puts[2].content) == 600


def test_upload_errors(google: FakeGoogle, video: Path) -> None:
    google.on("POST", youtube.UPLOAD_URL, httpx.Response(
        403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}}))  # fmt: skip
    with pytest.raises(youtube.TransientError):
        youtube.upload("tok", video, resource(), sleep=lambda s: None)
    google.routes.clear()
    google.on("POST", youtube.UPLOAD_URL, httpx.Response(
        400, json={"error": {"errors": [{"reason": "invalidTitle"}]}}))  # fmt: skip
    with pytest.raises(youtube.YouTubeError, match="invalidTitle") as err:
        youtube.upload("tok", video, resource(), sleep=lambda s: None)
    assert not isinstance(err.value, youtube.TransientError)
    google.routes.clear()
    google.on("POST", youtube.UPLOAD_URL, httpx.Response(200, headers={"Location": UPLOAD_SESSION}))
    google.on("PUT", UPLOAD_SESSION, httpx.Response(503))
    with pytest.raises(youtube.TransientError):
        youtube.upload("tok", video, resource(), attempts=2, sleep=lambda s: None)


# --- Publishing Agent ---------------------------------------------------------------


def scheduled(
    db: Session,
    settings: Settings,
    mode: PublishingMode = PublishingMode.MOCK,
    platform: PlatformCode = PlatformCode.YOUTUBE,
    due: bool = True,
) -> tuple[Variant, PublishingJob]:
    chain = build_chain(db)
    channel = db.scalar(
        select(Channel)
        .join(Channel.platform)
        .where(Channel.language == chain.variant.language)
        .where(Channel.platform.has(code=platform))
    )
    assert channel is not None
    src = Path(settings.media_root) / "src.mp4"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"video-bytes" * 100)
    stored = storage.store_path(settings, src, "variants", ".mp4")
    channel.is_paused = channel.platform.is_paused = False  # seeded paused
    v = chain.variant
    v.channel_id, v.status, v.quality_score = channel.id, VideoStatus.SCHEDULED, 0.9
    v.storage_uri, v.sha256, v.title, v.description = stored.uri, stored.sha256, "Titel", "Text"
    chain.gameplay_file.status = MaterialStatus.ANALYZED
    when = datetime.now(UTC) + (timedelta(minutes=-5) if due else timedelta(hours=3))
    job = PublishingJob(
        variant_id=v.id,
        channel_id=channel.id,
        status=PublishingJobStatus.SCHEDULED,
        mode=mode,
        scheduled_for=when,
        idempotency_key=f"t-{v.id}",
    )
    db.add(job)
    db.add(QualityCheck(variant_id=v.id, passed=True, score=0.9))
    db.flush()
    return v, job


def publish(db: Session, settings: Settings, v: Variant) -> Any:
    return orchestrator.run_agent(
        db, settings, "publishing", {"entity_type": "variants", "entity_id": v.id}
    )


def test_mock_publishing_creates_a_test_post_once(db: Session, settings: Settings) -> None:
    v, job = scheduled(db, settings)
    run = publish(db, settings, v)
    assert run.status == AgentRunStatus.SUCCEEDED, run.error
    post = db.scalar(select(Post).where(Post.variant_id == v.id))
    assert post is not None and post.is_mock and post.external_post_id.startswith("mock-")  # type: ignore[union-attr]
    assert job.status == PublishingJobStatus.SUCCEEDED and job.attempts == 1
    assert v.status == VideoStatus.PUBLISHED
    # a second run finds no planned job and changes nothing
    assert publish(db, settings, v).status == AgentRunStatus.SKIPPED  # wrong status now
    assert len(db.scalars(select(Post).where(Post.variant_id == v.id)).all()) == 1


def test_paused_channel_publishes_nothing(db: Session, settings: Settings) -> None:
    v, job = scheduled(db, settings)
    channel = db.get(Channel, v.channel_id)
    assert channel is not None
    channel.is_paused = True
    db.flush()
    run = publish(db, settings, v)
    assert run.status == AgentRunStatus.SKIPPED and run.output["gate"] == "channel"
    assert job.status == PublishingJobStatus.SCHEDULED


def test_only_due_jobs_are_dispatched(db: Session, settings: Settings) -> None:
    from agents.registry import get_spec
    from services import gates

    spec = get_spec("publishing")
    assert spec is not None
    due, _ = scheduled(db, settings)
    later, _ = scheduled(db, settings, due=False)
    ids = db.scalars(
        select(Variant.id).where(Variant.status == VideoStatus.SCHEDULED, *gates.step_filter(spec))
    ).all()
    assert due.id in ids and later.id not in ids


def test_existing_post_is_completed_without_new_upload(db: Session, settings: Settings) -> None:
    v, job = scheduled(db, settings)
    db.add(
        Post(
            publishing_job_id=job.id,
            variant_id=v.id,
            channel_id=job.channel_id,
            external_post_id="earlier",
            published_at=datetime.now(UTC),
            is_mock=True,
        )
    )
    db.flush()
    run = publish(db, settings, v)
    assert run.status == AgentRunStatus.SUCCEEDED and run.output["resumed"] is True
    assert v.status == VideoStatus.PUBLISHED and job.status == PublishingJobStatus.SUCCEEDED


def test_changed_file_is_not_published(db: Session, settings: Settings) -> None:
    v, job = scheduled(db, settings)
    storage.resolve(settings, v.storage_uri or "").write_bytes(b"other")
    run = publish(db, settings, v)
    assert run.status == AgentRunStatus.FAILED
    assert job.status == PublishingJobStatus.FAILED and "verändert" in (job.last_error or "")
    assert db.scalar(select(Post).where(Post.variant_id == v.id)) is None


@pytest.fixture
def live(
    settings: Settings, db: Session, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Settings]:
    import agents.publishing as agent_module

    monkeypatch.setattr(agent_module, "get_redis", lambda: redis_client)
    update_runtime_controls(db, None, auto_publish_enabled=True)
    yield settings.model_copy(update={"publishing_mode": "live", "auto_publish_enabled": True})


def connect_channel(db: Session, settings: Settings, v: Variant) -> Channel:
    channel = db.get(Channel, v.channel_id)
    assert channel is not None
    channel.auth_status, channel.is_paused = ChannelAuthStatus.AUTHORIZED, False
    channel.platform.is_paused = False
    db.add(
        ChannelCredential(
            channel_id=channel.id,
            provider="youtube",
            access_token_enc=crypto.encrypt(settings, "ya29.access"),
            refresh_token_enc=crypto.encrypt(settings, "1//refresh"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=list(youtube.SCOPES),
        )
    )
    db.flush()
    return channel


def test_live_upload_to_an_authorized_channel(
    db: Session, live: Settings, google: FakeGoogle
) -> None:
    v, _job = scheduled(db, live, PublishingMode.LIVE)
    connect_channel(db, live, v)
    google.on("POST", youtube.UPLOAD_URL, httpx.Response(200, headers={"Location": UPLOAD_SESSION}))
    done = httpx.Response(201, json={"id": "yt1", "status": {"privacyStatus": "private"}})
    google.on("PUT", UPLOAD_SESSION, done)
    run = publish(db, live, v)
    assert run.status == AgentRunStatus.SUCCEEDED, run.error
    post = db.scalar(select(Post).where(Post.variant_id == v.id))
    assert post is not None and not post.is_mock and post.external_post_id == "yt1"
    assert post.url == "https://www.youtube.com/shorts/yt1" and run.output["privacy"] == "private"
    start = google.sent("POST", youtube.UPLOAD_URL)[0]
    assert start.headers["Authorization"] == "Bearer ya29.access"
    assert json.loads(start.content)["status"]["privacyStatus"] == "private"


def test_live_job_waits_for_an_unauthorized_channel(
    db: Session, live: Settings, google: FakeGoogle
) -> None:
    v, _job = scheduled(db, live, PublishingMode.LIVE)
    channel = db.get(Channel, v.channel_id)
    assert channel is not None
    channel.is_paused = channel.platform.is_paused = False
    run = publish(db, live, v)
    assert run.status == AgentRunStatus.SKIPPED and run.output["gate"] == "channel"
    assert v.status == VideoStatus.SCHEDULED and google.requests == []


def test_expired_connection_marks_the_channel(
    db: Session, live: Settings, google: FakeGoogle
) -> None:
    v, job = scheduled(db, live, PublishingMode.LIVE)
    channel = connect_channel(db, live, v)
    cred = db.scalar(select(ChannelCredential).where(ChannelCredential.channel_id == channel.id))
    assert cred is not None
    cred.expires_at = datetime.now(UTC)
    google.on("POST", youtube.TOKEN_URL, httpx.Response(400, json={"error": "invalid_grant"}))
    run = publish(db, live, v)
    assert run.status == AgentRunStatus.SKIPPED
    db.refresh(channel)
    assert channel.auth_status == ChannelAuthStatus.EXPIRED
    assert job.status == PublishingJobStatus.SCHEDULED and v.status == VideoStatus.SCHEDULED
    assert db.scalar(select(Notification).where(Notification.title.contains("abgelaufen")))


def test_upload_quota_moves_the_job_later(
    db: Session, live: Settings, google: FakeGoogle, redis_client: Redis
) -> None:
    v, job = scheduled(db, live, PublishingMode.LIVE)
    connect_channel(db, live, v)
    limited = live.model_copy(update={"youtube_daily_upload_limit": 0})
    before = job.scheduled_for
    run = publish(db, limited, v)
    assert run.status == AgentRunStatus.SKIPPED and run.output["gate"] == "retry_later"
    assert job.status == PublishingJobStatus.SCHEDULED and job.scheduled_for > before  # type: ignore[operator]
    assert google.sent("POST", youtube.UPLOAD_URL) == []


def test_authorized_channel_without_stored_access_expires(db: Session, live: Settings) -> None:
    v, job = scheduled(db, live, PublishingMode.LIVE, PlatformCode.TIKTOK)
    channel = db.get(Channel, v.channel_id)
    assert channel is not None
    channel.auth_status, channel.is_paused = ChannelAuthStatus.AUTHORIZED, False
    channel.platform.is_paused = False
    db.flush()
    run = publish(db, live, v)
    assert run.status == AgentRunStatus.SKIPPED and run.output["gate"] == "channel"
    db.refresh(channel)
    assert channel.auth_status == ChannelAuthStatus.EXPIRED
    assert job.status == PublishingJobStatus.SCHEDULED and "nicht verbunden" in (
        job.last_error or ""
    )


def test_mock_job_stays_mock_in_live_mode(db: Session, live: Settings, google: FakeGoogle) -> None:
    v, _job = scheduled(db, live, PublishingMode.MOCK)
    connect_channel(db, live, v)
    run = publish(db, live, v)
    assert run.status == AgentRunStatus.SUCCEEDED and run.output["mock"] is True
    assert google.requests == []


# --- API ----------------------------------------------------------------------------


def test_connect_callback_and_disconnect(
    db: Session,
    settings: Settings,
    google: FakeGoogle,
    api: TestClient,
    make_user: Callable[..., User],
) -> None:
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    chain = build_chain(db)
    channel = db.scalar(
        select(Channel).where(
            Channel.platform.has(code=PlatformCode.YOUTUBE),
            Channel.language == chain.variant.language,
        )
    )
    assert channel is not None
    admin = make_user("admin@example.com", UserRole.ADMIN)
    make_user("op@example.com", UserRole.OPERATOR)
    db.commit()

    h_op = login(api, "op@example.com")
    assert api.post(f"/api/channels/{channel.id}/connect", headers=h_op).status_code == 403
    h = login(api, "admin@example.com")
    res = api.post(f"/api/channels/{channel.id}/connect", headers=h)
    assert res.status_code == 200, res.text
    state = parse_qs(urlparse(res.json()["url"]).query)["state"][0]

    google.on("POST", youtube.TOKEN_URL, token_response())
    google.on("GET", f"{youtube.API}/channels", channel_response())
    cb = api.get("/api/oauth/youtube/callback", params={"state": state, "code": "4/abc"},
                 follow_redirects=False)  # fmt: skip
    assert cb.status_code == 303 and cb.headers["location"].endswith("youtube=connected")
    db.expire_all()
    cred = db.scalar(select(ChannelCredential).where(ChannelCredential.channel_id == channel.id))
    assert cred is not None and cred.external_account_name == "Mein Kanal"
    assert "refresh" not in (cred.refresh_token_enc or "") and cred.connected_by_user_id == admin.id
    db.refresh(channel)
    assert channel.auth_status == ChannelAuthStatus.AUTHORIZED
    assert channel.external_channel_id == "UC123"

    listed = api.get("/api/channels", headers=h).json()
    row = next(c for c in listed if c["id"] == channel.id)
    assert row["connected_account"] == "Mein Kanal" and "token" not in json.dumps(row)

    bad = api.get("/api/oauth/youtube/callback", params={"state": "forged", "code": "x"},
                  follow_redirects=False)  # fmt: skip
    assert bad.headers["location"].endswith("youtube=invalid")

    google.on("POST", youtube.REVOKE_URL, httpx.Response(200))
    res = api.post(f"/api/channels/{channel.id}/disconnect", headers=h)
    assert res.status_code == 200 and res.json()["auth_status"] == "not_connected"
    assert google.sent("POST", youtube.REVOKE_URL)
    db.expire_all()
    assert (
        db.scalar(select(ChannelCredential).where(ChannelCredential.channel_id == channel.id))
        is None
    )


def test_one_platform_account_per_channel(
    db: Session,
    settings: Settings,
    google: FakeGoogle,
    api: TestClient,
    make_user: Callable[..., User],
) -> None:
    """Several YouTube channels (one per topic area) work; the same account twice does not."""
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    chain = build_chain(db)
    first = db.scalar(select(Channel).where(Channel.platform.has(code=PlatformCode.YOUTUBE)))
    assert first is not None
    second = Channel(
        platform_id=first.platform_id,
        content_project_id=first.content_project_id,
        language=chain.variant.language,
        name="YouTube Ernährung",
        auth_status=ChannelAuthStatus.NOT_CONNECTED,
    )
    db.add(second)
    make_user("admin@example.com", UserRole.ADMIN)
    db.commit()
    h = login(api, "admin@example.com")

    def connect(channel: Channel) -> str:
        res = api.post(f"/api/channels/{channel.id}/connect", headers=h)
        state = parse_qs(urlparse(res.json()["url"]).query)["state"][0]
        cb = api.get("/api/oauth/youtube/callback", params={"state": state, "code": "4/x"},
                     follow_redirects=False)  # fmt: skip
        return str(cb.headers["location"])

    other = httpx.Response(200, json={"items": [{"id": "UC999", "snippet": {"title": "Zwei"}}]})
    google.on("POST", youtube.TOKEN_URL, token_response())
    google.on("GET", f"{youtube.API}/channels", channel_response(), channel_response(), other)
    assert connect(first).endswith("youtube=connected")
    assert connect(second).endswith("youtube=in_use")  # same Google channel UC123
    db.expire_all()
    assert db.get(Channel, second.id).external_channel_id is None  # type: ignore[union-attr]
    assert connect(second).endswith("youtube=connected")  # its own channel UC999
    db.expire_all()
    ids = {db.get(Channel, c.id).external_channel_id for c in (first, second)}  # type: ignore[union-attr]
    assert ids == {"UC123", "UC999"}


def test_connect_needs_a_configured_client(
    db: Session, api: TestClient, make_user: Callable[..., User]
) -> None:
    chain = build_chain(db)
    make_user("admin@example.com", UserRole.ADMIN)
    db.commit()
    h = login(api, "admin@example.com")
    res = api.post(f"/api/channels/{chain.channel.id}/connect", headers=h)
    assert res.status_code in (409, 400)


def test_connect_failure_names_the_reason(
    db: Session,
    settings: Settings,
    google: FakeGoogle,
    api: TestClient,
    make_user: Callable[..., User],
) -> None:
    """A failed connection tells the dashboard why (no channel, API off, wrong client)."""
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    build_chain(db)
    channel = db.scalar(select(Channel).where(Channel.platform.has(code=PlatformCode.YOUTUBE)))
    assert channel is not None
    make_user("admin@example.com", UserRole.ADMIN)
    db.commit()
    h = login(api, "admin@example.com")

    def attempt() -> str:
        res = api.post(f"/api/channels/{channel.id}/connect", headers=h)
        state = parse_qs(urlparse(res.json()["url"]).query)["state"][0]
        cb = api.get("/api/oauth/youtube/callback", params={"state": state, "code": "4/abc"},
                     follow_redirects=False)  # fmt: skip
        assert cb.status_code == 303
        return str(cb.headers["location"])

    google.on("POST", youtube.TOKEN_URL, token_response())
    google.on("GET", f"{youtube.API}/channels", httpx.Response(200, json={"items": []}))
    assert attempt().endswith("youtube=failed&reason=no_channel")

    disabled = {
        "error": {
            "code": 403,
            "message": "YouTube Data API v3 has not been used in project 1 or it is disabled.",
            "errors": [{"reason": "accessNotConfigured"}],
            "status": "PERMISSION_DENIED",
        }
    }
    google.routes.clear()
    google.on("POST", youtube.TOKEN_URL, token_response())
    google.on("GET", f"{youtube.API}/channels", httpx.Response(403, json=disabled))
    assert attempt().endswith("youtube=failed&reason=api_disabled")

    google.routes.clear()
    google.on("POST", youtube.TOKEN_URL, httpx.Response(401, json={"error": "invalid_client"}))
    assert attempt().endswith("youtube=failed&reason=client")
    db.refresh(channel)
    assert channel.auth_status == ChannelAuthStatus.NOT_CONNECTED
