"""FFmpeg helpers: technical probe of a video file and generated test media (Phase 7).

Only the local ``ffmpeg``/``ffprobe`` binaries are used; nothing is downloaded.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from core.config import Settings


class MediaError(RuntimeError):
    """A file could not be read or processed by FFmpeg."""


@dataclass(frozen=True)
class Probe:
    duration_s: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str | None
    pix_fmt: str | None
    size_bytes: int
    format_name: str

    @property
    def has_audio(self) -> bool:
        return self.audio_codec is not None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def run(cmd: list[str], *, timeout: float | None = None, binary: bool = False) -> Any:
    """Run an FFmpeg command and raise :class:`MediaError` with its stderr on failure."""
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)  # noqa: S603
    except FileNotFoundError as exc:
        raise MediaError(f"{cmd[0]} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"{Path(cmd[0]).name} timed out after {timeout}s") from exc
    if proc.returncode != 0:
        tail = proc.stderr.decode(errors="replace").strip().splitlines()[-3:]
        raise MediaError(f"{Path(cmd[0]).name} failed: {' | '.join(tail)}")
    return proc.stdout if binary else proc.stdout.decode(errors="replace")


def _fps(rate: str | None) -> float:
    try:
        value = float(Fraction(rate or "0"))
    except (ValueError, ZeroDivisionError):
        return 0.0
    return round(value, 3)


def probe(settings: Settings, path: Path) -> Probe:
    out = run(
        [
            settings.ffprobe_bin,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        timeout=60,
    )
    data = json.loads(out or "{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format") or {}
    if video is None:
        raise MediaError("No video stream")
    duration = float(fmt.get("duration") or video.get("duration") or 0)
    return Probe(
        duration_s=round(duration, 3),
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=_fps(video.get("avg_frame_rate")) or _fps(video.get("r_frame_rate")),
        video_codec=str(video.get("codec_name") or "unknown"),
        audio_codec=str(audio["codec_name"]) if audio and audio.get("codec_name") else None,
        pix_fmt=video.get("pix_fmt"),
        size_bytes=int(fmt.get("size") or path.stat().st_size),
        format_name=str(fmt.get("format_name") or ""),
    )


def technical_issues(settings: Settings, p: Probe) -> list[str]:
    """Reasons why a source file cannot be used. Empty list means usable."""
    issues = []
    if p.duration_s < settings.min_material_s:
        issues.append(f"Zu kurz ({p.duration_s:.1f} s, mindestens {settings.min_material_s:.0f} s)")
    if p.duration_s > settings.max_material_s:
        issues.append(f"Zu lang ({p.duration_s / 60:.0f} min)")
    if min(p.width, p.height) < settings.min_source_height:
        issues.append(
            f"Auflösung zu gering ({p.width}×{p.height}, mindestens {settings.min_source_height}p)"
        )
    if p.fps < 20:
        issues.append(f"Bildrate zu niedrig ({p.fps:.1f} fps)")
    return issues


def make_test_video(
    settings: Settings,
    path: Path,
    *,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
    calm_s: float = 20,
    action_s: float = 15,
    tail_s: float = 10,
    audio: bool = True,
) -> Path:
    """Generate a licence-free test video: calm part, hard cut, loud action part, calm tail.

    Built only from FFmpeg's synthetic sources (no third-party footage), so it can be
    used in tests and benchmarks without any rights question.
    """
    size = f"{width}x{height}"
    parts = [
        (f"color=c=0x303840:s={size}:r={fps}:d={calm_s}", "sine=f=220", calm_s, 0.03),
        (f"testsrc2=s={size}:r={fps}:d={action_s}", "anoisesrc=c=pink", action_s, 0.6),
        (f"color=c=0x203020:s={size}:r={fps}:d={tail_s}", "sine=f=330", tail_s, 0.03),
    ]
    cmd = [settings.ffmpeg_bin, "-v", "error", "-y"]
    for video, _, _, _ in parts:
        cmd += ["-f", "lavfi", "-i", video]
    if audio:
        for _, src, dur, _ in parts:  # volume is applied in the filter graph below
            cmd += ["-f", "lavfi", "-i", f"{src}:d={dur}:sample_rate=48000"]
    n = len(parts)
    if audio:
        vols = "".join(
            f"[{n + i}:a]volume={vol},aformat=channel_layouts=stereo[a{i}];"
            for i, (_, _, _, vol) in enumerate(parts)
        )
        pairs = "".join(f"[{i}:v][a{i}]" for i in range(n))
        graph = f"{vols}{pairs}concat=n={n}:v=1:a=1[v][a]"
        maps = ["-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "128k"]
    else:
        graph = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
        maps = ["-map", "[v]"]
    cmd += ["-filter_complex", graph, *maps]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    run(cmd, timeout=600)
    return path
