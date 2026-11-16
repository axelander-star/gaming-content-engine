"""Channel assistant: coverage, prepared tasks, images, forwarding addresses, completion."""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import (
    ChannelAuthStatus,
    ChannelSetupStatus,
    Language,
    MailAliasStatus,
    PlatformCode,
    UserRole,
)
from models import Channel, ChannelSetupTask, ContentProject, Platform
from models.access import AuditLog, User
from services import ai, branding, channel_setup, mail_alias
from services.seed import seed_base_data
from tests.conftest import login

pytestmark = pytest.mark.integration

MakeUser = Callable[..., User]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(
        update={"media_root": str(tmp_path / "media"), "mail_alias_domain": "kanalfabrik.de"}
    )


@pytest.fixture
def client(api: TestClient, settings: Settings) -> Iterator[TestClient]:
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    yield api


def watches(db: Session, languages: tuple[str, ...] = ("de", "en")) -> ContentProject:
    seed_base_data(db)
    project = ContentProject(slug="uhren", name="Uhren", languages=list(languages))
    db.add(project)
    db.flush()
    return project


def add_channel(
    db: Session,
    project: ContentProject,
    code: PlatformCode,
    language: Language,
    auth: ChannelAuthStatus = ChannelAuthStatus.AUTHORIZED,
) -> Channel:
    plat = db.scalar(select(Platform).where(Platform.code == code))
    assert plat is not None
    channel = Channel(
        platform_id=plat.id,
        content_project_id=project.id,
        language=language,
        name=f"{code.value} {project.name} {language.value}",
        auth_status=auth,
    )
    db.add(channel)
    db.flush()
    return channel


# --- rules and texts --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "platform", "expected"),
    [
        ("Uhren Kompakt", PlatformCode.TIKTOK, "uhren_kompakt"),
        ("@Grüße.aus..Köln", PlatformCode.INSTAGRAM, "gruesse.aus.koeln"),
        ("Uhren-Welt!", PlatformCode.YOUTUBE, "uhren-welt"),
        ("x", PlatformCode.YOUTUBE, "xkanal"),
        ("a" * 40, PlatformCode.TIKTOK, "a" * 24),
    ],
)
def test_handles_follow_platform_rules(raw: str, platform: PlatformCode, expected: str) -> None:
    assert channel_setup.normalize_handle(raw, platform) == expected


def test_template_texts_fit_every_platform(db: Session) -> None:
    project = watches(db)
    for code, rules in channel_setup.RULES.items():
        for lang in (Language.DE, Language.EN):
            texts = channel_setup.template_texts(project, code, lang)
            assert texts.display_name and texts.bio
            handle = channel_setup.normalize_handle(texts.handles[0], code)
            assert rules.handle_min <= len(handle) <= rules.handle_max
    assert "Uhren" in channel_setup.template_texts(project, PlatformCode.TIKTOK, Language.DE).bio


def test_images_have_platform_sizes() -> None:
    avatar = Image.open(io.BytesIO(branding.avatar_png("Uhren Kompakt", "uhren")))
    banner = Image.open(io.BytesIO(branding.banner_png("Uhren Kompakt", "Kurz erklärt", "uhren")))
    assert avatar.size == branding.AVATAR_SIZE
    assert banner.size == branding.BANNER_SIZE
    assert branding.initials("Uhren Kompakt") == "UK"
    assert branding.palette("uhren") == branding.palette("UHREN")
    assert branding.palette("uhren") != branding.palette("mode")


# --- coverage and prepare -----------------------------------------------------------------


def test_coverage_shows_missing_added_and_connected(db: Session) -> None:
    project = watches(db)
    add_channel(db, project, PlatformCode.YOUTUBE, Language.DE)
    add_channel(db, project, PlatformCode.TIKTOK, Language.DE, ChannelAuthStatus.NOT_CONNECTED)
    states = {(s.platform, s.language): s.state for s in channel_setup.coverage(db, project).slots}
    assert len(states) == 6
    assert states[(PlatformCode.YOUTUBE, Language.DE)] == "connected"
    assert states[(PlatformCode.TIKTOK, Language.DE)] == "added"
    assert states[(PlatformCode.INSTAGRAM, Language.EN)] == "missing"


def test_prepare_creates_one_task_per_missing_channel(db: Session, settings: Settings) -> None:
    project = watches(db)
    add_channel(db, project, PlatformCode.YOUTUBE, Language.DE)
    tasks = channel_setup.prepare(db, settings, project)
    assert len(tasks) == 5
    by_key = {(t.platform, t.language): t for t in tasks}

    yt = by_key[(PlatformCode.YOUTUBE, Language.EN)]
    assert yt.email is None and yt.email_status == MailAliasStatus.NOT_NEEDED
    assert yt.avatar_uri and yt.banner_uri

    tt = by_key[(PlatformCode.TIKTOK, Language.DE)]
    assert tt.email == "uhren-de-tiktok@kanalfabrik.de"
    assert tt.email_status == MailAliasStatus.MOCK  # test mode: nothing created at Cloudflare
    assert tt.banner_uri is None and tt.avatar_uri
    assert len(tt.bio) <= channel_setup.RULES[PlatformCode.TIKTOK].bio_max
    assert tt.handle and tt.alt_handles
    assert tt.handle_check == dict.fromkeys([tt.handle, *tt.alt_handles], "unknown")

    ig = by_key[(PlatformCode.INSTAGRAM, Language.EN)]
    assert ig.email == "uhren-en-instagram@kanalfabrik.de"

    # idempotent: nothing missing any more
    assert channel_setup.prepare(db, settings, project) == []
    states = {s.state for s in channel_setup.coverage(db, project).slots}
    assert states == {"connected", "prepared"}


def test_prepare_without_mail_domain_still_works(db: Session, settings: Settings) -> None:
    project = watches(db, ("de",))
    no_domain = settings.model_copy(update={"mail_alias_domain": ""})
    tasks = channel_setup.prepare(db, no_domain, project, platforms=[PlatformCode.TIKTOK])
    assert len(tasks) == 1
    assert tasks[0].email is None and tasks[0].email_status == MailAliasStatus.MOCK
    assert tasks[0].email_error and "MAIL_ALIAS_DOMAIN" in tasks[0].email_error


def test_ai_answer_is_used_and_cleaned(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = watches(db, ("en",))
    answer = json.dumps(
        {
            "display_name": "Wrist Notes",
            "handles": ["Wrist Notes!", "wristnotes", "wrist.notes.daily"],
            "bio": "Watches explained in a minute. " * 10,
            "tagline": "Watches in a minute",
        }
    )

    def fake_generate(_s: Session, _st: Settings, req: object) -> object:
        class R:
            text = answer
            provider = "claude"

        return R()

    monkeypatch.setattr(ai, "generate", fake_generate)
    [task] = channel_setup.prepare(db, settings, project, platforms=[PlatformCode.INSTAGRAM])
    assert task.display_name == "Wrist Notes"
    assert task.handle == "wrist_notes"
    assert task.alt_handles == ["wristnotes", "wrist.notes.daily"]
    assert len(task.bio) <= 150 and task.bio.endswith("…")
    assert task.text_source == "claude"


def test_ai_failure_falls_back_to_template(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = watches(db, ("de",))

    def blocked(*_a: object, **_k: object) -> object:
        raise ai.AIBlockedError("cap", "Monatsgrenze erreicht")

    monkeypatch.setattr(ai, "generate", blocked)
    [task] = channel_setup.prepare(db, settings, project, platforms=[PlatformCode.YOUTUBE])
    assert task.text_source == "template" and task.display_name == "Uhren Kompakt"


# --- handle check and mail routing (HTTP mocked) -----------------------------------------


def test_youtube_handle_check_uses_official_api(settings: Settings) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        taken = request.url.params["forHandle"] == "@uhrenkompakt"
        return httpx.Response(200, json={"items": [{"id": "UC1"}] if taken else []})

    live = settings.model_copy(
        update={"trend_sources_mode": "live", "youtube_api_key": SecretStr("test-key")}
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = channel_setup.check_handles(
        live, PlatformCode.YOUTUBE, ["uhrenkompakt", "uhren.kurz"], client
    )
    assert result == {"uhrenkompakt": "taken", "uhren.kurz": "free"}
    assert calls[0].url.path == "/youtube/v3/channels"
    # no official API for TikTok: never a request
    assert channel_setup.check_handles(live, PlatformCode.TIKTOK, ["x"], client) == {"x": "unknown"}
    assert len(calls) == 2
    # mock mode: no request at all
    assert channel_setup.check_handles(settings, PlatformCode.YOUTUBE, ["y"]) == {"y": "unknown"}


def live_mail(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "mail_routing_mode": "live",
            "mail_forward_to": "inbox@example.com",
            "cloudflare_zone_id": "zone123",
            "cloudflare_api_token": SecretStr("token"),
        }
    )


def test_mail_alias_live_creates_cloudflare_rule(settings: Settings) -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/client/v4/zones/zone123/email/routing/rules"
        assert request.headers["Authorization"] == "Bearer token"
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"success": True, "result": {"id": "rule-1"}})

    client = httpx.Client(base_url=mail_alias.API, transport=httpx.MockTransport(handler))
    res = mail_alias.create(live_mail(settings), "uhren-de-tiktok", "Uhren", client)
    assert res.status == MailAliasStatus.CREATED and res.rule_id == "rule-1"
    assert res.address == "uhren-de-tiktok@kanalfabrik.de"
    body = seen[0]
    assert body["matchers"] == [
        {"type": "literal", "field": "to", "value": "uhren-de-tiktok@kanalfabrik.de"}
    ]
    assert body["actions"] == [{"type": "forward", "value": ["inbox@example.com"]}]


def test_mail_alias_errors_are_reported(settings: Settings) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"success": False, "errors": [{"message": "destination not verified"}]}
        )

    client = httpx.Client(base_url=mail_alias.API, transport=httpx.MockTransport(handler))
    res = mail_alias.create(live_mail(settings), "uhren-de-tiktok", "Uhren", client)
    assert res.status == MailAliasStatus.FAILED
    assert res.error and "destination not verified" in res.error
    # live without token: clear message, no request
    incomplete = live_mail(settings).model_copy(update={"cloudflare_api_token": SecretStr("")})
    res = mail_alias.create(incomplete, "uhren-de-tiktok", "Uhren")
    assert res.status == MailAliasStatus.FAILED and "CLOUDFLARE_API_TOKEN" in (res.error or "")


# --- API -----------------------------------------------------------------------------------


def test_api_flow_prepare_edit_complete(
    client: TestClient, db: Session, make_user: MakeUser
) -> None:
    project = watches(db, ("de",))
    make_user()
    headers = login(client, "admin@example.com")

    r = client.get("/api/channel-setup/coverage")
    assert r.status_code == 200
    mine = next(c for c in r.json() if c["project"] == "Uhren")
    assert mine["missing"] == 3

    r = client.post("/api/channel-setup/prepare", json={"project_id": project.id}, headers=headers)
    assert r.status_code == 201, r.text
    tasks = r.json()
    assert {t["platform"] for t in tasks} == {"youtube", "tiktok", "instagram"}
    ig = next(t for t in tasks if t["platform"] == "instagram")
    assert ig["signup_url"].startswith("https://www.instagram.com/")
    assert any("professionell" in s for s in ig["steps"])
    assert ig["has_avatar"] and not ig["has_banner"]

    r = client.get(f"/api/channel-setup/tasks/{ig['id']}/avatar.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert client.get(f"/api/channel-setup/tasks/{ig['id']}/banner.png").status_code == 404

    r = client.patch(
        f"/api/channel-setup/tasks/{ig['id']}",
        json={"display_name": "Zeitzeugen", "handle": "Zeit Zeugen", "bio": "Uhren, kurz erklärt."},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["handle"] == "zeit_zeugen" and r.json()["display_name"] == "Zeitzeugen"

    r = client.post(
        f"/api/channel-setup/tasks/{ig['id']}/complete",
        json={"handle": "zeitzeugen.de"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    channel = db.get(Channel, r.json()["channel_id"])
    assert channel is not None
    assert channel.content_project_id == project.id
    assert channel.is_paused and channel.max_posts_per_day == 0
    assert channel.auth_status == ChannelAuthStatus.NOT_CONNECTED
    assert channel.description == "Uhren, kurz erklärt."
    assert channel.strategy["handle"] == "zeitzeugen.de"
    assert r.json()["task"]["status"] == "done"

    # finished tasks cannot be changed
    again = client.post(f"/api/channel-setup/tasks/{ig['id']}/complete", json={}, headers=headers)
    assert again.status_code == 422

    yt = next(t for t in tasks if t["platform"] == "youtube")
    r = client.post(f"/api/channel-setup/tasks/{yt['id']}/dismiss", headers=headers)
    assert r.json()["status"] == "dismissed"
    open_ids = [t["id"] for t in client.get("/api/channel-setup/tasks").json()]
    assert open_ids == [next(t["id"] for t in tasks if t["platform"] == "tiktok")]
    assert client.get("/api/channel-setup/tasks?state=done").json()[0]["id"] == ig["id"]

    actions = set(db.scalars(select(AuditLog.action)))
    assert {"channel_setup.prepare", "channel_setup.complete", "channel_setup.dismiss"} <= actions
    assert (
        db.scalar(select(ChannelSetupTask.status).where(ChannelSetupTask.id == yt["id"]))
        == ChannelSetupStatus.DISMISSED
    )


def test_api_needs_admin_for_changes(client: TestClient, db: Session, make_user: MakeUser) -> None:
    project = watches(db, ("de",))
    make_user(email="viewer@example.com", role=UserRole.VIEWER)
    headers = login(client, "viewer@example.com")
    assert client.get("/api/channel-setup/coverage").status_code == 200
    r = client.post("/api/channel-setup/prepare", json={"project_id": project.id}, headers=headers)
    assert r.status_code == 403
    assert client.get("/api/channel-setup/mail").json()["mode"] == "mock"
