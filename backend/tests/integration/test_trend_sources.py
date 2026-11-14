"""Live trend sources: safe error texts, token reuse, rate limits, connection status."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis import Redis
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import Language, UserRole
from models import Game, Trend, User
from services import quota, source_status
from services.sources.base import KnownGame, SourceResult
from services.sources.live import (
    TWITCH_TOKEN_KEY,
    SteamSource,
    TwitchSource,
    YouTubeSource,
    describe_error,
)
from tests.conftest import login

pytestmark = pytest.mark.integration

LANGS = [Language.DE, Language.EN]
KEY = "AIza-SECRET-TEST-KEY"
TWITCH_SECRET = "twitch-secret-value"


def settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {
        "youtube_api_key": SecretStr(KEY),
        "twitch_client_id": "cid",
        "twitch_client_secret": SecretStr(TWITCH_SECRET),
    }
    return get_settings().model_copy(update={**base, **kw})


def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_env_example_lists_each_credential_once() -> None:
    from pathlib import Path

    text = (Path(__file__).parents[3] / ".env.example").read_text()
    names = [line.split("=")[0] for line in text.splitlines() if "=" in line and line[0] != "#"]
    for var in ("YOUTUBE_API_KEY", "TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET"):
        assert names.count(var) == 1, var


def test_empty_env_value_does_not_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUTUBE_DAILY_QUOTA_UNITS", "")
    assert Settings().youtube_daily_quota_units == 2000


def test_describe_error_never_leaks_url_or_key() -> None:
    req = httpx.Request("GET", f"https://www.googleapis.com/youtube/v3/videos?key={KEY}")
    resp = httpx.Response(
        403, request=req, json={"error": {"errors": [{"reason": "quotaExceeded"}]}}
    )
    exc = httpx.HTTPStatusError("boom " + str(req.url), request=req, response=resp)
    text = describe_error(exc)
    assert text == "HTTP 403 Zugriff verweigert (quotaExceeded)"
    assert KEY not in text and "googleapis" not in text
    twitch = httpx.Response(401, request=req, json={"message": "invalid client secret"})
    assert "Zugangsdaten ungültig" in describe_error(
        httpx.HTTPStatusError("x", request=req, response=twitch)
    )
    assert describe_error(httpx.ConnectTimeout("t", request=req)) == "Zeitüberschreitung"


def test_twitch_token_is_reused(redis_client: Redis) -> None:
    hosts: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        hosts.append(req.url.host)
        if req.url.host == "id.twitch.tv":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 5_000_000})
        return httpx.Response(200, json={"data": [{"id": "1", "name": "Real Game"}]})

    src = TwitchSource(settings(), redis_client, client(handler))
    assert src.check().detail == "Verbunden. Meistgeschautes Spiel gerade: Real Game"
    assert src.check().requests == 1  # second test needs no new token
    assert hosts.count("id.twitch.tv") == 1
    assert redis_client.ttl(TWITCH_TOKEN_KEY) > 0


def test_twitch_401_drops_cached_token_and_reports(redis_client: Redis) -> None:
    redis_client.set(TWITCH_TOKEN_KEY, "old")

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid OAuth token"})

    result = TwitchSource(settings(), redis_client, client(handler)).check()
    assert result.errors == ["HTTP 401 Zugangsdaten ungültig (Invalid OAuth token)"]
    assert redis_client.get(TWITCH_TOKEN_KEY) is None
    assert TWITCH_SECRET not in json.dumps(result.errors)


def test_twitch_rate_limit_stops_run(redis_client: Redis) -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if req.url.host == "id.twitch.tv":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 5_000_000})
        if req.url.path.endswith("/games/top"):
            return httpx.Response(
                200, json={"data": [{"id": str(i), "name": f"G{i}"} for i in range(5)]}
            )
        return httpx.Response(429, json={"message": "Too Many Requests"})

    result = TwitchSource(settings(), redis_client, client(handler)).fetch([], LANGS)
    assert calls == 3  # token, top games, first streams call -> stop
    assert result.errors == ["twitch: Rate Limit erreicht, Lauf beendet"]


def test_youtube_invalid_key_stops_after_first_call(redis_client: Redis) -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": {"errors": [{"reason": "keyInvalid"}]}})

    result = YouTubeSource(settings(), redis_client, client(handler)).fetch(
        [KnownGame("Real Game")], LANGS
    )
    assert calls == 1
    assert result.errors == ["de: HTTP 400 (keyInvalid)"]
    assert KEY not in json.dumps(result.errors)


def test_youtube_check_uses_one_unit(redis_client: Redis) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["maxResults"] == "1" and req.method == "GET"
        return httpx.Response(200, json={"items": [{"snippet": {"title": "Top Clip"}}]})

    result = YouTubeSource(settings(), redis_client, client(handler)).check()
    assert result.detail == "Verbunden. Beliebtestes Gaming-Video (DE): Top Clip"
    assert quota.used(redis_client, "youtube") == 1
    full = settings(youtube_daily_quota_units=1)
    over = YouTubeSource(full, redis_client, client(handler)).check()
    assert over.errors and "quota" in over.errors[0]


def test_steam_check(redis_client: Redis) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": {"player_count": 1234567, "result": 1}})

    result = SteamSource(settings(), redis_client, client(handler)).check()
    assert result.detail == "Verbunden. Counter-Strike 2 hat gerade 1.234.567 Spieler"


def test_missing_credentials_are_skipped_without_requests(redis_client: Redis) -> None:
    empty = settings(youtube_api_key=SecretStr(""), twitch_client_secret=SecretStr(""))

    def handler(req: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    for src in (YouTubeSource, TwitchSource):
        assert src(empty, redis_client, client(handler)).check().skipped


def test_status_record_and_overview(redis_client: Redis) -> None:
    s = settings(twitch_client_secret=SecretStr(""))
    ok = SourceResult("youtube", requests=2, detail="fine")
    source_status.record(redis_client, ok, "live")
    failed = SourceResult("youtube", requests=1, errors=["HTTP 403 Zugriff verweigert"])
    entry = source_status.record(redis_client, failed, "live")
    assert entry["state"] == "error" and entry["last_ok_at"] is not None
    rows = {r["name"]: r for r in source_status.overview(s, redis_client)}
    assert rows["youtube"]["configured"] and not rows["twitch"]["configured"]
    assert rows["steam"]["configured"]  # no key needed
    assert rows["youtube"]["last"]["errors"] == ["HTTP 403 Zugriff verweigert"]
    assert KEY not in json.dumps(rows)
    assert rows["youtube"]["quota_limit"] == s.youtube_daily_quota_units


def test_trend_run_records_status(db: Session, redis_client: Redis) -> None:
    from agents import registry
    from agents.trend_research import TrendResearchAgent
    from services import orchestrator

    with registry.override("trend_research", TrendResearchAgent):
        orchestrator.run_agent(db, get_settings(), "trend_research", {})
    rows = {r["name"]: r for r in source_status.overview(get_settings(), redis_client)}
    assert all(rows[n]["last"]["state"] == "mock" for n in ("youtube", "twitch", "steam"))
    assert rows["youtube"]["last"]["last_ok_at"] is None  # a mock run is never a connection
    assert rows["twitch"]["last"]["mode"] == "mock"


# --- API --------------------------------------------------------------------------


def test_sources_api_and_admin_only_test(
    api: TestClient,
    redis_client: Redis,
    make_user: Callable[..., User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_user("viewer@example.com", UserRole.VIEWER)
    make_user("admin@example.com", UserRole.ADMIN)
    h = login(api, "viewer@example.com")
    rows = api.get("/api/trends/sources").json()
    assert [r["name"] for r in rows] == ["youtube", "twitch", "steam"]
    assert api.post("/api/trends/sources/steam/test", headers=h).status_code == 403
    api.post("/api/auth/logout", headers=h)

    def fake_check(self: SteamSource) -> SourceResult:
        return SourceResult("steam", requests=1, detail="Verbunden. Test")

    monkeypatch.setattr(SteamSource, "check", fake_check)
    ha = login(api, "admin@example.com")
    r = api.post("/api/trends/sources/steam/test", headers=ha)
    assert r.status_code == 200, r.text
    assert r.json()["last"]["state"] == "ok" and r.json()["last"]["kind"] == "test"
    assert api.post("/api/trends/sources/nope/test", headers=ha).status_code == 422


def test_game_history(api: TestClient, db: Session, make_user: Callable[..., User]) -> None:
    make_user("viewer@example.com", UserRole.VIEWER)
    game = Game(name="History Game", slug="history-game")
    db.add(game)
    db.flush()
    now = datetime.now(UTC)
    for i, views in enumerate((100.0, 150.0, 300.0)):
        db.add(
            Trend(
                game_id=game.id,
                source="youtube",
                language=Language.DE,
                score=Decimal(40 + i * 10),
                detected_at=now - timedelta(days=3 - i),
                metrics={
                    "per_source": {
                        "youtube": {"metric": "video_views", "value": views, "growth_pct": 50.0}
                    }
                },
            )
        )
    db.add(
        Trend(
            game_id=game.id,
            source="youtube",
            language=Language.DE,
            score=Decimal(10),
            detected_at=now - timedelta(days=90),
        )
    )
    db.flush()
    login(api, "viewer@example.com")
    points = api.get(f"/api/games/{game.id}/history?language=de&days=30").json()
    assert [p["metrics"]["video_views"] for p in points] == [100.0, 150.0, 300.0]
    assert [p["score"] for p in points] == [40.0, 50.0, 60.0]
    assert api.get(f"/api/games/{game.id}/history?language=en").json() == []
    assert api.get("/api/games/999999/history").status_code == 404
