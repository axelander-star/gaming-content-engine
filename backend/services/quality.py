"""Quality control checks (Phase 10, Agent 13).

Each check returns a :class:`Check`: ``blocking`` failures reject the variant no
matter the score (broken export, missing rights, duplicate, platform limit); other
findings lower the quality score. The score starts at 1.0 and must reach the
operator's ``min_quality_score``.

Platform limits are conservative values from the providers' public help pages
(as of 11/2026); they must be checked again against the official API
documentation before live publishing (Phase 12/13).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.config import Settings
from core.enums import PlatformCode
from services import media


@dataclass(frozen=True)
class PlatformRules:
    max_duration_s: float
    max_title: int
    max_description: int
    max_bytes: int


#: ⚠️ check against official docs before Phase 12/13.
PLATFORM_RULES: dict[PlatformCode, PlatformRules] = {
    PlatformCode.YOUTUBE: PlatformRules(180, 100, 5000, 256 * 1024**3),  # Shorts up to 3 min
    PlatformCode.TIKTOK: PlatformRules(600, 150, 2200, 4 * 1024**3),
    PlatformCode.INSTAGRAM: PlatformRules(180, 150, 2200, 1024**3),
    PlatformCode.FACEBOOK: PlatformRules(90, 150, 2200, 1024**3),  # Reels
}

VERTICAL_SIZES = {(1080, 1920), (720, 1280)}
LOUDNESS_RANGE = (-18.0, -10.0)  # integrated LUFS accepted around the -14 target
MAX_TRUE_PEAK = -1.0
SILENT_LUFS = -50.0
MAX_BLACK_S = 1.0
MAX_FREEZE_SHARE = 0.4
DUPLICATE_HAMMING = 10  # bits of 64 that may differ for "same frame"
DUPLICATE_SHARE = 0.6  # share of matching seconds that makes a duplicate

#: Score deductions for non-blocking findings.
PENALTY = {
    "silent": 0.15,
    "loudness": 0.1,
    "true_peak": 0.05,
    "black": 0.1,
    "frozen": 0.1,
    "voice_overflow": 0.05,
    "subtitle_issue": 0.05,
}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    blocking: bool = False
    penalty: float = 0.0
    values: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def score(checks: list[Check]) -> float:
    return round(max(0.0, 1.0 - sum(c.penalty for c in checks if not c.passed)), 3)


# --- measurements -------------------------------------------------------------------


def decode_errors(settings: Settings, path: Path) -> list[str]:
    """Decode the whole file; any decoder error means a broken export."""
    try:
        media.run(
            [settings.ffmpeg_bin, "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
            timeout=settings.production_job_timeout_s,
        )
    except media.MediaError as exc:
        return [str(exc)]
    return []


def _stderr(settings: Settings, path: Path, af: str | None, vf: str | None) -> str:
    import subprocess

    cmd = [settings.ffmpeg_bin, "-hide_banner", "-nostats", "-i", str(path)]
    if af:
        cmd += ["-af", af]
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-f", "null", "-"]
    proc = subprocess.run(  # noqa: S603
        cmd, capture_output=True, timeout=settings.production_job_timeout_s, check=False
    )
    if proc.returncode != 0:
        raise media.MediaError(proc.stderr.decode(errors="replace").strip()[-300:])
    return proc.stderr.decode(errors="replace")


def loudness(settings: Settings, path: Path) -> tuple[float, float]:
    """Integrated loudness (LUFS) and true peak (dBTP) after EBU R128."""
    err = _stderr(settings, path, "loudnorm=I=-14:TP=-1.5:print_format=json", None)
    data = json.loads(err[err.rindex("{") : err.rindex("}") + 1])

    def num(key: str) -> float:
        value = str(data[key])
        return -99.0 if value in ("-inf", "inf", "nan") else float(value)

    return num("input_i"), num("input_tp")


def black_and_frozen(settings: Settings, path: Path) -> tuple[float, float]:
    """Seconds of black picture and of frozen picture."""
    err = _stderr(
        settings,
        path,
        None,
        "blackdetect=d=0.3:pix_th=0.10,freezedetect=n=0.001:d=1.5",
    )
    black = sum(float(x) for x in re.findall(r"black_duration:\s*([\d.]+)", err))
    frozen = sum(float(x) for x in re.findall(r"freeze_duration:\s*([\d.]+)", err))
    return round(black, 2), round(frozen, 2)


# --- duplicates ---------------------------------------------------------------------


def _hashes(fingerprint: str | None) -> list[int]:
    return [int(h, 16) for h in (fingerprint or "").split(",") if h]


def similarity(a: str | None, b: str | None) -> float:
    """Share of seconds of the shorter video that match the other one (best offset)."""
    ha, hb = _hashes(a), _hashes(b)
    if not ha or not hb:
        return 0.0
    if len(ha) > len(hb):
        ha, hb = hb, ha
    best = 0
    for offset in range(-len(ha) + 1, len(hb)):
        hits = 0
        for i, h in enumerate(ha):
            j = i + offset
            if 0 <= j < len(hb) and bin(h ^ hb[j]).count("1") <= DUPLICATE_HAMMING:
                hits += 1
        best = max(best, hits)
    return round(best / len(ha), 3)


def overlap_s(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
