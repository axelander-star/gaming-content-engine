"""Ausbau A6: one video on every platform (plus English), long videos into shorts."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.quality_control import _duplicates
from core.config import Settings, get_settings
from core.enums import (
    Language,
    LibraryOrigin,
    PlatformCode,
    ProductionStatus,
    UserRole,
    VideoStatus,
)
from models import Channel, User
from models.library import LibraryItem, OwnProduction
from models.production import QualityCheck, Variant, Voiceover
from models.projects import ContentProject
from services import approval, crosspost, gates, media, own_production, publishers, splitter
from tests.conftest import login
from tests.factories import build_chain
from tests.integration.test_approval import make_channel, make_item

pytestmark = pytest.mark.integration

MakeUser = Callable[..., User]
ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(update={"media_root": str(tmp_path / "media")})


# --- one clip on every platform --------------------------------------------------------


def _ready_clip(db: Session) -> tuple[Variant, list[Channel]]:
    chain = build_chain(db, Language.DE)
    project_id = chain.channel.content_project_id
    channels = db.scalars(select(Channel).where(Channel.content_project_id == project_id)).all()
    for c in channels:
        c.is_paused = False
    v = chain.variant
    v.status = VideoStatus.READY_TO_PUBLISH
    v.title = "Dieser Clutch war knapp"
    v.description = "Eine Runde, die alles entschieden hat."
    v.hashtags = ["Gaming", "Clutch", "Shooter", "Highlights", "Shorts", "Win", "GG"]
    v.quality_score = 0.92
    v.storage_uri = "mock://final.mp4"
    v.sha256 = "a" * 64
    chain.clip.duration_s = 30.0
    db.add(QualityCheck(variant_id=v.id, passed=True, score=0.92, checks={}, reasons=[]))
    db.flush()
    return v, list(channels)


def test_clip_is_copied_to_the_other_platforms_of_its_language(db: Session) -> None:
    v, channels = _ready_clip(db)
    origin_channel = db.get(Channel, v.channel_id)
    assert origin_channel is not None
    expected = {
        c.id for c in channels
        if c.language == Language.DE and c.id != v.channel_id
        and c.platform.code in approval.RULES
    }  # fmt: skip
    assert expected

    done = crosspost.sweep(db, get_settings())
    copies = db.scalars(
        select(Variant).where(Variant.clip_id == v.clip_id, Variant.id != v.id)
    ).all()
    assert {c.channel_id for c in copies} == expected  # no English channel, no Twitch
    assert done and done[0]["variant_id"] == v.id
    for c in copies:
        code = db.get(Channel, c.channel_id).platform.code  # type: ignore[union-attr]
        assert c.status == VideoStatus.READY_TO_PUBLISH
        assert c.storage_uri == v.storage_uri and c.sha256 == v.sha256
        assert crosspost.origin_id(c) == v.id
        assert c.quality_score == v.quality_score
        assert len(c.hashtags) <= crosspost.HASHTAGS[code]
        if code == PlatformCode.YOUTUBE:
            assert c.hashtags[-1] == "Shorts"
        else:
            assert "Shorts" not in c.hashtags
        qc = db.scalar(select(QualityCheck).where(QualityCheck.variant_id == c.id))
        assert qc is not None and qc.passed and qc.checks["crosspost_of"] == v.id

    # second run: nothing new; copies are never copied again
    assert crosspost.sweep(db, get_settings()) == []
    assert crosspost.targets(db, copies[0]) == []


def test_crosspost_skips_paused_too_long_and_can_be_switched_off(db: Session) -> None:
    v, channels = _ready_clip(db)
    tiktok = next(
        c for c in channels
        if c.platform.code == PlatformCode.TIKTOK and c.language == Language.DE
    )  # fmt: skip
    tiktok.is_paused = True
    assert crosspost.sweep(db, get_settings().model_copy(update={"crosspost_enabled": False})) == []

    clip = v.clip
    assert clip is not None
    clip.duration_s = 120.0  # Facebook Reels take 90 s at most
    db.flush()
    result = crosspost.sweep(db, get_settings())[0]
    made = {db.get(Variant, m["variant_id"]).channel_id for m in result["copies"]}  # type: ignore[union-attr]
    assert tiktok.id not in made
    skipped = [s["reason"] for s in result["skipped"]]
    assert any("erlaubt 90 s" in r for r in skipped)


def test_copy_keeps_ai_voice_label_and_is_no_duplicate_of_its_original(db: Session) -> None:
    v, _ = _ready_clip(db)
    db.add(Voiceover(variant_id=v.id, provider="piper", commercial_use_cleared=True))
    db.flush()
    crosspost.sweep(db, get_settings())
    copy = db.scalars(
        select(Variant).where(Variant.clip_id == v.clip_id, Variant.id != v.id)
    ).first()
    assert copy is not None
    assert publishers._synthetic_voice(db, copy) is True  # disclosure follows the original

    copy.status = VideoStatus.PUBLISHED
    db.flush()
    clip = v.clip
    assert clip is not None
    exact = next(c for c in _duplicates(db, v, clip) if c.name == "duplicate_exact")
    assert exact.passed  # its own copy on another platform is not a duplicate


def test_fit_texts_cuts_at_words() -> None:
    v = Variant(title="Wort " * 40, description="Satz " * 200, hashtags=["a", "b", "c"])
    t = crosspost.fit_texts(v, PlatformCode.TIKTOK)
    assert len(t.title) <= 150 and t.title.endswith("…") and "Wor…" not in t.title
    assert len(t.description) <= crosspost.DESCRIPTION[PlatformCode.TIKTOK]
    yt = crosspost.fit_texts(v, PlatformCode.YOUTUBE)
    assert yt.hashtags == ["a", "b", "c", "Shorts"] and len(yt.title) <= 100


# --- library video everywhere (approval center) -----------------------------------------


@pytest.fixture
def food(db: Session) -> ContentProject:
    from services.seed import seed_base_data

    seed_base_data(db)
    p = ContentProject(slug="essen", name="Essen", languages=["de", "en"], priority=210)
    db.add(p)
    db.flush()
    return p


@ffmpeg
def test_everywhere_prepares_all_platforms_and_languages(
    db: Session, settings: Settings, food: ContentProject, tmp_path: Path
) -> None:
    yt = make_channel(db, food, PlatformCode.YOUTUBE)
    tt = make_channel(db, food, PlatformCode.TIKTOK)
    en = make_channel(db, food, PlatformCode.INSTAGRAM)
    en.language = Language.EN
    db.flush()
    src = media.make_test_video(
        get_settings(), tmp_path / "v.mp4", width=720, height=1280, calm_s=2, action_s=2, tail_s=1
    )
    item = make_item(db, settings, food, src)

    ids = [c.id for c in approval.open_channels(db, item.id)]
    assert set(ids) == {yt.id, tt.id, en.id}
    posts = approval.prepare(db, settings, item.id, ids, None, skip_unfit=True)
    by_channel = {p.channel_id: p for p in posts}
    assert set(by_channel) == {yt.id, tt.id, en.id}
    assert by_channel[en.id].language == Language.EN
    assert approval.open_channels(db, item.id) == []  # nothing left to prepare

    landscape = make_item(
        db, settings, food,
        media.make_test_video(get_settings(), tmp_path / "l.mp4", calm_s=2, action_s=2, tail_s=1),
    )  # fmt: skip
    landscape.title = "Quer"
    as_video = {"title": "Quer", "description": "", "hashtags": [], "options": {"format": "video"}}
    posts = approval.prepare(
        db, settings, landscape.id, [yt.id, tt.id, en.id], None,
        texts={yt.id: as_video}, skip_unfit=True,
    )  # fmt: skip
    assert [p.channel_id for p in posts] == [yt.id]  # TikTok/Instagram need portrait
    with pytest.raises(approval.ApprovalError):
        approval.prepare(db, settings, landscape.id, [tt.id], None)


# --- English version of an own production ----------------------------------------------


def test_translate_production_keeps_pictures(db: Session, food: ContentProject) -> None:
    prod = OwnProduction(
        content_project_id=food.id,
        title="Hafer richtig lagern",
        language=Language.DE,
        status=ProductionStatus.DONE,
        segments=[
            {"headline": "Trocken", "text": "Immer trocken lagern.", "image_item_id": 7},
            {"headline": "Dunkel", "text": "Licht macht ihn alt.", "image_item_id": None},
        ],
        script_source="mock",
    )
    db.add(prod)
    db.flush()
    en = own_production.translate(db, get_settings(), prod, Language.EN, None)
    assert en.id != prod.id and en.language == Language.EN
    assert en.status == ProductionStatus.DRAFT
    assert [s["image_item_id"] for s in en.segments] == [7, None]
    assert all(s["text"].startswith("[EN]") for s in en.segments)  # mock translation
    assert en.result == {"translated_from": prod.id}
    assert en.script_source.startswith("translated:")
    with pytest.raises(own_production.ProductionError):
        own_production.translate(db, get_settings(), prod, Language.DE, None)


# --- long video into shorts ------------------------------------------------------------


@ffmpeg
def test_split_long_video_into_shorts(
    db: Session, settings: Settings, food: ContentProject, tmp_path: Path
) -> None:
    src = media.make_test_video(
        get_settings(), tmp_path / "long.mp4", width=640, height=360,
        calm_s=25, action_s=25, tail_s=15,
    )  # fmt: skip
    item = make_item(db, settings, food, src)
    item.title = "Langes Video"
    assert splitter.check(item) is None
    with pytest.raises(splitter.SplitError):
        splitter.request(db, item, count=10, length_s=60)  # does not fit
    splitter.request(db, item, count=2, length_s=15)
    assert item.split_state == "queued"
    with pytest.raises(splitter.SplitError) as busy:
        splitter.request(db, item)
    assert busy.value.status_code == 409
    assert splitter.pending(db) == [item]

    out = splitter.run(db, settings, item)
    assert out["status"] == "done", out
    shorts = splitter.children(db, item.id)
    assert len(shorts) == 2 and item.split_state == "done"
    first, second = shorts
    assert first.title == "Langes Video – Teil 1" and second.title.endswith("Teil 2")
    for s in shorts:
        assert s.origin == LibraryOrigin.GENERATED and s.parent_item_id == item.id
        assert (s.width, s.height) == (720, 1280)
        assert 10 <= (s.duration_s or 0) <= 20
        assert s.rights["cut_from"] == item.id and s.rights["origin"] == "upload"
        assert gates.library_item_problem(s, food.id) is None  # usable for posts
        assert s.note and s.note.startswith("Ausschnitt ")
        assert splitter.check(s) == "Das ist schon ein Ausschnitt"
    starts = [m["start_s"] for m in item.split_info["made"]]
    assert starts == sorted(starts)

    short = make_item(db, settings, food, media.make_test_video(
        get_settings(), tmp_path / "s.mp4", calm_s=2, action_s=2, tail_s=1))  # fmt: skip
    assert "Erst ab 60 Sekunden" in (splitter.check(short) or "")


def test_cut_of_upload_without_confirmation_is_blocked(db: Session, food: ContentProject) -> None:
    item = LibraryItem(
        content_project_id=food.id, kind="video", origin=LibraryOrigin.GENERATED,
        status="ready", title="x", content_type="video/mp4", original_uri="local://x",
        original_sha256="b" * 64, size_bytes=1, rights={"cut_from": 1, "origin": "upload"},
    )  # fmt: skip
    assert gates.library_item_problem(item, food.id) == "Rechtebestätigung fehlt"


def test_api_split_and_translate(
    api: TestClient, db: Session, make_user: MakeUser, food: ContentProject
) -> None:
    make_user(email="op@example.com", role=UserRole.OPERATOR)
    headers = login(api, "op@example.com")
    item = LibraryItem(
        content_project_id=food.id, kind="video", origin=LibraryOrigin.UPLOAD,
        status="ready", title="Stream", content_type="video/mp4", original_uri="local://y",
        original_sha256="c" * 64, size_bytes=1, duration_s=600.0,
        rights={"confirmed_by_user_id": 1},
    )  # fmt: skip
    db.add(item)
    db.flush()
    listed = next(i for i in api.get("/api/library").json() if i["id"] == item.id)
    assert listed["split_problem"] is None
    assert listed["split_suggestion"] == {"count": 5, "length_s": 30.0}
    image = LibraryItem(
        content_project_id=food.id, kind="image", origin=LibraryOrigin.UPLOAD,
        status="ready", title="Bild", content_type="image/png", original_uri="local://i",
        original_sha256="e" * 64, size_bytes=1, rights={"confirmed_by_user_id": 1},
    )  # fmt: skip
    db.add(image)
    db.flush()
    img = next(i for i in api.get("/api/library").json() if i["id"] == image.id)
    assert img["split_problem"] == "Nur Videos lassen sich zerlegen"

    r = api.post(f"/api/library/{item.id}/split", json={"count": 3, "length_s": 20},
                 headers=headers)  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.json()["split_state"] == "queued"
    again = api.post(f"/api/library/{item.id}/split", json={}, headers=headers)
    assert again.status_code == 409
    bad = api.post(f"/api/library/{item.id}/split", json={"count": 50}, headers=headers)
    assert bad.status_code == 422

    prod = OwnProduction(
        content_project_id=food.id, title="Tipp", language=Language.DE,
        status=ProductionStatus.DRAFT, segments=[{"headline": "A", "text": "Text eins."}],
        script_source="manual",
    )  # fmt: skip
    db.add(prod)
    db.flush()
    t = api.post(f"/api/productions/{prod.id}/translate", json={"language": "en"},
                 headers=headers)  # fmt: skip
    assert t.status_code == 201, t.text
    assert t.json()["language"] == "en" and t.json()["status"] == "draft"
    same = api.post(f"/api/productions/{prod.id}/translate", json={"language": "de"},
                    headers=headers)  # fmt: skip
    assert same.status_code == 422


def test_everywhere_api_reports_when_nothing_is_left(
    api: TestClient, db: Session, make_user: MakeUser, food: ContentProject
) -> None:
    make_user(email="op2@example.com", role=UserRole.OPERATOR)
    headers = login(api, "op2@example.com")
    item = LibraryItem(
        content_project_id=food.id, kind="video", origin=LibraryOrigin.UPLOAD,
        status="ready", title="Nichts", content_type="video/mp4", original_uri="local://z",
        original_sha256="d" * 64, size_bytes=1, duration_s=20.0,
        rights={"confirmed_by_user_id": 1},
    )  # fmt: skip
    db.add(item)
    db.flush()
    r = api.post("/api/approval/prepare", json={"item_id": item.id, "everywhere": True},
                 headers=headers)  # fmt: skip
    assert r.status_code == 409 and "schon" in r.json()["detail"]
