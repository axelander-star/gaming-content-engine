"""Phase 7: technical check, scene analysis and clip production with real FFmpeg.

All test videos are generated from FFmpeg's synthetic sources (no third-party
footage). Acceptance: a self-made test video becomes a clip with correct
technical parameters.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import AgentRunStatus, MaterialStatus, UserRole, VideoStatus
from models import Asset, Clip, GameplayFile, Scene, User, Variant
from services import analysis, media, orchestrator, render, storage
from tests.conftest import login
from tests.factories import build_chain

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed"),
]


@pytest.fixture(scope="module")
def videos(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    s = get_settings()
    root = tmp_path_factory.mktemp("videos")
    return {
        "720p": media.make_test_video(s, root / "720p.mp4"),
        "1080p": media.make_test_video(
            s, root / "1080p.mp4", width=1920, height=1080, calm_s=8, action_s=12, tail_s=5
        ),
        "short": media.make_test_video(
            s, root / "short.mp4", calm_s=2, action_s=2, tail_s=1, audio=False
        ),
    }


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(
        update={"media_root": str(tmp_path / "media"), "render_preset": "ultrafast"}
    )


def approved_material(db: Session, settings: Settings, video: Path) -> GameplayFile:
    """Rights-approved material whose file lies in the local store."""
    chain = build_chain(db)
    stored = storage.store_path(settings, video, "materials", ".mp4", move=False)
    old = db.get(Asset, chain.gameplay_file.asset_id)
    assert old is not None
    material = GameplayFile(
        asset_id=old.id,
        game_id=chain.gameplay_file.game_id,
        storage_uri=stored.uri,
        sha256=uuid4().hex * 2,
        status=MaterialStatus.RIGHTS_APPROVED,
    )
    db.add(material)
    db.flush()
    return material


def run(db: Session, s: Settings, agent: str, entity_type: str, entity_id: int) -> Any:
    return orchestrator.run_agent(
        db, s, agent, {"entity_type": entity_type, "entity_id": entity_id}
    )


# --- technical check ------------------------------------------------------------


def test_probe_and_technical_check(videos: dict[str, Path], settings: Settings) -> None:
    p = media.probe(settings, videos["720p"])
    assert (p.width, p.height, p.fps, p.video_codec, p.audio_codec) == (
        1280,
        720,
        30.0,
        "h264",
        "aac",
    )
    assert media.technical_issues(settings, p) == []
    short = media.probe(settings, videos["short"])
    assert short.audio_codec is None
    assert any("Zu kurz" in i for i in media.technical_issues(settings, short))
    strict = settings.model_copy(update={"min_source_height": 1080})
    assert any("Auflösung" in i for i in media.technical_issues(strict, p))


def test_probe_rejects_non_video(tmp_path: Path, settings: Settings) -> None:
    bogus = tmp_path / "x.mp4"
    bogus.write_text("not a video")
    with pytest.raises(media.MediaError):
        media.probe(settings, bogus)


# --- analysis -------------------------------------------------------------------


def test_analysis_finds_the_action_scene(videos: dict[str, Path], settings: Settings) -> None:
    probe = media.probe(settings, videos["720p"])
    features = analysis.extract(settings, videos["720p"], probe)
    assert features.cuts and abs(features.cuts[0] - 20) < 0.5  # hard cut calm -> action
    best = analysis.find_scenes(settings, features, 3)[0]
    overlap = min(best.end_s, 35) - max(best.start_s, 20)
    assert overlap >= 14  # the loud, moving part is inside the chosen scene
    assert best.score >= settings.min_scene_score
    assert "action" in best.tags
    assert settings.clip_min_s <= best.end_s - best.start_s <= settings.clip_max_s
    calm = analysis.rate_window(features, 0, 15)[0]
    assert calm < best.score


def test_render_plan_layouts(settings: Settings) -> None:
    src = media.Probe(60, 1920, 1080, 60.0, "h264", "aac", "yuv420p", 1, "mp4")
    crop = render.plan(settings, src, 10, 40, 0.9, 0.05)
    assert crop.layout == "crop" and (crop.width, crop.height) == (1080, 1920)
    assert crop.crop_w == 608 and crop.crop_x == 1920 - 608  # clamped to the right edge
    assert render.plan(settings, src, 10, 40, 0.5, 0.4).layout == "blur_fit"
    assert render.plan(settings, src, 10, 40, None, 0).layout == "blur_fit"
    low = media.Probe(60, 1280, 720, 120.0, "h264", None, "yuv420p", 1, "mp4")
    p = render.plan(settings, low, 0, 30, 0.5, 0.0)
    assert (p.width, p.height, p.fps, p.has_audio) == (720, 1280, 60.0, False)
    portrait = media.Probe(60, 1080, 1920, 30.0, "h264", "aac", "yuv420p", 1, "mp4")
    assert render.plan(settings, portrait, 0, 30, 0.5, 0.0).crop_w is None


# --- acceptance: agents end to end ------------------------------------------------


def test_test_video_becomes_clip_with_correct_parameters(
    db: Session, redis_client: Redis, videos: dict[str, Path], settings: Settings
) -> None:
    material = approved_material(db, settings, videos["1080p"])
    analysed = run(db, settings, "gameplay_analysis", "gameplay_files", material.id)
    assert analysed.status == AgentRunStatus.SUCCEEDED, analysed.error
    assert material.status == MaterialStatus.ANALYZED
    assert material.width == 1920 and material.audio_codec == "aac"
    scenes = db.scalars(select(Scene).where(Scene.gameplay_file_id == material.id)).all()
    selected = [s for s in scenes if s.selected]
    assert len(selected) == 1 and selected[0].rank == 1
    clip = db.scalars(select(Clip).where(Clip.scene_id == selected[0].id)).one()
    variants = db.scalars(select(Variant).where(Variant.clip_id == clip.id)).all()
    assert sorted(v.language.value for v in variants) == ["de", "en"]
    assert all(v.status == VideoStatus.SCENE_SELECTED for v in variants)

    first = run(db, settings, "clip_production", "variants", variants[0].id)
    assert first.status == AgentRunStatus.SUCCEEDED, first.error
    assert first.output["rendered_now"] is True
    second = run(db, settings, "clip_production", "variants", variants[1].id)
    assert second.output["rendered_now"] is False  # same clip, rendered once
    assert all(v.status == VideoStatus.EDITING for v in variants)
    assert variants[0].storage_uri == variants[1].storage_uri == clip.storage_uri

    path = storage.resolve(settings, clip.storage_uri or "")
    out = media.probe(settings, path)
    assert (out.video_codec, out.audio_codec, out.pix_fmt) == ("h264", "aac", "yuv420p")
    assert (out.width, out.height) == (1080, 1920)  # 9:16
    assert out.fps == 30.0
    assert settings.clip_min_s <= out.duration_s <= settings.clip_max_s
    assert render.faststart(path)
    assert clip.sha256 == storage.sha256_file(path)
    assert len((clip.fingerprint or "").split(",")) >= int(out.duration_s) - 1
    assert clip.render_seconds and clip.render_params["realtime_factor"] > 0


def test_broken_file_fails_without_retries(
    db: Session, redis_client: Redis, tmp_path: Path, settings: Settings
) -> None:
    bogus = tmp_path / "broken.mp4"
    bogus.write_bytes(b"\x00" * 2048)
    material = approved_material(db, settings, bogus)
    result = run(db, settings, "gameplay_analysis", "gameplay_files", material.id)
    assert result.status == AgentRunStatus.FAILED
    assert material.status == MaterialStatus.FAILED
    assert material.retry_count >= settings.agent_max_retries  # master will not retry
    assert "nicht lesbar" in (material.error_message or "")


def test_too_short_material_fails_technical_check(
    db: Session, redis_client: Redis, videos: dict[str, Path], settings: Settings
) -> None:
    material = approved_material(db, settings, videos["short"])
    result = run(db, settings, "gameplay_analysis", "gameplay_files", material.id)
    assert result.status == AgentRunStatus.FAILED
    assert "Technische Prüfung" in (material.error_message or "")


def test_render_waits_for_free_slot(
    db: Session, redis_client: Redis, videos: dict[str, Path], settings: Settings
) -> None:
    material = approved_material(db, settings, videos["720p"])
    run(db, settings, "gameplay_analysis", "gameplay_files", material.id)
    variant = db.scalars(
        select(Variant)
        .join(Clip, Clip.id == Variant.clip_id)
        .join(Scene, Scene.id == Clip.scene_id)
        .where(Scene.gameplay_file_id == material.id)
    ).first()
    assert variant is not None
    with render.render_slot(redis_client, 1, 60):  # another worker is rendering
        busy = run(db, settings, "clip_production", "variants", variant.id)
    assert busy.status == AgentRunStatus.SKIPPED and busy.output == {"gate": "capacity"}
    assert variant.status == VideoStatus.SCENE_SELECTED
    assert redis_client.zcard(render.SLOTS_KEY) == 0


# --- API ----------------------------------------------------------------------------


@pytest.fixture
def media_api(api: TestClient, settings: Settings) -> Iterator[TestClient]:
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    yield api


def test_upload_and_production_api(
    media_api: TestClient,
    db: Session,
    videos: dict[str, Path],
    settings: Settings,
    make_user: Callable[..., User],
) -> None:
    make_user("op@example.com", UserRole.OPERATOR)
    chain = build_chain(db)
    h = login(media_api, "op@example.com")
    form = {
        "source_id": str(chain.license.source_id),
        "license_id": str(chain.license.id),
        "game_id": str(chain.gameplay_file.game_id),
    }

    def upload(path: Path, ctype: str = "video/mp4") -> Any:
        with path.open("rb") as fh:
            return media_api.post(
                "/api/materials/upload",
                data={**form, "title": path.stem},
                files={"file": (path.name, fh, ctype)},
                headers=h,
            )

    ok = upload(videos["720p"])
    assert ok.status_code == 201, ok.text
    assert ok.json()["status"] == "DISCOVERED" and ok.json()["duration_s"] == 45.0
    material = db.get(GameplayFile, ok.json()["id"])
    assert material is not None and (material.width, material.height) == (1280, 720)
    assert storage.resolve(settings, material.storage_uri).is_file()
    assert upload(videos["720p"]).status_code == 409
    short = upload(videos["short"])
    assert short.status_code == 422 and "Zu kurz" in short.json()["detail"]
    assert upload(videos["720p"], "text/plain").status_code == 422
    assert not any((Path(settings.media_root) / "tmp").iterdir())  # no leftovers

    # analysed and rendered material shows up in the production API
    material.status = MaterialStatus.RIGHTS_APPROVED
    db.flush()
    run(db, settings, "gameplay_analysis", "gameplay_files", material.id)
    clips = media_api.get("/api/production/clips").json()
    mine = [c for c in clips if c["material_id"] == material.id]
    assert mine and not mine[0]["rendered"] and len(mine[0]["variants"]) == 2
    variant_id = mine[0]["variants"][0]["id"]
    run(db, settings, "clip_production", "variants", variant_id)
    clip = media_api.get("/api/production/clips").json()[0]
    assert clip["rendered"] and (clip["width"], clip["height"]) == (720, 1280)
    file = media_api.get(f"/api/clips/{clip['id']}/file")
    assert file.status_code == 200 and file.headers["content-type"] == "video/mp4"
    scenes = media_api.get(f"/api/materials/{material.id}/scenes").json()
    assert scenes[0]["rank"] == 1 and scenes[0]["selected"]
    cap = media_api.get("/api/production/capacity").json()
    assert cap["clips_rendered_7d"] >= 1 and cap["realtime_factor"] > 0
    assert cap["clips_per_hour"] > 0 and cap["parallel_slots"] == 1
    assert media_api.get("/api/clips/999999/file").status_code == 404
