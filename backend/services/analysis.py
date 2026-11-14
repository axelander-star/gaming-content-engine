"""Gameplay analysis: find and rate scenes worth cutting (Phase 7, Agent 6).

Signals per second of the source:

* **motion** – mean absolute difference between sampled frames (OpenCV),
  plus where in the picture the motion happens (for the 9:16 crop),
* **loudness** – RMS level of the audio track in dBFS,
* **cuts** – shot boundaries from PySceneDetect.

Candidate windows of the target clip length are rated from these signals.
All values are relative to the same file, so a quiet strategy game and a
loud shooter are both judged against their own baseline. Humour cannot be
recognised from these signals; that needs a vision model (paid, later).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from core.config import Settings
from services import media
from services.media import Probe

FArray = NDArray[np.float64]

#: Weights of the scene score (sum 1.0). Documented in docs/AGENTS.md.
WEIGHTS = {"motion": 0.35, "audio": 0.25, "surprise": 0.20, "cuts": 0.10, "buildup": 0.10}
SILENCE_DB = -90.0
SNAP_S = 3.0  # start/end move to a nearby shot boundary within this distance
FEATURE_WIDTH = 160


@dataclass
class Features:
    duration_s: float
    motion: FArray  # per second, mean absolute frame difference (0..255)
    focus: FArray  # per second, horizontal centre of motion 0..1 (nan = no motion)
    audio_db: FArray  # per second, RMS in dBFS (SILENCE_DB if silent/no audio)
    has_audio: bool
    cuts: list[float] = field(default_factory=list)


@dataclass
class Candidate:
    start_s: float
    end_s: float
    score: float
    scores: dict[str, float]
    tags: list[str]
    focus_x: float | None  # horizontal centre of the action 0..1
    spread: float  # how far the action moves horizontally (std of focus)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- signal extraction ----------------------------------------------------------


def _video_signals(settings: Settings, path: Path, probe: Probe) -> tuple[FArray, FArray]:
    """Motion and motion centre per second, from frames sampled by FFmpeg."""
    fps = settings.analysis_sample_fps
    w = FEATURE_WIDTH
    h = max(2, round(w * probe.height / max(probe.width, 1) / 2) * 2)
    raw = media.run(
        [
            settings.ffmpeg_bin,
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"fps={fps},scale={w}:{h}:flags=area,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        timeout=settings.production_job_timeout_s,
        binary=True,
    )
    flat = np.frombuffer(raw, dtype=np.uint8)
    n = flat.size // (w * h)
    frames = flat[: n * w * h].reshape(n, h, w)
    seconds = max(1, math.ceil(probe.duration_s))
    motion_sum = np.zeros(seconds)
    focus_sum = np.zeros(seconds)
    weight_sum = np.zeros(seconds)
    counts = np.zeros(seconds)
    columns = (np.arange(w) + 0.5) / w
    for i in range(1, n):
        diff = cv2.absdiff(frames[i], frames[i - 1]).astype(np.float64)
        sec = min(seconds - 1, int(i / fps))
        level = float(diff.mean())
        motion_sum[sec] += level
        counts[sec] += 1
        col = diff.sum(axis=0)
        total = float(col.sum())
        if total > 0:
            focus_sum[sec] += float((col * columns).sum() / total) * level
            weight_sum[sec] += level
    motion = np.divide(motion_sum, counts, out=np.zeros(seconds), where=counts > 0)
    focus = np.divide(focus_sum, weight_sum, out=np.full(seconds, np.nan), where=weight_sum > 0)
    return motion, focus


def _audio_db(settings: Settings, path: Path, probe: Probe) -> FArray:
    seconds = max(1, math.ceil(probe.duration_s))
    if not probe.has_audio:
        return np.full(seconds, SILENCE_DB)
    rate = 8000
    raw = media.run(
        [
            settings.ffmpeg_bin,
            "-v",
            "error",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-f",
            "s16le",
            "-",
        ],
        timeout=settings.production_job_timeout_s,
        binary=True,
    )
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    out = np.full(seconds, SILENCE_DB)
    for sec in range(seconds):
        chunk = samples[sec * rate : (sec + 1) * rate]
        if chunk.size:
            rms = math.sqrt(float(np.mean(chunk**2)))
            out[sec] = max(SILENCE_DB, 20 * math.log10(rms)) if rms > 0 else SILENCE_DB
    return out


def _cuts(path: Path, probe: Probe) -> list[float]:
    """Shot boundaries in seconds (PySceneDetect content detector)."""
    from scenedetect import ContentDetector, SceneManager, open_video

    video = open_video(str(path))
    manager = SceneManager()
    manager.auto_downscale = True
    manager.add_detector(ContentDetector(threshold=27.0, min_scene_len=15))
    skip = max(0, int(probe.fps // 10))  # ~10 analysed frames per second is enough
    manager.detect_scenes(video, frame_skip=skip, show_progress=False)
    scenes = manager.get_scene_list()
    return [round(start.get_seconds(), 2) for start, _ in scenes[1:]]


def extract(settings: Settings, path: Path, probe: Probe) -> Features:
    motion, focus = _video_signals(settings, path, probe)
    return Features(
        duration_s=probe.duration_s,
        motion=motion,
        focus=focus,
        audio_db=_audio_db(settings, path, probe),
        has_audio=probe.has_audio,
        cuts=_cuts(path, probe),
    )


# --- rating -----------------------------------------------------------------------


def _clip01(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def rate_window(f: Features, a: int, b: int) -> tuple[float, dict[str, float], list[str]]:
    """Score of the window [a, b) in whole seconds, its components and tags."""
    motion = f.motion[a:b]
    ref_motion = float(np.percentile(f.motion, 95)) if f.motion.size else 0.0
    s_motion = _clip01(float(motion.mean()) / ref_motion) if ref_motion > 0 else 0.0

    db = f.audio_db[a:b]
    lo, hi = (float(np.percentile(f.audio_db, p)) for p in (5, 95))
    audible = f.has_audio and hi > SILENCE_DB + 1
    level_known = audible and hi - lo >= 3
    # unknown (no audio or a flat level) counts neutral
    s_audio = _clip01((float(db.mean()) - lo) / (hi - lo)) if level_known else 0.5

    # surprise: sudden jump in loudness or motion compared with the 3 s before
    jump = 0.0
    for t in range(max(a, 1), b):
        before = slice(max(0, t - 3), t)
        if audible:
            jump = max(jump, (f.audio_db[t] - float(np.median(f.audio_db[before])) - 3) / 9)
        prev = float(f.motion[before].mean())
        if ref_motion > 0:
            jump = max(jump, (f.motion[t] - prev) / ref_motion - 0.3)
    s_surprise = _clip01(jump)

    length = max(1, b - a)
    cuts_inside = sum(1 for c in f.cuts if a < c < b)
    s_cuts = _clip01(cuts_inside * 10 / length / 2)

    third = max(1, length // 3)
    level = motion / ref_motion if ref_motion > 0 else np.zeros(length)
    if level_known:
        level = (level + np.clip((db - lo) / (hi - lo), 0, 1)) / 2
    s_buildup = _clip01((float(level[-third:].mean()) - float(level[:third].mean())) * 2)

    scores = {
        "motion": round(s_motion, 3),
        "audio": round(s_audio, 3),
        "surprise": round(s_surprise, 3),
        "cuts": round(s_cuts, 3),
        "buildup": round(s_buildup, 3),
    }
    score = sum(WEIGHTS[k] * v for k, v in scores.items())
    tags = []
    if s_motion >= 0.6:
        tags.append("action")
    if s_surprise >= 0.6:
        tags.append("ueberraschung")
    if s_buildup >= 0.5:
        tags.append("spannung")
    if s_motion < 0.2 and s_audio <= 0.5:
        tags.append("ruhig")
    return round(score, 3), scores, tags


def _snap(t: float, cuts: list[float]) -> float:
    near = [c for c in cuts if abs(c - t) <= SNAP_S]
    return min(near, key=lambda c: abs(c - t)) if near else t


def _focus(f: Features, a: int, b: int) -> tuple[float | None, float]:
    values = f.focus[a:b]
    weights = f.motion[a:b]
    mask = ~np.isnan(values) & (weights > 0)
    if not mask.any():
        return None, 0.0
    mean = float(np.average(values[mask], weights=weights[mask]))
    spread = float(np.sqrt(np.average((values[mask] - mean) ** 2, weights=weights[mask])))
    return round(mean, 3), round(spread, 3)


def find_scenes(settings: Settings, f: Features, limit: int = 10) -> list[Candidate]:
    """Best non-overlapping windows, best first (at most ``limit``)."""
    duration = f.duration_s
    length = int(min(settings.clip_target_s, settings.clip_max_s, math.floor(duration)))
    if length < 1:
        return []
    starts = range(0, max(1, math.floor(duration) - length + 1))
    rated = sorted(
        ((rate_window(f, a, a + length), a) for a in starts),
        key=lambda item: (-item[0][0], item[1]),
    )
    chosen: list[Candidate] = []
    taken: list[tuple[float, float]] = []
    for (score, scores, tags), a in rated:
        start = _snap(float(a), f.cuts)
        end = _snap(float(a + length), f.cuts)
        if not settings.clip_min_s <= end - start <= settings.clip_max_s:
            start, end = float(a), float(a + length)
        start, end = max(0.0, start), min(duration, end)
        if any(start < e and s < end for s, e in taken):
            continue
        focus_x, spread = _focus(f, int(start), max(int(start) + 1, int(end)))
        chosen.append(
            Candidate(round(start, 2), round(end, 2), score, scores, tags, focus_x, spread)
        )
        taken.append((start, end))
        if len(chosen) >= limit:
            break
    return chosen


def summary(f: Features) -> dict[str, Any]:
    return {
        "duration_s": f.duration_s,
        "cuts": len(f.cuts),
        "has_audio": f.has_audio,
        "mean_motion": round(float(f.motion.mean()), 2) if f.motion.size else 0.0,
        "loudness_db_p95": round(float(np.percentile(f.audio_db, 95)), 1),
    }
