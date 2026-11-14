"""Phase 5: trend sources, scoring, reports, Game Intelligence and trends API."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents import registry
from agents.game_intelligence import GameIntelligenceAgent
from agents.trend_research import TrendResearchAgent
from core.config import Settings, get_settings
from core.enums import AgentRunStatus, Language, MetricWindow, PublishingMode, UserRole
from models import (
    AgentDecision,
    Game,
    Metric,
    Post,
    PublishingJob,
    Trend,
    TrendReport,
    User,
    Variant,
)
from services import orchestrator, quota, trends
from services.sources import get_sources
from services.sources.base import KnownGame, QuotaExceededError
from services.sources.live import SteamSource, TwitchSource, YouTubeSource
from services.sources.mock import CATALOG, MockSource
from tests.conftest import login
from tests.factories import build_chain

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
LANGS = [Language.DE, Language.EN]


def fixed_sources(settings: Settings) -> list[Any]:
    return list(get_sources(settings, None, now=NOW))


def research(db: Session) -> Any:
    with registry.override("trend_research", lambda: TrendResearchAgent(fixed_sources)):
        return orchestrator.run_agent(db, get_settings(), "trend_research", {})


def latest(db: Session, language: Language) -> dict[str, Trend]:
    rows = trends.latest_trends(db, language, 50)
    names = {g.id: g.name for g in db.scalars(select(Game))}
    return {names[r.game_id]: r for r in rows}


# --- mock sources -----------------------------------------------------------


def test_mock_sources_are_deterministic() -> None:
    a = MockSource("twitch", NOW).fetch([], LANGS)
    b = MockSource("twitch", NOW).fetch([], LANGS)
    assert a.observations == b.observations
    assert len(a.observations) == len(CATALOG) * 2
    steam = MockSource("steam", NOW).fetch([], LANGS)
    assert all(o.language is None for o in steam.observations)
    assert all(o.is_mock and o.previous_value for o in steam.observations)
    with pytest.raises(ValueError):
        MockSource("myspace")


def test_mock_mode_never_builds_live_sources() -> None:
    names = [type(s).__name__ for s in get_sources(get_settings())]
    assert names == ["MockSource"] * 3
    with pytest.raises(ValueError):
        get_sources(get_settings().model_copy(update={"trend_sources_mode": "live"}))


# --- trend research ---------------------------------------------------------


def test_trend_research_scores_and_reports(db: Session) -> None:
    run = research(db)
    assert run.status == AgentRunStatus.SUCCEEDED, run.error
    assert run.output["trends"] == len(CATALOG) * 2
    games = db.scalars(select(Game)).all()
    assert len(games) == len(CATALOG) and all(g.is_test_data for g in games)

    de, en = latest(db, Language.DE), latest(db, Language.EN)
    assert set(de) == {g.name for g in CATALOG}
    # New releases are flagged, a shrinking game shows negative growth.
    assert de["Neon Drift Rivals"].metrics["is_new"] and de["Paper Moon Café"].metrics["is_new"]
    assert not de["Kingdoms of Ember"].metrics["is_new"]
    ember = de["Kingdoms of Ember"].metrics["per_source"]["twitch"]
    assert ember["growth_pct"] < 0
    # Language fit follows the interest split: Pitch Masters is stronger in DE than Rift Legends.
    fit = lambda t: t.metrics["components"]["language_fit"]  # noqa: E731
    assert fit(de["Pitch Masters 27"]) > fit(de["Rift Legends"])
    assert fit(en["Rift Legends"]) == 1.0
    # No own videos yet -> neutral and flagged as unknown.
    assert "own_performance" in de["Skyforge Arena"].metrics["unknown"]
    assert de["Skyforge Arena"].is_mock

    reports = db.scalars(select(TrendReport).order_by(TrendReport.id)).all()
    assert [r.language for r in reports] == [Language.DE, Language.EN]
    assert reports[0].summary.startswith("Testdaten.") and reports[0].is_mock
    assert len(reports[0].items) == trends.REPORT_SIZE
    assert reports[0].items[0]["score"] >= reports[0].items[-1]["score"]
    assert "action" in reports[0].by_audience
    decision = db.scalar(
        select(AgentDecision).where(AgentDecision.decision_type == "trend_report").limit(1)
    )
    assert decision is not None and "Weights" in (decision.reasoning or "")


def test_trend_research_is_reproducible(db: Session) -> None:
    research(db)
    first = [(n, float(t.score)) for n, t in latest(db, Language.DE).items()]
    research(db)
    second = [(n, float(t.score)) for n, t in latest(db, Language.DE).items()]
    assert sorted(first) == sorted(second)
    assert db.scalar(select(func.count(Game.id))) == len(CATALOG)  # no duplicate games


def test_no_source_data_records_decision(db: Session) -> None:
    class Empty:
        name = "twitch"

        def fetch(self, known: list[KnownGame], languages: list[Language]) -> Any:
            from services.sources.base import SourceResult

            return SourceResult("twitch", skipped="no keys")

    with registry.override("trend_research", lambda: TrendResearchAgent(lambda s: [Empty()])):
        run = orchestrator.run_agent(db, get_settings(), "trend_research", {})
    assert run.status == AgentRunStatus.SUCCEEDED and run.output["trends"] == 0
    assert run.output["sources"]["twitch"]["skipped"] == "no keys"


def test_own_performance_counts_real_posts_only(db: Session) -> None:
    chain = build_chain(db)
    other = build_chain(db)
    extra = Variant(
        clip_id=other.clip.id, channel_id=other.channel.id, language=Language.DE, variant_label="B"
    )
    db.add(extra)
    db.flush()
    for variant, views, mock in (
        (chain.variant, 3000, False),
        (other.variant, 1000, False),
        (extra, 10**9, True),  # mock posts never count
    ):
        job = PublishingJob(
            variant_id=variant.id,
            channel_id=variant.channel_id,
            mode=PublishingMode.MOCK,
            idempotency_key=f"k-{variant.id}",
        )
        db.add(job)
        db.flush()
        post = Post(
            publishing_job_id=job.id,
            variant_id=variant.id,
            channel_id=variant.channel_id,
            is_mock=mock,
        )
        db.add(post)
        db.flush()
        db.add(Metric(post_id=post.id, measure_window=MetricWindow.H24, views=views))
    db.flush()
    perf = trends.own_performance(db, Language.DE)
    game_a = chain.gameplay_file.game_id
    game_b = other.gameplay_file.game_id
    assert game_a is not None and game_b is not None
    assert perf[game_a] == 0.75 and perf[game_b] == 0.25  # 3000 vs. 1000, mock post ignored
    assert trends.own_performance(db, Language.EN) == {}


# --- game intelligence ------------------------------------------------------


def test_game_intelligence_builds_profiles(db: Session) -> None:
    research(db)
    run = orchestrator.run_agent(db, get_settings(), "game_intelligence", {})
    assert run.status == AgentRunStatus.SUCCEEDED, run.error
    assert run.output["count"] == len(CATALOG)
    game = db.scalar(select(Game).where(Game.name == "Skyforge Arena"))
    assert game is not None and game.profiled_at is not None
    profile = game.profile
    assert profile["audience"]["key"] == "action"
    assert "Squad" in profile["modes"]
    assert len(profile["video_ideas"]) == 4
    assert profile["video_ideas"][0]["title_de"].endswith("Skyforge Arena")
    assert profile["channel_performance"]["de"]["basis"] == "no_data"
    assert profile["rating"] is not None and profile["method"] == "rules"
    # Profiles are fresh -> nothing to do; force refreshes all.
    again = orchestrator.run_agent(db, get_settings(), "game_intelligence", {})
    assert again.output["count"] == 0
    forced = GameIntelligenceAgent()
    with registry.override("game_intelligence", lambda: forced):
        run = orchestrator.run_agent(db, get_settings(), "game_intelligence", {"force": True})
    assert run.output["count"] == len(CATALOG)


# --- live adapters (with a fake HTTP transport) -----------------------------


def live_settings(**kw: Any) -> Settings:
    return get_settings().model_copy(update={"trend_sources_mode": "live", **kw})


def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_twitch_adapter(redis_client: Redis) -> None:
    from pydantic import SecretStr

    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if req.url.host == "id.twitch.tv":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 1})
        assert req.headers["Client-Id"] == "cid" and req.headers["Authorization"] == "Bearer t"
        if req.url.path.endswith("/games/top"):
            return httpx.Response(200, json={"data": [{"id": "33", "name": "Real Game"}]})
        return httpx.Response(
            200,
            json={
                "data": [
                    {"viewer_count": 100, "language": "de"},
                    {"viewer_count": 50, "language": "de"},
                    {"viewer_count": 70, "language": "en"},
                    {"viewer_count": 999, "language": "fr"},
                ]
            },
        )

    s = live_settings(twitch_client_id="cid", twitch_client_secret=SecretStr("sec"))
    result = TwitchSource(s, redis_client, client(handler)).fetch([], LANGS)
    assert result.errors == [] and result.requests == 3
    values = {(o.language, o.value) for o in result.observations}
    assert values == {(Language.DE, 150.0), (Language.EN, 70.0)}
    assert quota.used(redis_client, "twitch") == 3

    missing = TwitchSource(live_settings(), redis_client, client(handler)).fetch([], LANGS)
    assert missing.skipped and missing.requests == 0


def test_steam_adapter(redis_client: Redis) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.params["appid"] == "1":
            return httpx.Response(200, json={"response": {"player_count": 1234, "result": 1}})
        return httpx.Response(200, json={"response": {"result": 42}})

    known = [KnownGame("A", steam_app_id=1), KnownGame("B", steam_app_id=2), KnownGame("C")]
    result = SteamSource(live_settings(), redis_client, client(handler)).fetch(known, LANGS)
    assert [o.value for o in result.observations] == [1234.0]
    assert result.errors and result.requests == 2
    assert SteamSource(live_settings(), redis_client, client(handler)).fetch([], LANGS).skipped


def test_youtube_adapter_matches_titles_and_hides_key(redis_client: Redis) -> None:
    from pydantic import SecretStr

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["chart"] == "mostPopular"
        if req.url.params["regionCode"] == "US":
            return httpx.Response(403, json={"error": "quota"})
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "snippet": {"title": "Real Game Highlights", "tags": []},
                        "statistics": {"viewCount": "500"},
                    },
                    {
                        "snippet": {"title": "Vlog", "tags": ["real game"]},
                        "statistics": {"viewCount": "100"},
                    },
                    {"snippet": {"title": "Unrelated"}, "statistics": {"viewCount": "9"}},
                ]
            },
        )

    s = live_settings(youtube_api_key=SecretStr("SECRET-KEY"))
    result = YouTubeSource(s, redis_client, client(handler)).fetch([KnownGame("Real Game")], LANGS)
    assert [(o.language, o.value) for o in result.observations] == [(Language.DE, 600.0)]
    assert result.errors and "SECRET-KEY" not in json.dumps(result.errors)
    no_key = YouTubeSource(live_settings(), redis_client, client(handler)).fetch([], LANGS)
    assert no_key.skipped


def test_quota_limit(redis_client: Redis) -> None:
    assert quota.consume(redis_client, "youtube", 2, 3) == 2
    with pytest.raises(QuotaExceededError):
        quota.consume(redis_client, "youtube", 2, 3)
    assert quota.used(redis_client, "youtube") == 2


# --- API --------------------------------------------------------------------


def test_trends_api(api: TestClient, db: Session, make_user: Callable[..., User]) -> None:
    make_user(role=UserRole.VIEWER, email="v@example.com")
    login(api, "v@example.com")
    assert api.get("/api/trends").json() == []
    assert api.get("/api/trends/report").json() is None
    research(db)
    orchestrator.run_agent(db, get_settings(), "game_intelligence", {})
    items = api.get("/api/trends?language=en&limit=5").json()
    assert len(items) == 5 and items[0]["score"] >= items[-1]["score"]
    assert items[0]["is_mock"] and items[0]["top_idea"]
    report = api.get("/api/trends/report?language=de").json()
    assert report["language"] == "de" and report["items"]
    games = api.get("/api/games").json()
    assert len(games) == len(CATALOG)
    one = api.get(f"/api/games/{games[0]['id']}").json()
    assert one["profile"]["video_ideas"]
    assert api.get("/api/games/999999").status_code == 404


def test_game_appearing_after_first_run_is_new(db: Session) -> None:
    from services.sources.base import Observation

    research(db)
    late = Observation(
        source="twitch",
        game_name="Brand New Game",
        metric="live_viewers",
        value=500.0,
        language=Language.DE,
        categories=("indie",),
    )
    scored = trends.score_observations(db, [late], [Language.DE])
    assert scored[0].is_new and scored[0].unknown == ["growth", "own_performance"]
