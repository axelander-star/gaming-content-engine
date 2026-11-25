"""Ausbau A4: chat attachments, spoken answers, notifications, push, watchdog.

No test talks to ntfy or Claude: push runs against an ``httpx.MockTransport``,
the live chat loop against a fake client.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import (
    AgentRunStatus,
    ChannelAuthStatus,
    CommentKind,
    CommentStatus,
    NotificationLevel,
    PlatformCode,
    PublishingJobStatus,
    PublishingMode,
    UserRole,
)
from models import Channel, Comment, PublishingJob
from models.access import Notification, User
from models.assistant import ChatAction, ChatAttachment, ChatMessage
from models.control import AgentRun
from services import ai, assistant, chat_media, notify, watchdog
from services.controls import update_operations
from services.seed import seed_base_data
from tests.conftest import login
from tests.factories import build_chain

pytestmark = pytest.mark.integration

MakeUser = Callable[..., User]
NOON = datetime(2026, 11, 17, 11, 0, tzinfo=UTC)  # 12:00 in Berlin
NIGHT = datetime(2026, 11, 17, 1, 0, tzinfo=UTC)  # 02:00 in Berlin


def _settings(tmp_path: Any, **update: Any) -> Settings:
    return get_settings().model_copy(update={"media_root": str(tmp_path), **update})


def _png(w: int = 2400, h: int = 1200) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def _text_pdf(text: str) -> bytes:
    """A one-page PDF with a real text layer (built by hand, no extra library)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def _scan_pdf() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), "white").save(buf, "PDF")
    return buf.getvalue()


# --- attachments ---------------------------------------------------------------------


def test_save_image_and_pdf(db: Session, make_user: MakeUser, tmp_path: Any) -> None:
    settings = _settings(tmp_path)
    user = make_user()
    img = chat_media.save(db, settings, user, "foto.png", "image/png", _png())
    assert (img.width, img.height) == (2400, 1200)
    pdf = chat_media.save(
        db, settings, user, "../../angebot.pdf", "application/pdf", _text_pdf("Preis 450 Euro")
    )
    assert pdf.filename == "angebot.pdf"
    assert pdf.pages == 1 and "Preis 450 Euro" in (pdf.extracted_text or "")
    scan = chat_media.save(db, settings, user, "scan.pdf", "application/pdf", _scan_pdf())
    assert scan.pages == 1 and not scan.extracted_text

    with pytest.raises(chat_media.ChatMediaError):
        chat_media.save(db, settings, user, "x.gif", "image/gif", b"GIF89a")
    with pytest.raises(chat_media.ChatMediaError):  # PNG name, PDF content
        chat_media.save(db, settings, user, "x.png", "image/png", _text_pdf("x"))


def test_content_blocks_downscale_and_bound_text(
    db: Session, make_user: MakeUser, tmp_path: Any
) -> None:
    settings = _settings(tmp_path)
    user = make_user()
    img = chat_media.save(db, settings, user, "foto.png", "image/png", _png())
    pdf = chat_media.save(db, settings, user, "a.pdf", "application/pdf", _text_pdf("Hallo"))
    pdf.extracted_text = "x" * 50_000
    scan = chat_media.save(db, settings, user, "scan.pdf", "application/pdf", _scan_pdf())

    blocks = chat_media.content_blocks(settings, "Was hältst du davon?", [img, pdf, scan])
    assert isinstance(blocks, list)
    image, text = blocks[0], blocks[-1]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg"
    import base64

    with Image.open(io.BytesIO(base64.b64decode(image["source"]["data"]))) as small:
        assert max(small.size) == chat_media.MAX_IMAGE_EDGE
    assert "(gekürzt)" in text["text"] and "ohne lesbaren Text" in text["text"]
    assert text["text"].endswith("Was hältst du davon?")
    assert len(text["text"]) < chat_media.MAX_PROMPT_PDF_CHARS + 2000
    # an image counts with its token cost, not with the length of its base64 data
    req = ai.AIRequest(purpose="chat", tier="reasoning", messages=[ai.AIMessage("user", blocks)])
    assert ai.prompt_chars(req) < 60_000
    assert chat_media.content_blocks(settings, "nur Text", []) == "nur Text"


def test_chat_with_files_mock(db: Session, make_user: MakeUser, tmp_path: Any) -> None:
    settings = _settings(tmp_path)
    seed_base_data(db, demo_channels=True)
    user = make_user()
    pdf = chat_media.save(db, settings, user, "a.pdf", "application/pdf", _text_pdf("Sponsor"))
    img = chat_media.save(db, settings, user, "b.png", "image/png", _png(400, 300))
    files = chat_media.claim(db, settings, user, [pdf.id, img.id])

    exchange = assistant.send(db, settings, user, "", attachments=files)

    assert "PDF „a.pdf“ (1 Seite) gelesen" in exchange.answer.text
    assert "Bild „b.png“ (400 × 300) erhalten" in exchange.answer.text
    assert exchange.question.text == "[PDF „a.pdf“ (1 Seite)]\n[Bild „b.png“ (400 × 300)]"
    assert {a.message_id for a in (pdf, img)} == {exchange.question.id}
    with pytest.raises(chat_media.ChatMediaError):  # already sent
        chat_media.claim(db, settings, user, [pdf.id])
    other = make_user(email="other@example.com")
    mine = chat_media.save(db, settings, user, "c.png", "image/png", _png(10, 10))
    with pytest.raises(chat_media.ChatMediaError):  # not theirs
        chat_media.claim(db, settings, other, [mine.id])
    with pytest.raises(chat_media.ChatMediaError):
        chat_media.claim(db, settings, user, list(range(1, settings.chat_max_attachments + 2)))


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **params: Any) -> Any:
        self.calls.append(params)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Das Angebot ist fair.")],
            usage=SimpleNamespace(
                input_tokens=2500,
                output_tokens=20,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
            stop_reason="end_turn",
            model=params["model"],
            _request_id="req_test",
        )


def test_live_chat_sends_image_and_pdf_text(
    db: Session, make_user: MakeUser, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient()
    monkeypatch.setattr(ai, "client_factory", lambda _s: client)
    seed_base_data(db, demo_channels=True)
    update_operations(db, None, {"ai_provider": "claude", "monthly_budget_eur": 50})
    db.flush()
    settings = _settings(
        tmp_path, paid_api_calls_enabled=True, anthropic_api_key=SecretStr("sk-test-not-real")
    )
    user = make_user()
    img = chat_media.save(db, settings, user, "b.png", "image/png", _png(800, 600))
    pdf = chat_media.save(db, settings, user, "a.pdf", "application/pdf", _text_pdf("450 Euro"))

    exchange = assistant.send(db, settings, user, "Lohnt sich das?", attachments=[img, pdf])

    assert exchange.answer.text == "Das Angebot ist fair."
    last = client.calls[0]["messages"][-1]["content"]
    assert last[0]["type"] == "image"
    assert "450 Euro" in last[-1]["text"] and last[-1]["text"].endswith("Lohnt sich das?")


# --- spoken answers ------------------------------------------------------------------


def test_spoken_text_and_browser_fallback(db: Session, make_user: MakeUser) -> None:
    text = "**Fertig.**\n- Montag: Uhren\n- Link: https://example.com/x\n## Ende"
    assert chat_media.spoken_text(text) == "Fertig. Montag: Uhren. Link: Link. Ende"
    assert len(chat_media.spoken_text("Satz. " * 400)) <= chat_media.MAX_SPOKEN_CHARS
    seed_base_data(db, demo_channels=True)
    user = make_user()
    msg = ChatMessage(user_id=user.id, role="assistant", text="Hallo")
    db.add(msg)
    db.flush()
    speech = chat_media.speak(db, get_settings(), msg)  # tts_provider defaults to mock
    assert speech.path is None and speech.provider == "mock"


def test_speak_with_server_voice(
    db: Session, make_user: MakeUser, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real voice provider writes an .m4a once and serves it from the cache after."""
    from decimal import Decimal

    from core.enums import Language
    from services import media, voice

    calls: list[str] = []

    class ToneVoice:
        name = "tone"
        commercial_use_cleared = True
        cost_per_second_eur = Decimal("0")

        def __init__(self, settings: Settings) -> None:
            self.settings = settings
            self.voices = {lang: "tone" for lang in Language}

        def synthesize(self, text: str, language: Any, voice_id: str, out: Any) -> float:
            calls.append(text)
            media.run(
                [self.settings.ffmpeg_bin, "-v", "error", "-y", "-f", "lavfi", "-t", "0.5",
                 "-i", "sine=frequency=440", str(out)],
                timeout=30,
            )  # fmt: skip
            return 0.5

    monkeypatch.setitem(voice.PROVIDERS, "tone", ToneVoice)
    seed_base_data(db, demo_channels=True)
    update_operations(db, None, {"tts_provider": "tone"})
    user = make_user()
    msg = ChatMessage(user_id=user.id, role="assistant", text="Alles erledigt.")
    db.add(msg)
    db.flush()
    settings = _settings(tmp_path)

    first = chat_media.speak(db, settings, msg)
    again = chat_media.speak(db, settings, msg)

    assert first.path is not None and first.path.suffix == ".m4a" and first.path.stat().st_size
    assert again.path == first.path and calls == ["Alles erledigt."]


# --- push ------------------------------------------------------------------------------


class Ntfy:
    def __init__(self, status: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status

    def client(self) -> httpx.Client:
        def handler(req: httpx.Request) -> httpx.Response:
            self.requests.append(req)
            return httpx.Response(self.status, json={"id": "x"})

        return httpx.Client(transport=httpx.MockTransport(handler))


def _live(**update: Any) -> Settings:
    return get_settings().model_copy(
        update={
            "push_mode": "live",
            "push_ntfy_url": SecretStr("https://ntfy.sh/gce-test-topic-123"),
            "push_click_base_url": "https://studio.example.de",
            **update,
        }
    )


def _note(db: Session, title: str, level: NotificationLevel, at: datetime) -> Notification:
    n = notify.add(db, title, f"Text zu {title}", level=level, link="/konten")
    n.created_at = at
    db.flush()
    return n


def test_push_only_important_and_not_twice(db: Session) -> None:
    ntfy = Ntfy()
    info = _note(db, "Nur Info", NotificationLevel.INFO, NOON)
    warn = _note(db, "Reichweite bricht ein: Uhren DE", NotificationLevel.WARNING, NOON)

    result = notify.deliver(db, _live(), NOON, ntfy.client())

    assert result.sent == 1 and result.skipped == 1
    assert (info.push_state, warn.push_state) == ("skipped", "sent")
    req = ntfy.requests[0]
    assert str(req.url) == "https://ntfy.sh/gce-test-topic-123"
    assert req.headers["Priority"] == "3" and req.headers["Click"].endswith("/konten")
    assert req.headers["Title"] == "Reichweite bricht ein: Uhren DE"
    assert req.content.decode() == "Text zu Reichweite bricht ein: Uhren DE"

    again = _note(db, "Reichweite bricht ein: Uhren DE", NotificationLevel.WARNING, NOON)
    notify.deliver(db, _live(), NOON + timedelta(minutes=5), ntfy.client())
    assert again.push_state == "skipped" and len(ntfy.requests) == 1


def test_umlauts_in_title_are_encoded(db: Session) -> None:
    ntfy = Ntfy()
    _note(db, "Rechte- oder Sperrhinweis bei Küche", NotificationLevel.CRITICAL, NOON)
    notify.deliver(db, _live(), NOON, ntfy.client())
    title = ntfy.requests[0].headers["Title"]
    assert title.startswith("=?UTF-8?B?") and ntfy.requests[0].headers["Priority"] == "5"


def test_quiet_hours_wait_except_critical_then_one_summary(db: Session) -> None:
    ntfy = Ntfy()
    for i in range(4):
        _note(db, f"Warnung {i}", NotificationLevel.WARNING, NIGHT)
    crit = _note(db, "Copyright", NotificationLevel.CRITICAL, NIGHT)

    night = notify.deliver(db, _live(), NIGHT, ntfy.client())
    assert night.waiting == 4 and crit.push_state == "sent" and len(ntfy.requests) == 1

    morning = NIGHT.replace(hour=7)  # 08:00 in Berlin
    result = notify.deliver(db, _live(), morning, ntfy.client())
    assert result.combined == 4 and len(ntfy.requests) == 2
    assert ntfy.requests[1].headers["Title"] == "4 neue Hinweise"
    assert "• Warnung 0" in ntfy.requests[1].content.decode()


def test_mock_mode_and_failures_and_stale(db: Session) -> None:
    n = _note(db, "Warnung", NotificationLevel.WARNING, NOON)
    notify.deliver(db, get_settings(), NOON)  # default: mock
    assert n.push_state == "mock"

    broken = Ntfy(status=500)
    f = _note(db, "Andere Warnung", NotificationLevel.WARNING, NOON)
    assert notify.deliver(db, _live(), NOON, broken.client()).failed == 1
    assert f.push_state == "failed"

    old = _note(db, "Alt", NotificationLevel.CRITICAL, NOON - timedelta(days=1))
    notify.deliver(db, _live(), NOON, Ntfy().client())
    assert old.push_state == "skipped"


def test_quiet_hours_helper() -> None:
    s = get_settings()
    assert notify.in_quiet_hours(s, NIGHT)
    assert not notify.in_quiet_hours(s, NOON)
    day_quiet = s.model_copy(update={"push_quiet_start": 9, "push_quiet_end": 17})
    assert notify.in_quiet_hours(day_quiet, NOON)
    off = s.model_copy(update={"push_quiet_start": 0, "push_quiet_end": 0})
    assert not notify.in_quiet_hours(off, NIGHT)


# --- watchdog ------------------------------------------------------------------------


def _channel_with_failed_job(db: Session, error: str) -> Channel:
    chain = build_chain(db)
    ch = db.scalars(select(Channel).where(Channel.platform.has(code=PlatformCode.YOUTUBE))).first()
    assert ch is not None
    chain.variant.channel_id = ch.id
    db.add(
        PublishingJob(
            variant_id=chain.variant.id, channel_id=ch.id, status=PublishingJobStatus.FAILED,
            mode=PublishingMode.MOCK, idempotency_key=f"w-{uuid4().hex}", last_error=error,
        )
    )  # fmt: skip
    db.flush()
    return ch


def test_watchdog_findings_once(db: Session, make_user: MakeUser) -> None:
    ch = _channel_with_failed_job(db, "Video blocked: copyright claim by Example Music")
    ch.auth_status, ch.is_paused = ChannelAuthStatus.EXPIRED, False
    db.add(
        Comment(
            channel_id=ch.id, platform=PlatformCode.YOUTUBE, external_id="c1",
            text="Das ist geklaut", kind=CommentKind.CRITICISM, status=CommentStatus.REVIEW,
        )
    )  # fmt: skip
    db.flush()
    settings = get_settings()

    first = watchdog.scan(db, settings)
    assert any(k.startswith("strike:") for k in first.created)
    assert f"auth:{ch.id}" in first.created
    assert any(k.startswith("comments:") for k in first.created)
    strike = db.scalars(select(Notification).where(Notification.kind == "rights")).one()
    assert strike.level == NotificationLevel.CRITICAL and "copyright" in (strike.body or "")

    assert watchdog.scan(db, settings).created == []  # nothing twice


def test_watchdog_reports_finished_chat_research(db: Session, make_user: MakeUser) -> None:
    seed_base_data(db, demo_channels=True)
    user = make_user()
    msg = ChatMessage(user_id=user.id, role="assistant", text="")
    db.add(msg)
    db.flush()
    action = ChatAction(
        message_id=msg.id, user_id=user.id, tool="start_research",
        args={"project": "Gaming", "jobs": {"research": "j1", "idea_lab": "j2"}},
        summary="Recherche gestartet",
    )  # fmt: skip
    db.add(action)
    db.add(AgentRun(agent_name="research", input={}, queue_job_id="j1",
                    status=AgentRunStatus.SUCCEEDED))  # fmt: skip
    run2 = AgentRun(agent_name="idea_lab", input={}, queue_job_id="j2")
    db.add(run2)
    db.flush()

    assert not [k for k in watchdog.scan(db, get_settings()).created if k.startswith("done:")]
    run2.status = AgentRunStatus.SUCCEEDED
    db.flush()
    assert f"done:{action.id}" in watchdog.scan(db, get_settings()).created
    done = db.scalars(select(Notification).where(Notification.kind == "done")).one()
    assert done.title == "Fertig: Recherche Gaming" and done.link == "/ideen"
    assert watchdog.scan(db, get_settings()).created == []


# --- API -------------------------------------------------------------------------------


def test_api_upload_send_file_speech_and_bell(
    api: TestClient, db: Session, make_user: MakeUser, tmp_path: Any
) -> None:
    seed_base_data(db, demo_channels=True)
    make_user(email="op@example.com", role=UserRole.OPERATOR)
    headers = login(api, "op@example.com")
    api.app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)  # type: ignore[attr-defined]

    r = api.post(
        "/api/assistant/attachments",
        files={"file": ("angebot.pdf", _text_pdf("Kooperation 300 Euro"), "application/pdf")},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    att = r.json()
    assert att["pages"] == 1 and att["has_text"]
    bad = api.post(
        "/api/assistant/attachments",
        files={"file": ("x.gif", b"GIF89a....", "image/gif")},
        headers=headers,
    )
    assert bad.status_code == 422

    assert (
        api.post("/api/assistant/messages", json={"text": "  "}, headers=headers).status_code == 422
    )
    r = api.post(
        "/api/assistant/messages",
        json={"text": "Was steht drin?", "attachment_ids": [att["id"]]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["question"]["attachments"][0]["filename"] == "angebot.pdf"
    assert "Kooperation 300 Euro" in body["answer"]["text"]
    assert "Ich verstehe zum Beispiel" not in body["answer"]["text"]
    history = api.get("/api/assistant/messages").json()
    assert history[-2]["attachments"][0]["id"] == att["id"]

    f = api.get(f"/api/assistant/attachments/{att['id']}/file")
    assert f.status_code == 200 and f.content.startswith(b"%PDF")
    assert f.headers["content-security-policy"] == "sandbox"

    speech = api.get(f"/api/assistant/messages/{body['answer']['id']}/speech")
    assert speech.status_code == 204 and speech.headers["x-voice"] == "browser"
    assert api.get(f"/api/assistant/messages/{body['question']['id']}/speech").status_code == 404

    notify.add(db, "Reichweite bricht ein", level=NotificationLevel.WARNING, link="/konten")
    notify.add(db, "Fertig", level=NotificationLevel.INFO, kind="done")
    db.flush()
    bell = api.get("/api/notifications").json()
    assert bell["unread"] == 2 and bell["items"][0]["title"] == "Fertig"
    first = bell["items"][1]["id"]
    r = api.post("/api/notifications/read", json={"ids": [first]}, headers=headers)
    assert r.json() == {"marked": 1, "unread": 1}
    r = api.post("/api/notifications/read", json={}, headers=headers)
    assert r.json()["unread"] == 0
    push = api.get("/api/notifications/push").json()
    assert push["mode"] == "mock" and push["min_level"] == "warning"
    assert api.post("/api/notifications/push/test", headers=headers).status_code == 403


def test_other_users_files_are_hidden(
    api: TestClient, db: Session, make_user: MakeUser, tmp_path: Any
) -> None:
    owner = make_user(email="a@example.com", role=UserRole.OPERATOR)
    make_user(email="b@example.com", role=UserRole.OPERATOR)
    api.app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)  # type: ignore[attr-defined]
    att = chat_media.save(db, _settings(tmp_path), owner, "x.png", "image/png", _png(20, 20))
    db.flush()
    login(api, "b@example.com")
    assert api.get(f"/api/assistant/attachments/{att.id}/file").status_code == 404
    assert db.scalar(select(ChatAttachment).where(ChatAttachment.id == att.id)) is not None
