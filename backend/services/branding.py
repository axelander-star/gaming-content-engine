"""Profile pictures and banners for new channels, drawn locally with Pillow (no paid AI).

Sizes follow the platforms' published recommendations:

* profile picture 800 x 800 px (YouTube recommends 800 x 800; TikTok and Instagram
  crop the same square to a circle, so the initials stay inside the circle);
* YouTube banner 2560 x 1440 px with all text inside the 1546 x 423 px safe area
  that every device shows.

Colours come from the topic area's name, so all channels of one topic share a look
and different topics are easy to tell apart.
"""

from __future__ import annotations

import colorsys
import hashlib
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core.config import Settings
from services import storage

AVATAR_SIZE = (800, 800)
BANNER_SIZE = (2560, 1440)
BANNER_SAFE = (1546, 423)

_FONT_DIRS = (
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/dejavu"),
)

Font = ImageFont.FreeTypeFont | ImageFont.ImageFont


def _font(size: int, bold: bool = True) -> Font:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for folder in _FONT_DIRS:
        path = folder / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def palette(seed: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Two related, saturated colours derived from ``seed`` (stable across runs)."""
    h = int(hashlib.sha256(seed.casefold().encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    a = colorsys.hls_to_rgb(h, 0.38, 0.70)
    b = colorsys.hls_to_rgb((h + 0.08) % 1.0, 0.22, 0.65)
    return (
        (round(a[0] * 255), round(a[1] * 255), round(a[2] * 255)),
        (round(b[0] * 255), round(b[1] * 255), round(b[2] * 255)),
    )


def _gradient(
    size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]
) -> Image.Image:
    w, h = size
    column = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        column.putpixel((0, y), tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return column.resize((w, h))


def initials(name: str) -> str:
    words = [w for w in "".join(c if c.isalnum() else " " for c in name).split() if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def _fit(draw: ImageDraw.ImageDraw, text: str, max_w: int, max_h: int, start: int) -> Font:
    size = start
    while size > 12:
        font = _font(size)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_w and box[3] - box[1] <= max_h:
            return font
        size -= 4
    return _font(12)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def avatar_png(name: str, seed: str) -> bytes:
    a, b = palette(seed)
    img = _gradient(AVATAR_SIZE, a, b)
    draw = ImageDraw.Draw(img)
    text = initials(name)
    # inside the inscribed circle: a square of side ~ 0.7 * diameter is always visible
    font = _fit(draw, text, int(AVATAR_SIZE[0] * 0.55), int(AVATAR_SIZE[1] * 0.45), 420)
    draw.text((AVATAR_SIZE[0] / 2, AVATAR_SIZE[1] / 2), text, font=font, fill="white", anchor="mm")
    return _png(img)


def banner_png(title: str, tagline: str, seed: str) -> bytes:
    a, b = palette(seed)
    img = _gradient(BANNER_SIZE, b, a)
    draw = ImageDraw.Draw(img)
    cx, cy = BANNER_SIZE[0] / 2, BANNER_SIZE[1] / 2
    safe_w, safe_h = BANNER_SAFE
    title_font = _fit(draw, title, int(safe_w * 0.92), int(safe_h * 0.5), 200)
    draw.text((cx, cy - safe_h * 0.12), title, font=title_font, fill="white", anchor="mm")
    if tagline:
        tag_font = _fit(draw, tagline, int(safe_w * 0.92), int(safe_h * 0.2), 72)
        draw.text(
            (cx, cy + safe_h * 0.28), tagline, font=tag_font, fill=(235, 235, 235), anchor="mm"
        )
    return _png(img)


def store_png(settings: Settings, data: bytes, folder: str = "channel-setup") -> str:
    return storage.store_document(settings, data, "image/png", folder).uri
