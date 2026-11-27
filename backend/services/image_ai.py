"""AI pictures for new channels: one style for profile picture and banner.

Provider: Cloudflare Workers AI (official REST API, documented at
https://developers.cloudflare.com/workers-ai/models/flux-1-schnell/)::

    POST https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}
    Authorization: Bearer <token>
    {"prompt": "...", "steps": 8}
    -> {"result": {"image": "<base64 JPEG>"}, "success": true}

The Workers Free plan includes a daily free allowance; when it is used up the API
answers with an error and nothing is charged. Every failure raises
:class:`ImageAIError`, and the caller falls back to the locally drawn pictures.

The model paints only the artwork. Channel name and tagline are set afterwards
as real text (see :mod:`services.branding`), because image models misspell words.
"""

from __future__ import annotations

import base64
import binascii
import colorsys
import hashlib
import io
import logging
from dataclasses import dataclass

import httpx
from PIL import Image, UnidentifiedImageError

from core.config import Settings

log = logging.getLogger(__name__)

API_BASE = "https://api.cloudflare.com/client/v4"

#: Art directions; the seed picks one so every "new design" click looks different,
#: while profile picture and banner of one design always share it.
STYLES = (
    "bold modern 3D render, glossy materials, soft studio lighting, high contrast",
    "cinematic digital painting, dramatic rim light, volumetric atmosphere, rich detail",
    "clean flat vector illustration, geometric shapes, crisp edges, minimal and premium",
    "neon synthwave look, glowing outlines, dark background, vibrant highlights",
    "playful pop-art illustration, thick outlines, halftone texture, punchy colours",
    "isometric 3D scene, miniature diorama, smooth pastel lighting, tidy composition",
)


class ImageAIError(RuntimeError):
    """The image model could not deliver a picture (not set up, quota, network, ...)."""


@dataclass(frozen=True)
class Design:
    """What both pictures of one channel share."""

    subject: str
    style: str
    colours: str

    def avatar_prompt(self) -> str:
        return (
            f"Iconic emblem for a social media channel about {self.subject}. One single bold "
            f"central motif, simple silhouette that reads at small size, centered with space "
            f"around it. {self.style}. Colour palette: {self.colours}. "
            "Square composition, professional brand logo quality. "
            "No text, no letters, no words, no watermark."
        )

    def banner_prompt(self) -> str:
        return (
            f"Wide cinematic header artwork for a social media channel about {self.subject}. "
            f"Scene elements on the left and right edges, calm darker empty area in the "
            f"middle. {self.style}. Colour palette: {self.colours}. "
            "Professional brand key visual. No text, no letters, no words, no watermark."
        )


def hue_name(rgb: tuple[int, int, int]) -> str:
    h, light, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    if s < 0.15:
        return "graphite grey"
    names = (
        (0.04, "crimson red"),
        (0.10, "orange"),
        (0.17, "golden yellow"),
        (0.25, "lime green"),
        (0.40, "emerald green"),
        (0.50, "teal"),
        (0.58, "cyan blue"),
        (0.68, "royal blue"),
        (0.78, "violet"),
        (0.88, "magenta"),
        (0.96, "pink"),
        (1.01, "crimson red"),
    )
    name = next(n for limit, n in names if h < limit)
    return f"deep {name}" if light < 0.3 else name


def design(subject: str, seed: str, colours: tuple[tuple[int, int, int], ...]) -> Design:
    """Style and colours for one look; same seed -> same design."""
    idx = int(hashlib.sha256(f"style:{seed.casefold()}".encode()).hexdigest()[:6], 16)
    names = list(dict.fromkeys(hue_name(c) for c in colours))
    return Design(
        subject=subject.strip() or "short videos",
        style=STYLES[idx % len(STYLES)],
        colours=" and ".join(names) + " accents",
    )


def available(settings: Settings) -> bool:
    return (
        settings.image_ai_mode == "cloudflare"
        and bool(settings.cloudflare_ai_account_id)
        and bool(settings.cloudflare_ai_token.get_secret_value())
    )


def paint(settings: Settings, prompt: str, client: httpx.Client | None = None) -> Image.Image:
    """One square picture (about 1024 x 1024) from the image model."""
    if not available(settings):
        raise ImageAIError("Bild-KI ist nicht eingerichtet (IMAGE_AI_MODE=cloudflare + Token).")
    url = (
        f"{API_BASE}/accounts/{settings.cloudflare_ai_account_id}/ai/run/{settings.image_ai_model}"
    )
    body: dict[str, object] = {"prompt": prompt[:2048], "steps": settings.image_ai_steps}
    own = client is None
    http = client or httpx.Client(timeout=settings.image_ai_timeout_s)
    try:
        res = http.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {settings.cloudflare_ai_token.get_secret_value()}"},
        )
    except httpx.HTTPError as exc:
        raise ImageAIError(f"Bild-KI nicht erreichbar ({type(exc).__name__}).") from exc
    finally:
        if own:
            http.close()
    try:
        data = res.json()
    except ValueError:
        data = {}
    if res.status_code >= 400 or not data.get("success", res.status_code < 400):
        errors = data.get("errors") if isinstance(data, dict) else None
        msg = ""
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            msg = str(errors[0].get("message") or "")
        if res.status_code == 429 or "neuron" in msg.casefold():
            raise ImageAIError("Das kostenlose Tageskontingent der Bild-KI ist aufgebraucht.")
        raise ImageAIError(f"Bild-KI meldet Fehler {res.status_code}: {msg[:160]}".rstrip(": "))
    result = data.get("result") if isinstance(data, dict) else None
    b64 = result.get("image") if isinstance(result, dict) else None
    if not isinstance(b64, str) or not b64:
        raise ImageAIError("Bild-KI hat kein Bild geliefert.")
    try:
        img = Image.open(io.BytesIO(base64.b64decode(b64)))
        img.load()
    except (binascii.Error, UnidentifiedImageError, OSError) as exc:
        raise ImageAIError("Bild-KI hat ein unlesbares Bild geliefert.") from exc
    log.info("image ai: %s, %sx%s", settings.image_ai_model, img.width, img.height)
    return img.convert("RGB")
