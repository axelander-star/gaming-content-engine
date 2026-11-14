# ruff: noqa: F811 - pytest fixtures imported from the Phase 9 tests
"""Phase 10: quality control, duplicate detection and platform limits."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import AgentRunStatus, UserRole, VideoStatus
from models import Clip, User, Variant
from models.access import Notification
from models.production import GameplayFile, QualityCheck, Scene, Subtitle, Voiceover
from models.rights import Asset, License
from services import quality, storage, workflow
from services.controls import update_operations
from services.quality import Check
from tests.conftest import login
from tests.integration.test_localization_voice import (  # noqa: F401 - shared fixtures
    gameplay,
    run,
    scripted,
    settings,
)

# --- unit ---------------------------------------------------------------------------


def test_score_counts_only_failed_penalties() -> None:
    checks = [
        Check("loudness", False, "", penalty=0.1),
        Check("black", True, "", penalty=0.1),
        Check("frozen", False, "", penalty=0.1),
    ]
    assert quality.score(checks) == 0.8
    assert quality.score([Check("x", False, "", penalty=2.0)]) == 0.0


def test_similarity_finds_shifted_copies_and_ignores_other_videos() -> None:
    base = [f"{(i * 0x9E3779B97F4A7C15) & (2**64 - 1):016x}" for i in range(1, 21)]
    a = ",".join(base)
    shifted = ",".join(["0" * 16, "f" * 16, *base[:15]])
    other = ",".join(f"{(i * 0xC2B2AE3D27D4EB4F + 7) & (2**64 - 1):016x}" for i in range(20))
    assert quality.similarity(a, a) == 1.0
    assert quality.similarity(a, shifted) >= 0.7  # 15 of the 15 shared seconds
    assert quality.similarity(a, other) < quality.DUPLICATE_SHARE
    assert quality.similarity(a, None) == 0.0


def test_overlap() -> None:
    assert quality.overlap_s((0, 10), (5, 20)) == 5
    assert quality.overlap_s((0, 10), (10, 20)) == 0


def test_platform_rules_cover_all_platforms() -> None:
    from core.enums import PlatformCode

    assert set(quality.PLATFORM_RULES) == set(PlatformCode)
    assert all(r.max_duration_s >= 60 for r in quality.PLATFORM_RULES.values())


# --- pipeline -----------------------------------------------------------------------


@pytest.fixture
def checked(db: Session, settings: Settings, scripted: Variant) -> Iterator[Variant]:
    """Finished variant waiting in QUALITY_CHECK."""
    for agent in ("localization", "voice", "subtitle"):
        result = run(db, settings, agent, scripted.id)
        assert result.status == AgentRunStatus.SUCCEEDED, (agent, result.error)
    assert scripted.status == VideoStatus.QUALITY_CHECK
    yield scripted


def latest_check(db: Session, variant: Variant) -> QualityCheck:
    qc = db.scalar(
        select(QualityCheck)
        .where(QualityCheck.variant_id == variant.id)
        .order_by(QualityCheck.id.desc())
        .limit(1)
    )
    assert qc is not None
    return qc


def by_name(qc: QualityCheck) -> dict[str, dict[str, Any]]:
    return {c["name"]: c for c in qc.checks["items"]}


def test_finished_variant_is_approved_and_ready(
    db: Session,
    settings: Settings,
    checked: Variant,
    api: TestClient,
    make_user: Callable[..., User],
) -> None:
    result = run(db, settings, "quality_control", checked.id)
    assert result.status == AgentRunStatus.SUCCEEDED, result.error
    qc = latest_check(db, checked)
    assert qc.passed, qc.reasons
    assert checked.status == VideoStatus.READY_TO_PUBLISH
    assert checked.quality_score == qc.score and qc.score is not None and qc.score >= 0.7
    checks = by_name(qc)
    for name in ("integrity", "decode", "format", "platform", "rights", "voice", "subtitles",
                 "loudness", "true_peak", "black", "frozen", "duplicate_exact",
                 "duplicate_visual", "duplicate_scene"):  # fmt: skip
        assert checks[name]["passed"], (name, checks[name]["detail"])
    measured = qc.checks["measured"]
    low, high = quality.LOUDNESS_RANGE
    assert low <= measured["lufs"] <= high  # loudnorm in the final render
    assert measured["probe"]["width"] == 1080 or measured["probe"]["width"] == 720

    # dashboard API shows the result
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    make_user("viewer@example.com", UserRole.VIEWER)
    h = login(api, "viewer@example.com")
    listed = api.get("/api/production/clips", headers=h).json()
    brief = next(x for c in listed for x in c["variants"] if x["id"] == checked.id)
    assert brief["status"] == "READY_TO_PUBLISH"
    assert brief["quality"]["passed"] and brief["quality"]["score"] == qc.score
    assert {c["name"] for c in brief["quality"]["checks"]} >= {"decode", "duplicate_visual"}


def reject_reasons(db: Session, settings: Settings, variant: Variant) -> list[str]:
    result = run(db, settings, "quality_control", variant.id)
    assert result.status == AgentRunStatus.SUCCEEDED, result.error
    assert variant.status == VideoStatus.QUALITY_REJECTED
    qc = latest_check(db, variant)
    assert not qc.passed and variant.quality_score == qc.score
    note = db.scalar(
        select(Notification).where(Notification.title.contains(f"Variante #{variant.id} "))
    )
    assert note is not None
    return list(qc.reasons)


def published_twin(
    db: Session,
    variant: Variant,
    start_s: float,
    end_s: float,
    sha256: str | None = None,
    fingerprint: str | None = None,
) -> Variant:
    """Another clip of the same material, already published on the same channel."""
    clip = db.get(Clip, variant.clip_id)
    assert clip is not None
    twin_clip = Clip(scene_id=clip.scene_id, start_s=start_s, end_s=end_s)
    db.add(twin_clip)
    db.flush()
    twin = Variant(
        clip_id=twin_clip.id,
        channel_id=variant.channel_id,
        language=variant.language,
        variant_label="A",
        status=VideoStatus.PUBLISHED,
        sha256=sha256,
        fingerprint=fingerprint,
    )
    db.add(twin)
    db.flush()
    return twin


def test_exact_copy_is_rejected(db: Session, settings: Settings, checked: Variant) -> None:
    twin = published_twin(db, checked, sha256=checked.sha256, start_s=1000.0, end_s=1010.0)
    reasons = reject_reasons(db, settings, checked)
    assert f"Identische Datei wie Variante #{twin.id}" in reasons


def test_visual_duplicate_is_rejected(db: Session, settings: Settings, checked: Variant) -> None:
    published_twin(db, checked, fingerprint=checked.fingerprint, start_s=1000.0, end_s=1010.0)
    reasons = reject_reasons(db, settings, checked)
    assert any(r.startswith("Bild zu 100% gleich") for r in reasons), reasons


def test_same_scene_on_same_channel_is_rejected(
    db: Session, settings: Settings, checked: Variant
) -> None:
    clip = db.get(Clip, checked.clip_id)
    assert clip is not None
    published_twin(db, checked, start_s=clip.start_s + 1, end_s=clip.end_s + 1)
    reasons = reject_reasons(db, settings, checked)
    assert any("Gleiche Szene" in r for r in reasons), reasons


def test_sibling_variant_counts_as_ab_test(
    db: Session, settings: Settings, checked: Variant
) -> None:
    sibling = Variant(
        clip_id=checked.clip_id,
        channel_id=checked.channel_id,
        language=checked.language,
        variant_label="B",
        status=VideoStatus.PUBLISHED,
        fingerprint=checked.fingerprint,
    )
    db.add(sibling)
    db.flush()
    result = run(db, settings, "quality_control", checked.id)
    assert result.status == AgentRunStatus.SUCCEEDED
    qc = latest_check(db, checked)
    assert qc.passed, qc.reasons
    assert by_name(qc)["ab_test"]["values"]["siblings"] == ["B"]


def test_broken_export_is_rejected(db: Session, settings: Settings, checked: Variant) -> None:
    path = storage.resolve(settings, checked.storage_uri or "")
    data = path.read_bytes()
    broken = path.with_name("broken.mp4")
    broken.write_bytes(data[: len(data) // 3])  # cut off: moov atom at the start, data missing
    stored = storage.store_path(settings, broken, "variants", ".mp4")
    checked.storage_uri, checked.sha256 = stored.uri, stored.sha256
    db.flush()
    reasons = reject_reasons(db, settings, checked)
    assert any(r.startswith(("Fehlerhafter Export", "Datei nicht lesbar")) for r in reasons)


def test_changed_file_is_rejected(db: Session, settings: Settings, checked: Variant) -> None:
    path = storage.resolve(settings, checked.storage_uri or "")
    with path.open("ab") as fh:
        fh.write(b"tampered")
    reasons = reject_reasons(db, settings, checked)
    assert "Datei wurde nach dem Rendern verändert" in reasons


def test_platform_limits_and_voice_rights_block(
    db: Session, settings: Settings, checked: Variant
) -> None:
    checked.title = "x" * 120
    vo = db.scalar(select(Voiceover).where(Voiceover.variant_id == checked.id))
    assert vo is not None
    vo.commercial_use_cleared = False
    db.flush()
    reasons = reject_reasons(db, settings, checked)
    assert any("Titel 120 Zeichen (max. 100)" in r for r in reasons), reasons
    assert any("ohne kommerzielle Nutzungsrechte" in r for r in reasons), reasons


def test_low_score_is_rejected_and_can_be_reworked(
    db: Session, settings: Settings, checked: Variant
) -> None:
    srt = db.scalar(
        select(Subtitle).where(Subtitle.variant_id == checked.id, Subtitle.format == "srt")
    )
    assert srt is not None
    srt.issues = ["Untertitel 1: 25 Zeichen/s (max. 17)"]
    update_operations(db, None, {"min_quality_score": 1.0})
    db.flush()
    reasons = reject_reasons(db, settings, checked)
    assert reasons[0].startswith("Qualitätswert 0.95 unter Mindestwert 1.00")
    assert "Untertitel 1: 25 Zeichen/s (max. 17)" in reasons
    workflow.transition(db, checked, VideoStatus.EDITING, actor="test")  # rework allowed


def test_expired_license_stops_before_approval(
    db: Session, settings: Settings, checked: Variant
) -> None:
    material = db.scalar(
        select(GameplayFile)
        .join(Scene, Scene.gameplay_file_id == GameplayFile.id)
        .join(Clip, Clip.scene_id == Scene.id)
        .where(Clip.id == checked.clip_id)
    )
    assert material is not None
    asset = db.get(Asset, material.asset_id)
    assert asset is not None
    lic = db.get(License, asset.license_id)
    assert lic is not None
    lic.valid_until = date.today() - timedelta(days=1)
    db.flush()
    result = run(db, settings, "quality_control", checked.id)
    assert result.status == AgentRunStatus.SKIPPED
    assert result.output["gate"] == "rights"
    assert checked.status == VideoStatus.QUALITY_CHECK  # never approved


def test_missing_file_is_rejected(db: Session, settings: Settings, checked: Variant) -> None:
    Path(storage.resolve(settings, checked.storage_uri or "")).unlink()
    reasons = reject_reasons(db, settings, checked)
    assert reasons[0] == "Datei fehlt im Speicher"
