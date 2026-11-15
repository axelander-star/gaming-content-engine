"""Clip production: cut, 9:16 reframing and export (Phase 7, Agent 7).

Output (PROJECT_SPEC section 7): MP4, H.264 (High, yuv420p), AAC 48 kHz stereo,
9:16, 1080×1920 if the source allows it (720×1280 below 1080p), frame rate of
the source capped at ``RENDER_MAX_FPS``, ``+faststart`` for streaming.

Two layouts:

* ``crop`` – a 9:16 window around the action (centre of motion from the analysis),
* ``blur_fit`` – the whole 16:9 picture centred on a blurred copy of itself; used
  when the action moves across the full width and a crop would lose it.
"""

from __future__ import annotations

import contextlib
import time
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from redis import Redis

from agents.base import CapacityError
from core.config import Settings
from services import media, storage
from services.media import Probe

FADE_S = 0.3
SPREAD_FOR_BLUR = 0.18  # horizontal spread of the action above which a crop loses too much
SLOTS_KEY = "render:slots"


class RenderError(RuntimeError):
    """The rendered file does not meet the technical requirements."""


@dataclass(frozen=True)
class RenderPlan:
    start_s: float
    duration_s: float
    width: int
    height: int
    fps: float
    layout: str  # crop | blur_fit
    crop_x: int | None  # left edge of the crop in source pixels
    crop_w: int | None
    has_audio: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RenderResult:
    stored: storage.StoredFile
    probe: Probe
    plan: RenderPlan
    render_seconds: float
    fingerprint: str

    @property
    def realtime_factor(self) -> float:
        """Seconds of clip rendered per second of work (>1 = faster than real time)."""
        return round(self.plan.duration_s / max(self.render_seconds, 1e-6), 2)


def _even(x: float) -> int:
    return max(2, round(x / 2) * 2)


def plan(
    settings: Settings,
    source: Probe,
    start_s: float,
    end_s: float,
    focus_x: float | None,
    spread: float,
) -> RenderPlan:
    width, height = (1080, 1920) if min(source.width, source.height) >= 1080 else (720, 1280)
    fps = round(min(source.fps or 30.0, settings.render_max_fps), 3)
    duration = round(min(end_s, source.duration_s) - start_s, 3)
    if duration <= 0:
        raise RenderError("Empty clip range")
    portrait = source.height >= source.width * 16 / 9 - 2
    crop_w = _even(source.height * 9 / 16)
    if portrait or crop_w >= source.width:
        return RenderPlan(
            start_s, duration, width, height, fps, "crop", None, None, source.has_audio
        )
    if focus_x is None or spread > SPREAD_FOR_BLUR:
        return RenderPlan(
            start_s, duration, width, height, fps, "blur_fit", None, None, source.has_audio
        )
    centre = focus_x * source.width
    crop_x = int(min(max(0.0, centre - crop_w / 2), source.width - crop_w))
    return RenderPlan(
        start_s, duration, width, height, fps, "crop", crop_x, crop_w, source.has_audio
    )


def _video_filter(p: RenderPlan) -> str:
    fade_out = max(0.0, p.duration_s - FADE_S)
    tail = (
        f"fps={p.fps},fade=t=in:st=0:d={FADE_S},fade=t=out:st={fade_out:.3f}:d={FADE_S},"
        "format=yuv420p,setsar=1"
    )
    if p.layout == "blur_fit":
        return (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale={p.width}:{p.height}:force_original_aspect_ratio=increase,"
            f"crop={p.width}:{p.height},boxblur=20:2[bgb];"
            f"[fg]scale={p.width}:-2:flags=lanczos[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,{tail}[v]"
        )
    if p.crop_w is not None and p.crop_x is not None:
        crop = f"crop={p.crop_w}:ih:{p.crop_x}:0,"
    else:  # source is already (nearly) portrait: fill and centre-crop
        crop = f"scale={p.width}:{p.height}:force_original_aspect_ratio=increase,"
        crop += f"crop={p.width}:{p.height},"
    return f"[0:v]{crop}scale={p.width}:{p.height}:flags=lanczos,{tail}[v]"


def command(settings: Settings, src: Path, out: Path, p: RenderPlan) -> list[str]:
    cmd = [settings.ffmpeg_bin, "-v", "error", "-y", "-ss", f"{p.start_s:.3f}"]
    cmd += ["-t", f"{p.duration_s:.3f}", "-i", str(src)]
    if p.has_audio:
        fade_out = max(0.0, p.duration_s - FADE_S)
        audio = f"[0:a]afade=t=in:st=0:d={FADE_S},afade=t=out:st={fade_out:.3f}:d={FADE_S}[a]"
    else:  # silent track, so every clip has AAC audio for voiceover and platforms
        cmd += ["-f", "lavfi", "-t", f"{p.duration_s:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        audio = "[1:a]anull[a]"
    cmd += ["-filter_complex", f"{_video_filter(p)};{audio}", "-map", "[v]", "-map", "[a]"]
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        settings.render_preset,
        "-crf",
        str(settings.render_crf),
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        "-shortest",
        str(out),
    ]
    return cmd


def verify(settings: Settings, p: RenderPlan, out: Probe) -> list[str]:
    """Technical requirements of a finished clip. Empty list = all met."""
    issues = []
    if out.video_codec != "h264":
        issues.append(f"Videocodec {out.video_codec} statt H.264")
    if out.audio_codec != "aac":
        issues.append(f"Audiocodec {out.audio_codec} statt AAC")
    if (out.width, out.height) != (p.width, p.height):
        issues.append(f"Auflösung {out.width}×{out.height} statt {p.width}×{p.height}")
    if out.pix_fmt != "yuv420p":
        issues.append(f"Pixelformat {out.pix_fmt}")
    if abs(out.duration_s - p.duration_s) > 0.5:
        issues.append(f"Länge {out.duration_s:.1f} s statt {p.duration_s:.1f} s")
    if out.size_bytes > settings.max_clip_bytes:
        issues.append(f"Datei zu groß ({out.size_bytes / 1024**2:.0f} MB)")
    return issues


def fingerprint(settings: Settings, path: Path) -> str:
    """Visual fingerprint: 64-bit difference hash of one frame per second, hex joined.

    Used by quality control (Phase 10) to recognise near-duplicate clips."""
    raw = media.run(
        [
            settings.ffmpeg_bin,
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            "fps=1,scale=64:64:flags=area,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        timeout=300,
        binary=True,
    )
    frames = np.frombuffer(raw, dtype=np.uint8)
    hashes = []
    for i in range(frames.size // (64 * 64)):
        frame = frames[i * 4096 : (i + 1) * 4096].reshape(64, 64)
        small = cv2.resize(frame, (9, 8), interpolation=cv2.INTER_AREA).astype(np.int16)
        bits = (small[:, 1:] > small[:, :-1]).flatten()
        value = 0
        for bit in bits:
            value = (value << 1) | int(bit)
        hashes.append(f"{value:016x}")
    return ",".join(hashes)


def faststart(path: Path) -> bool:
    """True if the MP4 index (moov) comes before the media data (mdat)."""
    head = path.read_bytes()[: 1024 * 1024]
    moov, mdat = head.find(b"moov"), head.find(b"mdat")
    return moov != -1 and (mdat == -1 or moov < mdat)


@contextlib.contextmanager
def render_slot(redis: Redis, limit: int, ttl_s: int) -> Iterator[None]:
    """At most ``limit`` renders at the same time across all workers.

    Raises :class:`CapacityError` (run is skipped, retried by the master later).
    Slots of crashed workers expire after ``ttl_s``."""
    token = uuid.uuid4().hex
    now = time.time()
    redis.zremrangebyscore(SLOTS_KEY, 0, now - ttl_s)
    redis.zadd(SLOTS_KEY, {token: now})
    try:
        rank: Any = redis.zrank(SLOTS_KEY, token)
        if rank is None or int(rank) >= limit:
            raise CapacityError(f"all {limit} render slot(s) busy")
        yield
    finally:
        redis.zrem(SLOTS_KEY, token)


def render(
    settings: Settings,
    src: Path,
    source: Probe,
    start_s: float,
    end_s: float,
    focus_x: float | None,
    spread: float,
    *,
    folder: str = "clips",
) -> RenderResult:
    p = plan(settings, source, start_s, end_s, focus_x, spread)
    tmp = storage.work_dir(settings) / f"render-{uuid.uuid4().hex}.mp4"
    began = time.monotonic()
    try:
        media.run(command(settings, src, tmp, p), timeout=settings.production_job_timeout_s)
        took = time.monotonic() - began
        out = media.probe(settings, tmp)
        issues = verify(settings, p, out)
        if not faststart(tmp):
            issues.append("MP4 ohne faststart")
        if issues:
            raise RenderError("; ".join(issues))
        fp = fingerprint(settings, tmp)
        stored = storage.store_path(settings, tmp, folder, ".mp4")
    finally:
        tmp.unlink(missing_ok=True)
    return RenderResult(stored, out, p, round(took, 2), fp)
