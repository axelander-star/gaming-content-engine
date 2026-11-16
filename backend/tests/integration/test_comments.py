"""Comments (A3): classification, natural drafts, policy, fetch, send, agent, API."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import crypto
from core.config import Settings, get_settings
from core.enums import (
    ChannelAuthStatus,
    CommentKind,
    CommentStatus,
    Language,
    PlatformCode,
    PublishingJobStatus,
    PublishingMode,
    UserRole,
    VideoStatus,
)
from models import Channel, ChannelCredential, Comment, Post, PublishingJob
from models.access import User
from services import ai, comments, youtube
from services.orchestrator import run_agent
from tests.conftest import login
from tests.factories import build_chain

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)
MakeUser = Callable[..., User]


# --- rules -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Wie lange hält sich das im Kühlschrank?", CommentKind.QUESTION),
        ("how do you store it", CommentKind.QUESTION),
        ("Mega gut erklärt 🔥", CommentKind.PRAISE),
        ("❤️❤️", CommentKind.PRAISE),
        ("Totaler Clickbait, stimmt nicht", CommentKind.CRITICISM),
        ("Das ist mein Video, ich schalte meinen Anwalt ein", CommentKind.SENSITIVE),
        ("du idiot", CommentKind.SENSITIVE),
        ("check my channel www.example.com", CommentKind.SPAM),
        ("sub4sub?", CommentKind.SPAM),
        ("Hab ich gestern auch gemacht", CommentKind.OTHER),
    ],
)
def test_classify(text: str, kind: CommentKind) -> None:
    assert comments.classify(text)[0] == kind


def test_language_and_cleaning() -> None:
    assert comments.language_of("Wie geht das?", Language.EN) == Language.DE
    assert comments.language_of("How does this work?", Language.DE) == Language.EN
    assert comments.language_of("🔥🔥", Language.DE) == Language.DE
    assert comments.clean_reply('"Freut mich! #shorts"') == "Freut mich!"
    assert comments.clean_reply("Great question! It depends.") is None
    assert comments.clean_reply("Als KI kann ich das nicht sagen") is None
    assert comments.clean_reply("schau auf www.example.com") is None
    assert len(comments.clean_reply("wort " * 200) or "") <= comments.MAX_REPLY_CHARS


# --- helpers ---------------------------------------------------------------------------


def channel(db: Session, code: PlatformCode, lang: Language = Language.DE) -> Channel:
    build_chain(db)
    ch = db.scalar(select(Channel).where(Channel.platform.has(code=code), Channel.language == lang))
    assert ch is not None
    ch.is_paused = False
    return ch


def post(db: Session, ch: Channel, *, mock: bool = True, ext: str | None = None) -> Post:
    chain = build_chain(db)
    v = chain.variant
    v.channel_id, v.language, v.status, v.title = ch.id, ch.language, VideoStatus.PUBLISHED, "Hafer"
    job = PublishingJob(
        variant_id=v.id,
        channel_id=ch.id,
        status=PublishingJobStatus.SUCCEEDED,
        mode=PublishingMode.MOCK if mock else PublishingMode.LIVE,
        idempotency_key=f"c-{uuid4().hex}",
    )
    db.add(job)
    db.flush()
    p = Post(
        publishing_job_id=job.id,
        variant_id=v.id,
        channel_id=ch.id,
        external_post_id=ext or f"mock-{v.id}",
        published_at=NOW - timedelta(days=1),
        is_mock=mock,
    )
    db.add(p)
    db.flush()
    return p


def by_kind(rows: list[Comment]) -> dict[CommentKind, Comment]:
    return {c.kind: c for c in rows}


# --- mock flow -------------------------------------------------------------------------


def test_run_channel_with_test_comments(db: Session) -> None:
    settings = get_settings()
    ch = channel(db, PlatformCode.YOUTUBE)
    post(db, ch)
    res = comments.run_channel(db, settings, ch, NOW)
    assert res.fetched == 4 and res.ignored == 1
    rows = by_kind(list(db.scalars(select(Comment).where(Comment.channel_id == ch.id))))
    q = rows[CommentKind.QUESTION]
    assert q.status == CommentStatus.SENT and q.reply_is_mock  # simulated, never real
    assert q.reply_source == "mock" and q.reply_text
    assert rows[CommentKind.PRAISE].status == CommentStatus.SENT
    assert rows[CommentKind.SPAM].status == CommentStatus.IGNORED
    assert rows[CommentKind.SPAM].reply_text is None
    crit = rows[CommentKind.CRITICISM]
    assert crit.status == CommentStatus.REVIEW and crit.review_reason
    # nothing twice
    assert comments.run_channel(db, settings, ch, NOW).fetched == 0


def test_tiktok_and_auto_off_go_to_review(db: Session, make_user: MakeUser) -> None:
    settings = get_settings()
    user = make_user()
    tt = channel(db, PlatformCode.TIKTOK)
    post(db, tt)
    comments.run_channel(db, settings, tt, NOW)
    q = db.scalar(
        select(Comment).where(Comment.channel_id == tt.id, Comment.kind == CommentKind.QUESTION)
    )
    assert q is not None and q.status == CommentStatus.REVIEW
    assert "TikTok" in (q.review_reason or "")
    with pytest.raises(comments.CommentError):
        comments.send(db, settings, q)
    assert comments.mark_done(db, q, user.id).status == CommentStatus.SENT

    off = settings.model_copy(update={"comment_auto_reply": False})
    yt = channel(db, PlatformCode.YOUTUBE, Language.EN)
    post(db, yt)
    comments.run_channel(db, off, yt, NOW)
    statuses = {c.status for c in db.scalars(select(Comment).where(Comment.channel_id == yt.id))}
    assert statuses == {CommentStatus.REVIEW, CommentStatus.IGNORED}


def test_bot_sounding_draft_is_retried_then_dropped(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    ch = channel(db, PlatformCode.INSTAGRAM)
    answers = iter(["Great question! It depends.", "Kommt drauf an, eher drei Tage."])

    class R:
        provider = "claude"

        def __init__(self) -> None:
            self.text = next(answers)

    monkeypatch.setattr(ai, "generate", lambda *_a, **_k: R())
    c = Comment(
        channel_id=ch.id,
        platform=PlatformCode.INSTAGRAM,
        external_id="x1",
        text="Wie lange hält das?",
    )
    db.add(c)
    db.flush()
    comments.process(db, get_settings(), c, ch)
    assert c.reply_text == "Kommt drauf an, eher drei Tage."
    assert c.reply_source == "claude" and c.status == CommentStatus.READY

    def blocked(*_a: object, **_k: object) -> object:
        raise ai.AIBlockedError("cap", "Monatsgrenze")

    monkeypatch.setattr(ai, "generate", blocked)
    c2 = Comment(channel_id=ch.id, platform=PlatformCode.INSTAGRAM, external_id="x2", text="Toll!")
    db.add(c2)
    db.flush()
    comments.process(db, get_settings(), c2, ch)
    assert c2.status == CommentStatus.NEW and c2.reply_text is None  # retried next run


# --- live paths (HTTP mocked) ------------------------------------------------------------


@pytest.fixture
def yt_transport() -> Iterator[list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/commentThreads"):
            assert request.url.params["videoId"] == "VID1"
            assert request.url.params["textFormat"] == "plainText"
            item = lambda cid, author, text: {  # noqa: E731
                "snippet": {
                    "topLevelComment": {
                        "id": cid,
                        "snippet": {
                            "textOriginal": text,
                            "authorDisplayName": author,
                            "authorChannelId": {"value": author},
                            "likeCount": 3,
                            "publishedAt": "2026-11-16T10:00:00Z",
                        },
                    }
                }
            }
            return httpx.Response(200, json={"items": [
                item("C1", "viewer", "Wie lange hält sich das?"),
                item("C2", "UC-own", "Danke euch allen!"),  # own channel: skipped
            ]})  # fmt: skip
        if request.url.path.endswith("/comments"):
            body = json.loads(request.content)
            assert body == {
                "snippet": {"parentId": "C1", "textOriginal": body["snippet"]["textOriginal"]}
            }
            return httpx.Response(200, json={"id": "R1"})
        return httpx.Response(404)

    youtube.TRANSPORT = httpx.MockTransport(handler)
    try:
        yield seen
    finally:
        youtube.TRANSPORT = None


def test_youtube_live_fetch_and_reply(db: Session, yt_transport: list[httpx.Request]) -> None:
    live = get_settings().model_copy(
        update={
            "publishing_mode": "live",
            "auto_publish_enabled": True,
            "comment_mock_samples": False,
        }
    )
    ch = channel(db, PlatformCode.YOUTUBE)
    ch.auth_status = ChannelAuthStatus.AUTHORIZED
    db.add(ChannelCredential(
        channel_id=ch.id, provider="youtube",
        access_token_enc=crypto.encrypt(live, "tok"),
        expires_at=NOW + timedelta(hours=1),
        scopes=list(youtube.SCOPES), external_account_id="UC-own",
    ))  # fmt: skip
    post(db, ch, mock=False, ext="VID1")
    res = comments.run_channel(db, live, ch, NOW)
    assert (res.fetched, res.sent) == (1, 1), res.errors
    c = db.scalar(select(Comment).where(Comment.channel_id == ch.id))
    assert c is not None and c.external_id == "C1" and c.like_count == 3
    assert c.status == CommentStatus.SENT and not c.reply_is_mock and c.reply_external_id == "R1"
    reply_req = [r for r in yt_transport if r.method == "POST"]
    assert reply_req and reply_req[0].headers["Authorization"] == "Bearer tok"


def test_youtube_reply_without_scope_fails_clearly(
    db: Session, yt_transport: list[httpx.Request]
) -> None:
    live = get_settings().model_copy(
        update={"publishing_mode": "live", "auto_publish_enabled": True}
    )
    ch = channel(db, PlatformCode.YOUTUBE)
    ch.auth_status = ChannelAuthStatus.AUTHORIZED
    db.add(ChannelCredential(channel_id=ch.id, provider="youtube",
                             access_token_enc=crypto.encrypt(live, "tok"),
                             scopes=[youtube.UPLOAD_SCOPE]))  # fmt: skip
    p = post(db, ch, mock=False, ext="VID1")
    c = Comment(
        channel_id=ch.id,
        post_id=p.id,
        platform=PlatformCode.YOUTUBE,
        external_id="C9",
        text="Frage?",
        reply_text="Antwort",
        status=CommentStatus.READY,
    )
    db.add(c)
    db.flush()
    with pytest.raises(comments.CommentError, match="neu verbinden"):
        comments.send(db, live, c)
    assert c.status == CommentStatus.FAILED
    assert not [r for r in yt_transport if r.method == "POST"]


# --- agent and API -------------------------------------------------------------------------


def test_agent_runs_over_channels(db: Session) -> None:
    ch = channel(db, PlatformCode.INSTAGRAM)
    post(db, ch)
    run = run_agent(db, get_settings(), "community", {"sweep": True})
    assert run.status.value == "succeeded"
    assert db.scalar(select(Comment.id).where(Comment.channel_id == ch.id)) is not None


def test_api(
    api: TestClient, db: Session, make_user: MakeUser, settings: Settings | None = None
) -> None:
    tt = channel(db, PlatformCode.TIKTOK)
    yt = channel(db, PlatformCode.YOUTUBE, Language.EN)
    post(db, yt)
    comments.run_channel(
        db, get_settings().model_copy(update={"comment_auto_reply": False}), yt, NOW
    )
    make_user(email="op@example.com", role=UserRole.OPERATOR)
    headers = login(api, "op@example.com")

    stats = api.get("/api/comments/stats").json()
    assert stats["by_status"]["review"] == 3 and stats["live"] is False

    review = api.get("/api/comments?state=review").json()
    q = next(c for c in review if c["kind"] == "question")
    assert q["is_test"] and q["can_send"] and q["post_title"] == "Hafer"
    r = api.put(f"/api/comments/{q['id']}/reply", json={"reply_text": "Two days in the fridge."},
                headers=headers)  # fmt: skip
    assert r.json()["reply_text"] == "Two days in the fridge."
    r = api.post(f"/api/comments/{q['id']}/redraft", headers=headers)
    assert r.status_code == 200 and r.json()["reply_text"] != "Two days in the fridge."
    r = api.post(f"/api/comments/{q['id']}/send", json={"reply_text": "Two days, max three."},
                 headers=headers)  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sent" and r.json()["reply_is_mock"]
    assert api.post(f"/api/comments/{q['id']}/ignore", headers=headers).status_code == 422

    crit = next(c for c in review if c["kind"] == "criticism")
    assert (
        api.post(f"/api/comments/{crit['id']}/ignore", headers=headers).json()["status"]
        == "ignored"
    )

    r = api.post("/api/comments/manual", json={"channel_id": tt.id, "text": "Wie lange hält das?",
                                               "author": "lena"}, headers=headers)  # fmt: skip
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["status"] == "review" and m["reply_text"] and not m["can_send"]
    payload = {"channel_id": tt.id, "text": "Wie lange hält das?", "author": "lena"}
    again = api.post("/api/comments/manual", json=payload, headers=headers)
    assert again.status_code == 422
    assert api.post(f"/api/comments/{m['id']}/done", headers=headers).json()["status"] == "sent"

    assert api.post("/api/comments/run", headers=headers).json()["job_id"]


def test_viewer_cannot_act(api: TestClient, db: Session, make_user: MakeUser) -> None:
    tt = channel(db, PlatformCode.TIKTOK)
    make_user(email="v@example.com", role=UserRole.VIEWER)
    headers = login(api, "v@example.com")
    r = api.post("/api/comments/manual", json={"channel_id": tt.id, "text": "Hi"}, headers=headers)
    assert r.status_code == 403
