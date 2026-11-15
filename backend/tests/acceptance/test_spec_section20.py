"""Acceptance test, PROJECT_SPEC section 20: the whole flow in one connected run.

Trend -> material -> rights -> analysis -> scenes -> clips -> DE/EN -> voice and
subtitles -> quality -> publishing decision -> publishing -> performance ->
learning -> adapted strategy -> dashboard.

Every step runs the real agent through the orchestrator (the same code path as
the worker). External services are replaced by the project's mock services:

* trend sources: test data (``TREND_SOURCES_MODE=mock``),
* voice: the silent mock voice (no TTS provider is connected),
* publishing: mock posts (``PUBLISHING_MODE=mock``, nothing leaves the system),
* statistics: synthetic numbers for mock posts.

Each step records whether it was executed for real or only simulated. With
``ACCEPTANCE_REPORT=<path>`` the protocol is written as JSON for the docs.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents import registry
from agents.base import Agent
from agents.master import MasterOrchestratorAgent
from core.config import Settings, get_settings
from core.enums import (
    AgentRunStatus,
    Language,
    MaterialStatus,
    MetricWindow,
    UserRole,
    VideoStatus,
)
from models import (
    Channel,
    Clip,
    Game,
    GameplayFile,
    LearningVersion,
    Scene,
    User,
    Variant,
)
from models.analytics import AnalyticsSnapshot, Metric
from models.control import AgentRun
from models.production import QualityCheck, Script, Subtitle, Voiceover
from models.publishing import Post, PublishingJob, StrategyVersion
from models.trends import Trend
from services import media, orchestrator
from services.controls import update_operations
from tests.conftest import login

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed"),
]

PDF = b"%PDF-1.4\n% acceptance test license\n"


@dataclass
class Step:
    number: int
    title: str
    result: str = "offen"  # bestanden | bestanden (simuliert) | fehlgeschlagen
    mode: str = "echt"  # echt | simuliert | teilweise simuliert
    evidence: list[str] = field(default_factory=list)
    seconds: float = 0.0


@dataclass
class Protocol:
    steps: list[Step] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)

    def step(self, number: int, title: str, mode: str = "echt") -> Step:
        s = Step(number, title, mode=mode)
        self.steps.append(s)
        return s

    def save(self) -> None:
        path = os.environ.get("ACCEPTANCE_REPORT")
        if path:
            Path(path).write_text(
                json.dumps(
                    {
                        "run_at": datetime.now(UTC).isoformat(),
                        "seconds": round(time.monotonic() - self.started, 1),
                        "steps": [asdict(s) for s in self.steps],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(
        update={
            "media_root": str(tmp_path / "media"),
            "render_preset": "ultrafast",
            "trend_sources_mode": "mock",
            "publishing_mode": "mock",
            "auto_publish_enabled": False,
        }
    )


@pytest.fixture
def client(api: TestClient, settings: Settings) -> Iterator[TestClient]:
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    yield api


def _master_into(queued: list[tuple[str, dict[str, Any]]]) -> Callable[[], Agent]:
    return lambda: MasterOrchestratorAgent(submit=lambda n, p: queued.append((n, p)))


def run_master(db: Session, settings: Settings, ticks: int = 40) -> list[str]:
    """Master ticks; every dispatched job runs at once, like a worker would."""
    executed: list[str] = []
    for _ in range(ticks):
        queued: list[tuple[str, dict[str, Any]]] = []
        with registry.override("master", _master_into(queued)):
            orchestrator.run_agent(db, settings, "master", {})
        if not queued:
            break
        for name, payload in queued:
            run = orchestrator.run_agent(db, settings, name, payload)
            assert run.status in (AgentRunStatus.SUCCEEDED, AgentRunStatus.SKIPPED), (
                name,
                run.output,
                run.error,
            )
            executed.append(name)
    return executed


def agent(db: Session, settings: Settings, name: str, payload: dict[str, Any] | None = None) -> Any:
    run = orchestrator.run_agent(db, settings, name, payload or {})
    assert run.status == AgentRunStatus.SUCCEEDED, (name, run.output, run.error)
    return run


def test_spec_section_20_end_to_end(
    client: TestClient,
    db: Session,
    settings: Settings,
    make_user: Callable[..., User],
    tmp_path: Path,
) -> None:
    proto = Protocol()
    try:
        _run(client, db, settings, make_user, tmp_path, proto)
    finally:
        proto.save()


def _run(
    c: TestClient,
    db: Session,
    s: Settings,
    make_user: Callable[..., User],
    tmp_path: Path,
    proto: Protocol,
) -> None:
    from services.seed import seed_base_data

    seed_base_data(db)  # what the "migrate" service does on every deployment
    # The default of 10 production jobs per day is not enough for one material in
    # two languages (about 16 jobs); the operator raises it in the settings.
    update_operations(db, None, {"max_daily_production_jobs": 200})
    make_user("admin@example.com", UserRole.ADMIN)
    h = login(c, "admin@example.com")

    # --- 1. trend -------------------------------------------------------------------
    st = proto.step(1, "Gaming-Trend erkennen", mode="simuliert")
    t0 = time.monotonic()
    agent(db, s, "trend_research")
    agent(db, s, "game_intelligence")
    top = db.execute(
        select(Trend, Game)
        .join(Game, Game.id == Trend.game_id)
        .where(Trend.language == Language.DE)
        .order_by(Trend.score.desc())
        .limit(1)
    ).first()
    assert top is not None
    trend, game = top
    assert trend.is_mock
    assert game.profile and game.profile.get("video_ideas")
    st.evidence += [
        f"Top-Trend (DE): {game.name}, Score {float(trend.score):.1f} – Quelle: Testdaten",
        f"Spielprofil mit {len(game.profile['video_ideas'])} Videoideen",
    ]
    st.result, st.seconds = "bestanden (simuliert)", round(time.monotonic() - t0, 2)

    # --- 2. material ----------------------------------------------------------------
    st = proto.step(2, "Geeignetes Material finden", mode="teilweise simuliert")
    t0 = time.monotonic()
    creator = c.post("/api/creators", json={"name": "Abnahme-Partner"}, headers=h).json()
    source = c.post(
        "/api/sources",
        json={
            "creator_id": creator["id"],
            "type": "licensed_creator",
            "name": "Abnahme-Uploads",
            "url": "https://partner.example.com/vertrag",
        },
        headers=h,
    ).json()
    lic = c.post("/api/licenses", json={"source_id": source["id"]}, headers=h).json()
    video = media.make_test_video(
        s, tmp_path / "gameplay.mp4", width=1920, height=1080, calm_s=15, action_s=20, tail_s=10
    )
    with video.open("rb") as fh:
        up = c.post(
            "/api/materials/upload",
            data={
                "source_id": str(source["id"]),
                "license_id": str(lic["id"]),
                "game_id": str(game.id),
                "title": "Abnahmetest Gameplay",
            },
            files={"file": ("gameplay.mp4", fh, "video/mp4")},
            headers=h,
        )
    assert up.status_code == 201, up.text
    material = db.get(GameplayFile, up.json()["id"])
    assert material is not None and material.status == MaterialStatus.DISCOVERED
    agent(db, s, "material_scout", {"sweep": True})
    st.evidence += [
        "Material ist ein mit FFmpeg erzeugtes Testvideo (1080p, 45 s), hochgeladen über die "
        "echte Upload-API mit technischer Prüfung",
        "Material Scout gleicht Trends mit freigegebenem Material ab (Bedarfsmeldung); er sucht "
        "kein Material im Netz – das ist so gewollt (keine Downloads ohne Rechte)",
    ]

    # --- 3. rights ------------------------------------------------------------------
    st3 = proto.step(3, "Nutzungsrechte prüfen")
    up_doc = c.post(
        f"/api/licenses/{lic['id']}/documents",
        files={"file": ("vertrag.pdf", PDF, "application/pdf")},
        headers=h,
    )
    assert up_doc.status_code == 201, up_doc.text
    terms = {
        "allows_commercial_use": True,
        "allows_editing": True,
        "allows_short_form": True,
        "allows_monetization": True,
        "music_cleared": True,
        "publisher_permission": True,
        "allowed_platforms": ["youtube", "tiktok", "instagram", "facebook"],
        "allowed_languages": ["de", "en"],
    }
    assert c.patch(f"/api/licenses/{lic['id']}", json=terms, headers=h).status_code == 200
    assert c.post(f"/api/licenses/{lic['id']}/approve", headers=h).status_code == 200
    policy = c.put(
        f"/api/games/{game.id}/policy",
        json={"status": "permitted", "notes": "Abnahmetest: Annahme, keine echte Erlaubnis"},
        headers=h,
    )
    assert policy.status_code == 200, policy.text
    executed = run_master(db, s, ticks=3)
    db.refresh(material)
    assert "material_scout" in executed and "rights_license" in executed, executed
    detail = c.get(f"/api/materials/{material.id}").json()
    assert material.status in (MaterialStatus.RIGHTS_APPROVED, MaterialStatus.ANALYZED), detail
    st.result, st.seconds = "bestanden (simuliert)", round(time.monotonic() - t0, 2)
    st3.evidence += [
        "Lizenz mit Nachweis-PDF, Bedingungen und Admin-Freigabe über die API",
        f"Rechteprüfung: alle {len(detail['last_check']['checks'])} Kriterien ok",
        "Publisher-Richtlinie und Erlaubnis sind für den Test angenommen (keine echte Lizenz)",
    ]
    st3.result = "bestanden"

    # --- 4.–9. production -----------------------------------------------------------
    # The operator activates the first YouTube channel of each language (seeded paused)
    # with own bounds of 0–4 posts per day; the agent decides the amount in between.
    for lang in (Language.DE, Language.EN):
        ch = db.scalar(select(Channel).where(Channel.language == lang).order_by(Channel.id))
        assert ch is not None
        ch.is_paused = ch.platform.is_paused = False
        ch.min_posts_per_day, ch.max_posts_per_day = 0, 4
    db.flush()
    t0 = time.monotonic()
    executed = run_master(db, s, ticks=40)
    db.refresh(material)
    assert material.status == MaterialStatus.ANALYZED, material.status
    scenes = list(db.scalars(select(Scene).where(Scene.gameplay_file_id == material.id)))
    clips = list(db.scalars(select(Clip).join(Scene).where(Scene.gameplay_file_id == material.id)))
    variants = list(db.scalars(select(Variant).where(Variant.clip_id.in_([x.id for x in clips]))))
    statuses = sorted({v.status.value for v in variants})
    st = proto.step(4, "Gameplay analysieren")
    st.evidence.append(
        f"Material {material.width}×{material.height}, {material.duration_s} s analysiert"
    )
    st.result = "bestanden"
    st = proto.step(5, "Interessante Szenen erkennen")
    best = max(scenes, key=lambda x: float(x.score))
    st.evidence.append(
        f"{len(scenes)} Szenen bewertet, beste {float(best.score):.2f} bei "
        f"{float(best.start_s):.0f}–{float(best.end_s):.0f} s (Action-Teil ab 15 s)"
    )
    overlap = min(float(best.end_s), 35.0) - max(float(best.start_s), 15.0)
    assert overlap >= 15, "best scene should cover most of the loud action part (15–35 s)"
    st.result = "bestanden"

    st = proto.step(6, "Eigenständige Kurzvideos produzieren")
    rendered = [x for x in clips if x.storage_uri]
    assert rendered, (
        "no clip rendered",
        executed,
        [(float(x.score), x.selected) for x in scenes],
        len(clips),
    )
    st.evidence.append(
        f"{len(rendered)} Clip(s) gerendert ({rendered[0].width}×{rendered[0].height}, H.264/AAC)"
    )
    st.result = "bestanden"

    st = proto.step(7, "Deutsche und englische Fassungen")
    langs = {v.language for v in variants}
    assert langs == {Language.DE, Language.EN}, langs
    scripts = list(
        db.scalars(select(Script).where(Script.variant_id.in_([v.id for v in variants])))
    )
    assert scripts and {sc.language for sc in scripts} == {Language.DE, Language.EN}
    st.evidence.append(
        f"{len(variants)} Varianten (DE und EN), {len(scripts)} Skripte; Texte aus Vorlagen, "
        "kein Sprachmodell (kostenpflichtig, nicht freigegeben)"
    )
    st.result = "bestanden"

    st = proto.step(8, "Voiceover und Untertitel", mode="teilweise simuliert")
    voices = list(
        db.scalars(select(Voiceover).where(Voiceover.variant_id.in_([v.id for v in variants])))
    )
    subs = list(
        db.scalars(select(Subtitle).where(Subtitle.variant_id.in_([v.id for v in variants])))
    )
    assert voices and subs, statuses
    st.evidence += [
        f"{len(voices)} Voiceover-Spuren mit Anbieter „{voices[0].provider}“ – stille "
        "Test-Stimme, keine echte Sprachausgabe",
        f"{len(subs)} Untertitel erzeugt und eingebrannt (echt)",
    ]
    st.result = "bestanden (simuliert)"

    st = proto.step(9, "Qualität kontrollieren")
    checks = list(
        db.scalars(
            select(QualityCheck).where(QualityCheck.variant_id.in_([v.id for v in variants]))
        )
    )
    passed = [q for q in checks if q.passed]
    assert passed, [q.reasons for q in checks]
    st.evidence.append(
        f"{len(checks)} Prüfungen, {len(passed)} bestanden; Status jetzt: {', '.join(statuses)}"
    )
    st.result = "bestanden"
    for n in (4, 5, 6, 7, 8, 9):
        proto.steps[n - 1].seconds = round((time.monotonic() - t0) / 6, 2)

    # --- 10.–11. publishing decision and publishing ----------------------------------
    st = proto.step(10, "Über die Veröffentlichung anhand der Kanalstatistiken entscheiden")
    ready = [v for v in variants if v.status == VideoStatus.READY_TO_PUBLISH]
    assert ready, statuses
    target = db.get(Channel, ready[0].channel_id)
    assert target is not None
    executed = run_master(db, s, ticks=3)  # the master already ran it during production
    strategy_runs = db.scalar(
        select(func.count())
        .select_from(AgentRun)
        .where(AgentRun.agent_name == "publishing_strategy")
    )
    assert strategy_runs, executed
    version = db.scalar(
        select(StrategyVersion)
        .where(StrategyVersion.channel_id == target.id)
        .order_by(StrategyVersion.id.desc())
    )
    assert version is not None
    jobs = list(db.scalars(select(PublishingJob).where(PublishingJob.channel_id == target.id)))
    assert jobs, "strategy planned nothing"
    st.evidence += [
        f"Kanal {target.name}: Strategie-Version {version.version}, "
        f"{version.posts_per_day} Posts/Tag – {' '.join(version.reasons)[:160]}",
        f"{len(jobs)} Auftrag/Aufträge geplant (Modus {jobs[0].mode.value})",
    ]
    st.result = "bestanden"

    st = proto.step(11, "Über autorisierte Plattformzugänge veröffentlichen", mode="simuliert")
    for j in jobs:
        j.scheduled_for = datetime.now(UTC) - timedelta(minutes=1)
    db.flush()
    executed = run_master(db, s, ticks=3)
    posts = list(db.scalars(select(Post).where(Post.channel_id == target.id)))
    assert posts and all(p.is_mock for p in posts), executed
    st.evidence += [
        f"{len(posts)} Test-Post(s) (Mock) über den Publishing Agent; nichts wurde hochgeladen",
        "Echte Veröffentlichung braucht einen autorisierten Kanal und ausdrückliche Freigabe",
    ]
    st.result = "bestanden (simuliert)"

    # --- 12. performance -----------------------------------------------------------
    st = proto.step(12, "Performance erfassen", mode="simuliert")
    for p in posts:
        p.published_at = datetime.now(UTC) - timedelta(hours=2)
    db.flush()
    agent(db, s, "analytics", {"sweep": True})
    measured = list(db.scalars(select(Metric).where(Metric.post_id.in_([p.id for p in posts]))))
    assert measured
    snapshot = db.scalar(select(AnalyticsSnapshot).where(AnalyticsSnapshot.channel_id == target.id))
    assert snapshot is not None
    published_variant = db.get(Variant, posts[0].variant_id)
    assert published_variant is not None
    db.refresh(published_variant)
    assert published_variant.status == VideoStatus.ANALYTICS_PENDING
    st.evidence += [
        f"{len(measured)} Messung(en) im Fenster {measured[0].measure_window.value}: "
        f"{measured[0].views} Aufrufe – synthetische Zahlen für Testposts",
        f"Tagesbericht für den Kanal angelegt; Variante jetzt {published_variant.status.value}",
    ]
    st.result = "bestanden (simuliert)"

    # --- 13.–14. learning and adapted strategy -------------------------------------------
    st13 = proto.step(13, "Aus den Ergebnissen lernen", mode="simuliert")
    history = _history(db, target, game)
    agent(db, s, "learning")
    lv = db.scalar(select(LearningVersion).order_by(LearningVersion.version.desc()))
    assert lv is not None, "learning derived nothing"
    weights = lv.weights.get("game", {})
    assert weights.get(game.name, 1.0) > 1.0, lv.weights
    st13.evidence += [
        f"{history} zusätzliche Test-Posts mit festgelegten Zahlen über 4 Tage angelegt "
        "(echte Daten gibt es noch nicht)",
        f"Lernversion {lv.version} ({lv.status}): {game.name} × {weights[game.name]:.2f}; "
        + "; ".join(lv.reasons[:2]),
    ]
    st13.result = "bestanden (simuliert)"

    st = proto.step(14, "Nächste Veröffentlichungsstrategie anpassen", mode="teilweise simuliert")
    before = version.posts_per_day
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    agent(db, s, "publishing_strategy", {"sweep": True, "channel_id": target.id, "now": tomorrow})
    newest = db.scalar(
        select(StrategyVersion)
        .where(StrategyVersion.channel_id == target.id)
        .order_by(StrategyVersion.id.desc())
    )
    assert newest is not None and newest.id != version.id
    groups = (newest.params or {}).get("groups", {})
    factor = groups.get("game", {}).get(game.name)
    assert factor is not None and factor > 1.0, groups
    st.evidence += [
        f"Neue Strategie-Version {newest.version} für den Folgetag: {newest.posts_per_day} "
        f"Posts/Tag (vorher {before}) – {' '.join(newest.reasons)[:200]}",
        f"Auswahlgewicht für {game.name} in der Strategie: {factor:.2f} (vorher neutral 1,00)",
    ]
    st.result = "bestanden (simuliert)"

    # --- 15. dashboard -------------------------------------------------------------
    st = proto.step(15, "Alle Vorgänge im Dashboard zeigen")
    pages = {
        "/api/overview": None,
        "/api/trends": None,
        f"/api/materials/{material.id}": None,
        "/api/production/clips": None,
        "/api/publishing/plan": None,
        "/api/agents/decisions": None,
        "/api/analytics/overview?days=30": None,
        "/api/analytics/learning": None,
        "/api/costs/summary": None,
        "/api/system/status": None,
        "/api/agents": None,
    }
    for path in pages:
        r = c.get(path)
        assert r.status_code == 200, (path, r.status_code, r.text[:200])
    runs = db.scalar(select(func.count()).select_from(AgentRun)) or 0
    st.evidence += [
        f"{len(pages)} Dashboard-Endpunkte liefern die Daten (HTTP 200)",
        f"{runs} Agentenläufe protokolliert; die Oberfläche selbst prüft der Playwright-Test",
    ]
    st.result = "bestanden"
    assert all(x.result.startswith("bestanden") for x in proto.steps)


def _history(db: Session, channel: Channel, game: Game) -> int:
    """Synthetic past posts: the trend game clearly beats another game on this channel."""
    from tests.integration.test_analytics_learning import make_post  # reuse the factory

    other = db.scalar(select(Game).where(Game.id != game.id).limit(1))
    assert other is not None
    n = 0
    for day in range(4):
        for i in range(5):
            for g, views in ((game, 3000), (other, 800)):
                post, variant = make_post(db, timedelta(days=day + 1, hours=i), mock=True)
                post.channel_id = channel.id
                variant.channel_id = channel.id
                variant.language = channel.language
                clip = db.get(Clip, variant.clip_id)
                assert clip is not None
                scene = db.get(Scene, clip.scene_id)
                assert scene is not None
                material = db.get(GameplayFile, scene.gameplay_file_id)
                assert material is not None
                material.game_id = g.id
                db.add(
                    Metric(
                        post_id=post.id,
                        measure_window=MetricWindow.H24,
                        measured_at=post.published_at,
                        views=views + i * 10,
                        likes=views // 20,
                        comments=views // 200,
                        shares=views // 400,
                        raw={"mock": True},
                    )
                )
                n += 1
    db.flush()
    return n
