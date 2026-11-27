"""Profile pictures and banners for new channels.

With the image AI (:mod:`services.image_ai`) the model paints the artwork and this
module crops it and sets the channel name as real text. Without it (or when the AI
fails) the pictures are drawn locally with Pillow: gradient, pattern and initials.

Sizes follow the platforms' published recommendations:

* profile picture 800 x 800 px (YouTube recommends 800 x 800; TikTok and Instagram
  crop the same square to a circle, so the initials stay inside the circle);
* YouTube banner 2560 x 1440 px with all text inside the 1546 x 423 px safe area
  that every device shows.

Colours come from the topic area's name, so all channels of one topic share a look
and different topics are easy to tell apart. The AI symbol for the pictures passes a
new seed, which gives another colour pair and another pattern.
"""

from __future__ import annotations

import colorsys
import hashlib
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

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


PATTERNS = 4


def pattern_of(seed: str) -> int:
    return int(hashlib.sha256(f"pattern:{seed.casefold()}".encode()).hexdigest()[:4], 16) % PATTERNS


def _decorate(img: Image.Image, seed: str) -> None:
    """Soft shapes over the gradient so pictures do not look flat (0 = plain)."""
    kind = pattern_of(seed)
    if kind == 0:
        return
    w, h = img.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    unit = min(w, h)
    if kind == 1:  # large circles in the corners
        for cx, cy, r in ((0, 0, 0.55), (w, h, 0.7), (w, 0, 0.3)):
            rad = unit * r
            draw.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=(255, 255, 255, 28))
    elif kind == 2:  # diagonal stripes
        step = max(unit // 8, 40)
        for x in range(-h, w + h, step * 2):
            draw.polygon(
                [(x, 0), (x + step, 0), (x + step - h, h), (x - h, h)], fill=(255, 255, 255, 18)
            )
    else:  # dot grid
        step = max(unit // 12, 30)
        dot = max(step // 7, 3)
        for y in range(step // 2, h, step):
            for x in range(step // 2, w, step):
                draw.ellipse((x - dot, y - dot, x + dot, y + dot), fill=(255, 255, 255, 26))
    img.paste(layer, (0, 0), layer)


def avatar_png(name: str, seed: str) -> bytes:
    a, b = palette(seed)
    img = _gradient(AVATAR_SIZE, a, b)
    _decorate(img, seed)
    draw = ImageDraw.Draw(img)
    text = initials(name)
    # inside the inscribed circle: a square of side ~ 0.7 * diameter is always visible
    font = _fit(draw, text, int(AVATAR_SIZE[0] * 0.55), int(AVATAR_SIZE[1] * 0.45), 420)
    draw.text((AVATAR_SIZE[0] / 2, AVATAR_SIZE[1] / 2), text, font=font, fill="white", anchor="mm")
    return _png(img)


def banner_png(title: str, tagline: str, seed: str) -> bytes:
    a, b = palette(seed)
    img = _gradient(BANNER_SIZE, b, a)
    _decorate(img, seed)
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


def _cover(art: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale ``art`` to fill ``size`` and cut the overflow evenly (like CSS cover)."""
    w, h = size
    scale = max(w / art.width, h / art.height)
    img = art.convert("RGB").resize(
        (round(art.width * scale), round(art.height * scale)), Image.Resampling.LANCZOS
    )
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def art_png(art: Image.Image) -> bytes:
    """Raw AI artwork as PNG (kept so a new name does not need a new painting)."""
    return _png(art.convert("RGB"))


def avatar_from_art(art: Image.Image) -> bytes:
    """Profile picture from AI artwork: square, motif centered for the circle crop."""
    return _png(_cover(art, AVATAR_SIZE))


def _shadow_text(
    img: Image.Image,
    xy: tuple[float, float],
    text: str,
    font: Font,
    fill: tuple[int, int, int],
) -> None:
    """Text with a soft drop shadow, readable on any artwork."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(
        (xy[0] + 4, xy[1] + 6), text, font=font, fill=(0, 0, 0, 190), anchor="mm"
    )
    layer = layer.filter(ImageFilter.GaussianBlur(10))
    img.paste(layer, (0, 0), layer)
    ImageDraw.Draw(img).text(xy, text, font=font, fill=fill, anchor="mm")


def banner_from_art(art: Image.Image, title: str, tagline: str) -> bytes:
    """Banner from AI artwork with the name set as real, sharp text in the safe area."""
    img = _cover(art, BANNER_SIZE).filter(ImageFilter.GaussianBlur(1.2))
    cx, cy = BANNER_SIZE[0] / 2, BANNER_SIZE[1] / 2
    safe_w, safe_h = BANNER_SAFE
    # darker band behind the text: the name stays readable on bright artwork
    band = Image.new("L", BANNER_SIZE, 0)
    ImageDraw.Draw(band).rounded_rectangle(
        (cx - safe_w * 0.58, cy - safe_h * 0.62, cx + safe_w * 0.58, cy + safe_h * 0.62),
        radius=60,
        fill=150,
    )
    band = band.filter(ImageFilter.GaussianBlur(70))
    img = Image.composite(Image.new("RGB", BANNER_SIZE, (0, 0, 0)), img, band)
    draw = ImageDraw.Draw(img)
    title_font = _fit(draw, title, int(safe_w * 0.92), int(safe_h * 0.5), 200)
    _shadow_text(img, (cx, cy - safe_h * 0.12), title, title_font, (255, 255, 255))
    if tagline:
        tag_font = _fit(draw, tagline, int(safe_w * 0.92), int(safe_h * 0.2), 72)
        _shadow_text(img, (cx, cy + safe_h * 0.28), tagline, tag_font, (238, 238, 238))
    return _png(img)


def store_png(settings: Settings, data: bytes, folder: str = "channel-setup") -> str:
    return storage.store_document(settings, data, "image/png", folder).uri
