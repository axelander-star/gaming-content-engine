"""Cloudflare Workers AI client for channel pictures (HTTP mocked)."""

from __future__ import annotations

import base64
import io
import json

import httpx
import pytest
from PIL import Image
from pydantic import SecretStr

from core.config import Settings, get_settings
from services import branding, image_ai


def _settings(**kw: object) -> Settings:
    base = {
        "image_ai_mode": "cloudflare",
        "cloudflare_ai_account_id": "acc123",
        "cloudflare_ai_token": SecretStr("secret-token"),
    }
    return get_settings().model_copy(update={**base, **kw})


def _jpeg() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (1024, 1024), (200, 40, 90)).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def test_paint_calls_documented_endpoint() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"success": True, "result": {"image": _jpeg()}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        img = image_ai.paint(_settings(), "a lighthouse", client=client)
    assert img.size == (1024, 1024)
    assert seen["url"] == (
        "https://api.cloudflare.com/client/v4/accounts/acc123/ai/run/"
        "@cf/black-forest-labs/flux-1-schnell"
    )
    assert seen["auth"] == "Bearer secret-token"
    assert seen["body"] == {"prompt": "a lighthouse", "steps": 8}


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        (429, {"success": False, "errors": [{"message": "Too many"}]}, "Tageskontingent"),
        (
            400,
            {
                "success": False,
                "errors": [
                    {"message": "you have used up your daily free allocation of 10,000 neurons"}
                ],
            },
            "Tageskontingent",
        ),
        (401, {"success": False, "errors": [{"message": "Authentication error"}]}, "401"),
        (200, {"success": True, "result": {}}, "kein Bild"),
        (200, {"success": True, "result": {"image": "!!notbase64"}}, "unlesbar"),
    ],
)
def test_paint_errors(status: int, payload: dict[str, object], expected: str) -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(status, json=payload))
    with httpx.Client(transport=transport) as client, pytest.raises(image_ai.ImageAIError) as err:
        image_ai.paint(_settings(), "x", client=client)
    assert expected in str(err.value)


def test_not_set_up() -> None:
    assert not image_ai.available(_settings(image_ai_mode="off"))
    assert not image_ai.available(_settings(cloudflare_ai_token=SecretStr("")))
    with pytest.raises(image_ai.ImageAIError):
        image_ai.paint(_settings(image_ai_mode="off"), "x")


def test_design_is_shared_and_changes_with_seed() -> None:
    a = image_ai.design("light bulbs", "fakten-1", branding.palette("fakten-1"))
    assert a.style in a.avatar_prompt() and a.style in a.banner_prompt()
    assert a.colours in a.avatar_prompt() and a.colours in a.banner_prompt()
    styles = {image_ai.design("x", f"s{i}", ((10, 200, 30),)).style for i in range(30)}
    assert len(styles) > 2


def test_art_compositions() -> None:
    art = Image.new("RGB", (1024, 1024), (30, 60, 200))
    avatar = Image.open(io.BytesIO(branding.avatar_from_art(art)))
    banner = Image.open(io.BytesIO(branding.banner_from_art(art, "Krasse Fakten", "Jeden Tag")))
    assert avatar.size == branding.AVATAR_SIZE
    assert banner.size == branding.BANNER_SIZE
    # the name is drawn: the centre is brighter than the plain artwork
    centre = banner.convert("L").crop((1000, 560, 1560, 700))
    assert max(centre.getextrema()) > 200  # type: ignore[operator]
