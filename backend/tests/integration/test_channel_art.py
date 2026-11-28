"""AI pictures in the channel assistant (image AI mocked, no network)."""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import SecretStr
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from models import ContentProject
from services import ai, image_ai
from services.seed import seed_base_data
from tests.conftest import login

pytestmark = pytest.mark.integration


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(
        update={
            "media_root": str(tmp_path / "media"),
            "trend_sources_mode": "mock",
            "image_ai_mode": "cloudflare",
            "cloudflare_ai_account_id": "acc",
            "cloudflare_ai_token": SecretStr("tok"),
        }
    )


@pytest.fixture(autouse=True)
def text_ai(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Cloudflare text model (used by the assistant once Cloudflare is set up): mocked;
    it is down here, so texts and motif come from the templates."""
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(503, json={"success": False, "errors": [{"message": "down"}]})

    monkeypatch.setattr(
        ai, "http_client_factory", lambda _s: httpx.Client(transport=httpx.MockTransport(handler))
    )
    return seen


def test_pictures_from_image_ai(
    api: TestClient,
    db: Session,
    settings: Settings,
    make_user: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_base_data(db)
    project = ContentProject(
        slug="fakten", name="Krasse Fakten", languages=["de"], subtopics=["Rekorde"]
    )
    db.add(project)
    db.commit()
    prompts: list[str] = []
    colours = iter(range(10, 250, 7))

    def fake_paint(_settings: Settings, prompt: str, client: object = None) -> Image.Image:
        prompts.append(prompt)
        return Image.new("RGB", (1024, 1024), (next(colours), 80, 120))

    monkeypatch.setattr(image_ai, "paint", fake_paint)
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    make_user()  # type: ignore[operator]
    headers = login(api, "admin@example.com")
    r = api.post("/api/channel-setup/prepare", json={"project_id": project.id}, headers=headers)
    assert r.status_code == 201, r.text
    task = next(t for t in r.json() if t["platform"] == "youtube")
    assert task["image_source"] == "ai" and task["image_note"] is None
    # one style for both: logo prompt and banner prompt share style and colours
    i = next(i for i, p in enumerate(prompts) if "header artwork" in p)
    yt_prompts = prompts[i - 1 : i + 1]
    assert "emblem" in yt_prompts[0] and "header artwork" in yt_prompts[1]
    style = image_ai.STYLES
    assert [s for s in style if s in yt_prompts[0]] == [s for s in style if s in yt_prompts[1]]
    assert all("No text" in p for p in yt_prompts)
    base = f"/api/channel-setup/tasks/{task['id']}"
    banner = api.get(f"{base}/banner.png", headers=headers)
    assert banner.status_code == 200
    assert Image.open(__import__("io").BytesIO(banner.content)).size == (2560, 1440)

    # a new name gets new pictures that fit it (motif and lettering)
    painted = len(prompts)
    r = api.post(f"{base}/research?part=name", headers=headers)
    assert r.status_code == 200, r.text
    assert len(prompts) == painted + 2
    assert api.get(f"{base}/banner.png", headers=headers).content != banner.content
    painted = len(prompts)

    # the pictures symbol paints both anew
    r = api.post(f"{base}/research?part=images", headers=headers)
    assert r.json()["image_source"] == "ai"
    assert len(prompts) == painted + 2

    # AI down or allowance used up: drawn locally, with a note, never blocked
    def broken(_settings: Settings, prompt: str, client: object = None) -> Image.Image:
        raise image_ai.ImageAIError("Das kostenlose Tageskontingent der Bild-KI ist aufgebraucht.")

    monkeypatch.setattr(image_ai, "paint", broken)
    r = api.post(f"{base}/research?part=images", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["image_source"] == "local"
    assert "Tageskontingent" in r.json()["image_note"]
    assert api.get(f"{base}/avatar.png", headers=headers).status_code == 200


def _png_bytes(size: tuple[int, int], colour: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, "PNG")
    return buf.getvalue()


def test_own_pictures_upload(
    api: TestClient, db: Session, tmp_path: Path, make_user: object
) -> None:
    seed_base_data(db)
    project = ContentProject(slug="fakten2", name="Krasse Fakten", languages=["de"])
    db.add(project)
    db.commit()
    local = get_settings().model_copy(
        update={"media_root": str(tmp_path / "media"), "trend_sources_mode": "mock"}
    )
    api.app.dependency_overrides[get_settings] = lambda: local  # type: ignore[attr-defined]
    make_user()  # type: ignore[operator]
    headers = login(api, "admin@example.com")
    tasks = api.post(
        "/api/channel-setup/prepare", json={"project_id": project.id}, headers=headers
    ).json()
    yt = next(t for t in tasks if t["platform"] == "youtube")
    ig = next(t for t in tasks if t["platform"] == "instagram")
    base = f"/api/channel-setup/tasks/{yt['id']}"

    # a small square avatar is accepted with a hint and cut to 800 x 800
    r = api.post(
        f"{base}/upload/avatar",
        files={"file": ("logo.png", _png_bytes((300, 300), (250, 10, 10)), "image/png")},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert "300 × 300" in r.json()["hint"]
    assert r.json()["task"]["uploaded"] == ["avatar"]
    avatar = Image.open(io.BytesIO(api.get(f"{base}/avatar.png", headers=headers).content))
    assert avatar.size == (800, 800) and avatar.getpixel((400, 400)) == (250, 10, 10)

    # a banner in another ratio is cut to 2560 x 1440 without a hint
    r = api.post(
        f"{base}/upload/banner",
        files={"file": ("b.png", _png_bytes((3000, 3000), (10, 250, 10)), "image/png")},
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["hint"] is None
    banner = Image.open(io.BytesIO(api.get(f"{base}/banner.png", headers=headers).content))
    assert banner.size == (2560, 1440)

    # renaming keeps the own pictures
    r = api.patch(base, json={"display_name": "Hirnfutter"}, headers=headers)
    assert r.status_code == 200, r.text
    again = Image.open(io.BytesIO(api.get(f"{base}/avatar.png", headers=headers).content))
    assert again.getpixel((400, 400)) == (250, 10, 10)

    # the pictures AI symbol replaces them on purpose
    r = api.post(f"{base}/research?part=images", headers=headers)
    assert r.json()["uploaded"] == []

    # not an image; Instagram takes a banner (cover photo of its Facebook Page)
    r = api.post(
        f"{base}/upload/avatar", files={"file": ("x.png", b"hello", "image/png")}, headers=headers
    )
    assert r.status_code == 422
    r = api.post(
        f"/api/channel-setup/tasks/{ig['id']}/upload/banner",
        files={"file": ("b.png", _png_bytes((2560, 1440), (0, 0, 0)), "image/png")},
        headers=headers,
    )
    assert r.status_code == 200, r.text


def test_idea_chat_builds_everything_on_the_idea(
    api: TestClient,
    db: Session,
    settings: Settings,
    make_user: object,
    monkeypatch: pytest.MonkeyPatch,
    text_ai: list[httpx.Request],
) -> None:
    seed_base_data(db)
    project = ContentProject(slug="schock", name="Unterhaltung", languages=["de"])
    db.add(project)
    db.commit()
    prompts: list[str] = []

    def fake_paint(_settings: Settings, prompt: str, client: object = None) -> Image.Image:
        prompts.append(prompt)
        return Image.new("RGB", (1024, 1024), (40, 40, 40))

    monkeypatch.setattr(image_ai, "paint", fake_paint)
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    make_user()  # type: ignore[operator]
    headers = login(api, "admin@example.com")
    tasks = api.post(
        "/api/channel-setup/prepare", json={"project_id": project.id}, headers=headers
    ).json()
    yt = next(t for t in tasks if t["platform"] == "youtube")
    base = f"/api/channel-setup/tasks/{yt['id']}"
    assert yt["chat"] == []

    # text plus a red picture and a text file as inspiration
    painted = len(prompts)
    r = api.post(
        f"{base}/chat",
        data={"text": "Schockierte Gesichter, frech und laut"},
        files=[
            ("files", ("mood.png", _png_bytes((64, 64), (230, 20, 20)), "image/png")),
            ("files", ("notizen.txt", b"Name mit Blitz", "text/plain")),
        ],
        headers=headers,
    )
    assert r.status_code == 200, r.text
    task = r.json()
    assert [e["role"] for e in task["chat"]] == ["user", "assistant"]
    assert task["chat"][0]["files"] == ["mood.png", "notizen.txt"]
    assert task["display_name"] in task["chat"][1]["text"]
    assert len(prompts) == painted + 2
    assert "red" in prompts[-1]  # colour mood of the picture
    # the free text model got the idea, including the text file
    sent = [req.content.decode() for req in text_ai]
    assert any("Schockierte Gesichter" in c and "Name mit Blitz" in c for c in sent)

    # "other variant" symbol: same idea, new bio; the plain AI symbol leaves it out
    before = len(text_ai)
    r = api.post(f"{base}/research?part=bio&use_chat=true", headers=headers)
    assert r.status_code == 200, r.text
    assert "Schockierte Gesichter" in text_ai[before].content.decode()
    before = len(text_ai)
    api.post(f"{base}/research?part=bio", headers=headers)
    assert "Schockierte Gesichter" not in text_ai[before].content.decode()

    # empty message and unreadable file are refused, clearing works
    assert api.post(f"{base}/chat", data={"text": " "}, headers=headers).status_code == 422
    r = api.post(
        f"{base}/chat",
        files=[("files", ("x.bin", bytes(range(256)) * 8, "application/octet-stream"))],
        headers=headers,
    )
    assert r.status_code == 422
    r = api.delete(f"{base}/chat", headers=headers)
    assert r.status_code == 200 and r.json()["chat"] == []
