"""Phase 9: Localization, Voice and Subtitle agents (with real rendering)."""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import AgentRunStatus, Language, UserRole, VideoStatus
from models import Clip, Scene, Script, User, Variant
from models.production import Subtitle, Voiceover
from services import localization, media, orchestrator, storage, subtitles, voice
from services.controls import update_operations
from tests.conftest import login
from tests.integration.test_production import approved_material

# --- unit: localization ------------------------------------------------------------


def test_wrong_language_is_detected_but_game_names_are_ignored() -> None:
    assert localization.wrong_language("Das ist nicht der Plan.", Language.EN, [])
    assert not localization.wrong_language("Watch The Last of Us now.", Language.EN, [])
    assert not localization.wrong_language(
        "Achte auf The Last of Us.", Language.DE, ["The Last of Us"]
    )
    assert localization.wrong_language("Watch this and the end.", Language.DE, [])


def test_mechanical_fixes() -> None:
    text, fixes = localization.tidy("warte  bis bis zum Ende")
    assert text == "Warte bis zum Ende." and len(fixes) == 4
    assert localization.tidy("Titel ohne Punkt", sentence=False) == ("Titel ohne Punkt", [])
    desc, added = localization.adapt_description("Hook\n\n#Valorant #Gaming", Language.DE)
    assert desc.endswith("#Valorant #Gaming #GamingDeutsch") and added
    assert localization.adapt_description(desc, Language.DE) == (desc, [])
    same = localization.same_as_other_language({"hook": "Hi", "title": "A"}, {"hook": "Hi"})
    assert same == ["hook"]


# --- unit: voice timing and subtitles --------------------------------------------------


def test_voice_is_sped_up_at_most_and_overflow_reported() -> None:
    beat = {"kind": "payoff", "start_s": 10.0, "end_s": 12.0, "text": "x"}
    fits = voice.plan_segment(beat, 1.5, 30.0)
    assert fits.tempo == 1.0 and fits.overflow_s == 0 and fits.end_s == 11.5
    faster = voice.plan_segment(beat, 2.2, 30.0)
    assert 1.0 < faster.tempo <= voice.MAX_TEMPO and faster.overflow_s == 0
    too_long = voice.plan_segment(beat, 4.0, 30.0)
    assert too_long.tempo == voice.MAX_TEMPO and too_long.overflow_s > 1


def segment(kind: str, start: float, end: float, text: str) -> voice.Segment:
    return voice.Segment(kind, text, start, end, end, 1.0, 0.0)


def test_cues_are_short_ordered_and_readable() -> None:
    segs = [
        segment("hook", 0.0, 2.5, "Hättest du das in Valorant kommen sehen?"),
        segment(
            "buildup",
            3.0,
            9.0,
            "Die Spannung steigt mit jeder Sekunde und am Ende passiert etwas völlig Unerwartetes.",
        ),
    ]
    cues = subtitles.build_cues(segs, 30.0)
    assert len(cues) >= 3
    for cue in cues:
        assert 1 <= len(cue.lines) <= subtitles.MAX_LINES
        assert all(len(line) <= subtitles.MAX_LINE_CHARS for line in cue.lines)
    for a, b in itertools.pairwise(cues):
        assert a.end_s <= b.start_s
    assert subtitles.readability_issues(cues) == []
    fast = [subtitles.Cue(0.0, 0.5, ["Viel zu viel Text für eine so", "kurze Zeit auf dem Schirm"])]
    assert any("Zeichen/s" in i for i in subtitles.readability_issues(fast))

    srt = subtitles.to_srt(cues)
    assert srt.startswith("1\n00:00:00,000 --> 00:00:0")
    assert subtitles.to_vtt(cues).startswith("WEBVTT\n\n00:00:00.000 --> ")
    ass = subtitles.to_ass(cues, 1080, 1920)
    assert "PlayResY: 1920" in ass and ",2,86,86,422\n" in ass  # bottom centre, safe margins


# --- agents with real files -------------------------------------------------------------


@pytest.fixture(scope="module")
def gameplay(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("gameplay")
    return media.make_test_video(get_settings(), root / "g.mp4", calm_s=6, action_s=16, tail_s=4)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(
        update={
            "media_root": str(tmp_path / "media"),
            "render_preset": "ultrafast",
            "clip_target_s": 15,
            "clip_min_s": 10,
        }
    )


def run(db: Session, s: Settings, agent: str, variant_id: int) -> Any:
    return orchestrator.run_agent(
        db, s, agent, {"entity_type": "variants", "entity_id": variant_id}
    )


@pytest.fixture
def scripted(db: Session, settings: Settings, gameplay: Path) -> Iterator[Variant]:
    """German variant A with rendered clip and script, waiting in LOCALIZATION."""
    update_operations(db, None, {"creative_variants": 1, "max_daily_production_jobs": 100})
    material = approved_material(db, settings, gameplay)
    analysis = orchestrator.run_agent(
        db,
        settings,
        "gameplay_analysis",
        {"entity_type": "gameplay_files", "entity_id": material.id},
    )
    assert analysis.status == AgentRunStatus.SUCCEEDED, analysis.error
    variant = db.scalars(
        select(Variant)
        .join(Clip, Clip.id == Variant.clip_id)
        .join(Scene, Scene.id == Clip.scene_id)
        .where(Scene.gameplay_file_id == material.id, Variant.language == Language.DE)
        .order_by(Variant.id)
    ).first()
    assert variant is not None
    for agent in ("clip_production", "creative_director", "script_hook"):
        result = run(db, settings, agent, variant.id)
        assert result.status == AgentRunStatus.SUCCEEDED, (agent, result.error)
    assert variant.status == VideoStatus.LOCALIZATION
    yield variant


def frame(settings: Settings, path: Path, t: float) -> Any:
    raw = media.run(
        [settings.ffmpeg_bin, "-v", "error", "-ss", f"{t}", "-i", str(path), "-frames:v", "1",
         "-vf", "scale=180:320,format=gray", "-f", "rawvideo", "-"],
        timeout=60, binary=True,
    )  # fmt: skip
    return np.frombuffer(raw, dtype=np.uint8).reshape(320, 180).astype(np.float64)


def test_localization_voice_and_subtitles_produce_final_variant(
    db: Session,
    settings: Settings,
    scripted: Variant,
    api: TestClient,
    make_user: Callable[..., User],
) -> None:
    v = scripted
    loc = run(db, settings, "localization", v.id)
    assert loc.status == AgentRunStatus.SUCCEEDED, loc.error
    assert v.status == VideoStatus.VOICEOVER
    scripts = db.scalars(select(Script).where(Script.variant_id == v.id).order_by(Script.version))
    latest = list(scripts)[-1]
    assert latest.version == 2 and latest.source == "template+localized"  # hashtag added
    assert "#GamingDeutsch" in (latest.description or "")

    vo_run = run(db, settings, "voice", v.id)
    assert vo_run.status == AgentRunStatus.SUCCEEDED, vo_run.error
    assert v.status == VideoStatus.SUBTITLES
    vo = db.scalar(select(Voiceover).where(Voiceover.variant_id == v.id))
    assert vo is not None and vo.provider == "mock" and vo.commercial_use_cleared
    assert vo.script_id == latest.id and vo.segments[0]["kind"] == "hook"
    clip = db.get(Clip, v.clip_id)
    assert clip is not None and clip.duration_s is not None and vo.duration_s is not None
    assert abs(vo.duration_s - clip.duration_s) < 0.3  # one track of clip length

    sub_run = run(db, settings, "subtitle", v.id)
    assert sub_run.status == AgentRunStatus.SUCCEEDED, sub_run.error
    assert v.status == VideoStatus.QUALITY_CHECK
    subs = {s.format: s for s in db.scalars(select(Subtitle).where(Subtitle.variant_id == v.id))}
    assert set(subs) == {"srt", "vtt", "ass"} and subs["ass"].burned_in
    srt_text = storage.resolve(settings, subs["srt"].storage_uri or "").read_text("utf-8")
    assert srt_text.startswith("1\n00:00:00,000 -->")
    assert subs["srt"].cues and subs["srt"].issues == []

    final = storage.resolve(settings, v.storage_uri or "")
    raw = storage.resolve(settings, clip.storage_uri or "")
    assert final != raw
    probe = media.probe(settings, final)
    assert (probe.width, probe.height) == (clip.width, clip.height)
    assert probe.video_codec == "h264" and probe.audio_codec == "aac"
    assert abs(probe.duration_s - clip.duration_s) < 0.5

    # dashboard API: final video, subtitles and voice details
    api.app.dependency_overrides[get_settings] = lambda: settings
    make_user("viewer@example.com", UserRole.VIEWER)
    h = login(api, "viewer@example.com")
    assert api.get(f"/api/variants/{v.id}/file", headers=h).status_code == 200
    vtt = api.get(f"/api/variants/{v.id}/subtitles.vtt", headers=h)
    assert vtt.status_code == 200 and vtt.text.startswith("WEBVTT")
    assert api.get(f"/api/variants/{v.id}/subtitles.ass", headers=h).status_code == 404
    listed = api.get("/api/production/clips", headers=h).json()
    brief = next(x for c in listed for x in c["variants"] if x["id"] == v.id)
    assert brief["final_video"] and brief["voice"]["provider"] == "mock"
    assert brief["subtitle_formats"] == ["ass", "srt", "vtt"]

    # captions are burned in: the lower caption band changes, the top of the frame does not
    t = 1.0
    a, b = frame(settings, raw, t), frame(settings, final, t)
    band = slice(int(320 * 0.55), int(320 * (1 - subtitles.SAFE_BOTTOM)) + 4)
    caption_diff = float(np.abs(a[band] - b[band]).mean())
    top_diff = float(np.abs(a[:80] - b[:80]).mean())
    assert caption_diff > 3 * max(top_diff, 0.5)


def test_text_in_wrong_language_fails_localization(
    db: Session, settings: Settings, scripted: Variant
) -> None:
    script = db.scalar(select(Script).where(Script.variant_id == scripted.id))
    assert script is not None
    script.beats = [{**b, "text": "Watch this and the end now."} for b in script.beats]
    db.flush()
    result = run(db, settings, "localization", scripted.id)
    assert result.status == AgentRunStatus.FAILED
    assert "anderen Sprache" in (result.error or "")


def test_unknown_voice_provider_waits(db: Session, settings: Settings, scripted: Variant) -> None:
    assert run(db, settings, "localization", scripted.id).status == AgentRunStatus.SUCCEEDED
    update_operations(db, None, {"tts_provider": "nicht-angebunden"})
    result = run(db, settings, "voice", scripted.id)
    assert result.status == AgentRunStatus.SKIPPED and result.output["gate"] == "provider"
    assert scripted.status == VideoStatus.VOICEOVER  # stays, master tries again later


def test_piper_without_downloaded_voices_waits(
    db: Session, settings: Settings, scripted: Variant, tmp_path: Path
) -> None:
    assert run(db, settings, "localization", scripted.id).status == AgentRunStatus.SUCCEEDED
    update_operations(db, None, {"tts_provider": "piper"})
    empty = settings.model_copy(update={"piper_voice_dir": str(tmp_path / "none")})
    result = run(db, empty, "voice", scripted.id)
    assert result.status == AgentRunStatus.SKIPPED and result.output["gate"] == "provider"
    assert "piper_voices fetch" in (result.error or "")
    assert scripted.status == VideoStatus.VOICEOVER


class UnclearedVoice(voice.MockVoice):
    name = "uncleared"
    commercial_use_cleared = False


class PaidVoice(voice.MockVoice):
    name = "paid"
    cost_per_second_eur = Decimal("0.01")


@pytest.fixture
def extra_voices() -> Iterator[None]:
    voice.PROVIDERS.update({"uncleared": UnclearedVoice, "paid": PaidVoice})
    try:
        yield
    finally:
        voice.PROVIDERS.pop("uncleared", None)
        voice.PROVIDERS.pop("paid", None)


def test_voice_without_commercial_rights_is_refused(
    db: Session, settings: Settings, scripted: Variant, extra_voices: None
) -> None:
    assert run(db, settings, "localization", scripted.id).status == AgentRunStatus.SUCCEEDED
    update_operations(db, None, {"tts_provider": "uncleared"})
    result = run(db, settings, "voice", scripted.id)
    assert result.status == AgentRunStatus.FAILED
    assert "kommerzielle Nutzung" in (result.error or "")


def test_paid_voice_needs_budget_approval(
    db: Session, settings: Settings, scripted: Variant, extra_voices: None
) -> None:
    assert run(db, settings, "localization", scripted.id).status == AgentRunStatus.SUCCEEDED
    update_operations(db, None, {"tts_provider": "paid"})
    result = run(db, settings, "voice", scripted.id)  # paid calls disabled by default
    assert result.status == AgentRunStatus.SKIPPED and result.output["gate"] == "budget"
    assert db.scalar(select(Voiceover).where(Voiceover.variant_id == scripted.id)) is None
