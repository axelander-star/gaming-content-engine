"""Subtitles for vertical video (Phase 9, Agent 12).

Cues follow the voiceover segments. Each cue has at most two lines of
``MAX_LINE_CHARS`` characters, stays on screen at least ``MIN_CUE_S`` and is
checked for reading speed. Files: SRT and WebVTT for the platforms, ASS for
burning into the video.

Position: bottom centre, raised to ``SAFE_BOTTOM`` of the frame height so captions
stay clear of the platform buttons and descriptions that cover the lower part of
Shorts, TikTok and Reels; side margins keep text off the right-hand icon column.
"""

from __future__ import annotations

import textwrap
from dataclasses import asdict, dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from core.config import Settings
from services.voice import Segment

MAX_LINE_CHARS = 32
MAX_LINES = 2
MIN_CUE_S = 0.8
MAX_CPS = 17.0  # characters per second, common reading-speed limit
SAFE_BOTTOM = 0.22  # share of the frame height kept free at the bottom
SAFE_SIDE = 0.08
FONT = "DejaVu Sans"


@dataclass
class Cue:
    start_s: float
    end_s: float
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def cps(self) -> float:
        chars = sum(len(line) for line in self.lines)
        return chars / max(0.01, self.end_s - self.start_s)

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "cps": round(self.cps, 1)}


def _chunks(text: str) -> list[list[str]]:
    lines = textwrap.wrap(text, MAX_LINE_CHARS, break_long_words=False)
    return [lines[i : i + MAX_LINES] for i in range(0, len(lines), MAX_LINES)] or [[""]]


def build_cues(segments: list[Segment], clip_s: float) -> list[Cue]:
    """Split every segment into cues; time shared by character count."""
    cues: list[Cue] = []
    for seg in segments:
        chunks = _chunks(seg.text)
        total = sum(len(" ".join(c)) for c in chunks) or 1
        span = max(MIN_CUE_S * len(chunks), seg.end_s - seg.start_s)
        t = seg.start_s
        for chunk in chunks:
            dur = max(MIN_CUE_S, span * len(" ".join(chunk)) / total)
            cues.append(Cue(round(t, 2), round(min(t + dur, clip_s), 2), chunk))
            t += dur
    # no overlaps: a cue ends when the next one starts
    for a, b in pairwise(cues):
        if a.end_s > b.start_s:
            a.end_s = b.start_s
    return [c for c in cues if c.end_s > c.start_s]


def readability_issues(cues: list[Cue]) -> list[str]:
    issues = []
    for i, c in enumerate(cues, start=1):
        if c.cps > MAX_CPS:
            issues.append(f"Untertitel {i}: {c.cps:.0f} Zeichen/s (max. {MAX_CPS:.0f})")
        if c.end_s - c.start_s < MIN_CUE_S - 0.05:
            issues.append(f"Untertitel {i}: nur {c.end_s - c.start_s:.1f} s sichtbar")
        if any(len(line) > MAX_LINE_CHARS for line in c.lines):
            issues.append(f"Untertitel {i}: Zeile länger als {MAX_LINE_CHARS} Zeichen")
    return issues


def _ts(seconds: float, sep: str) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    blocks = [
        f"{i}\n{_ts(c.start_s, ',')} --> {_ts(c.end_s, ',')}\n{c.text}\n"
        for i, c in enumerate(cues, start=1)
    ]
    return "\n".join(blocks)


def to_vtt(cues: list[Cue]) -> str:
    blocks = [f"{_ts(c.start_s, '.')} --> {_ts(c.end_s, '.')}\n{c.text}\n" for c in cues]
    return "WEBVTT\n\n" + "\n".join(blocks)


def _ass_ts(seconds: float) -> str:
    cs = round(seconds * 100)
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def to_ass(cues: list[Cue], width: int, height: int) -> str:
    size = round(height * 0.034)  # 65 px at 1920
    outline = max(2, round(size * 0.08))
    margin_v = round(height * SAFE_BOTTOM)
    margin_lr = round(width * SAFE_SIDE)
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
        f"Style: Default,{FONT},{size},&H00FFFFFF,&H00000000,&H64000000,1,1,{outline},0,2,"
        f"{margin_lr},{margin_lr},{margin_v}\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Text\n"
    )
    events = [
        f"Dialogue: 0,{_ass_ts(c.start_s)},{_ass_ts(c.end_s)},Default,"
        + "\\N".join(line.replace("{", "(").replace("}", ")") for line in c.lines)
        for c in cues
    ]
    return header + "\n".join(events) + "\n"


def burn_command(settings: Settings, clip: Path, voice: Path, ass: Path, out: Path) -> list[str]:
    """Final variant: captions burned in, voice over the gameplay (ducked while speaking)."""
    ass_arg = str(ass).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    graph = (
        f"[0:v]ass='{ass_arg}'[v];"
        "[1:a]asplit=2[vk][vm];"
        "[0:a][vk]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300[g];"
        "[g][vm]amix=inputs=2:normalize=0:duration=first[a]"
    )
    return [
        settings.ffmpeg_bin, "-v", "error", "-y", "-i", str(clip), "-i", str(voice),
        "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", settings.render_preset, "-crf", str(settings.render_crf),
        "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(out),
    ]  # fmt: skip
