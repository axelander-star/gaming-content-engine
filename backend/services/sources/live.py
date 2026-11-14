"""Live trend sources using official, documented endpoints only.

They run only with ``TREND_SOURCES_MODE=live`` and the operator's own keys.
Every request is counted against a daily quota in Redis first. None of these
endpoints costs money; the quota protects the provider limits.

Endpoints (verify against current provider docs before enabling, see
docs/API_INTEGRATIONS.md):

* Twitch Helix: ``POST https://id.twitch.tv/oauth2/token`` (client credentials),
  ``GET https://api.twitch.tv/helix/games/top``,
  ``GET https://api.twitch.tv/helix/streams?game_id=…``
* Steam Web API: ``GET https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/``
* YouTube Data API v3: ``GET https://www.googleapis.com/youtube/v3/videos``
  with ``chart=mostPopular`` and the gaming category (1 quota unit per call)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from redis import Redis

from core.config import Settings
from core.enums import Language
from services import quota
from services.sources.base import KnownGame, Observation, QuotaExceededError, SourceResult

log = logging.getLogger("trend_sources")

TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"  # noqa: S105 - URL, not a secret
TWITCH_API = "https://api.twitch.tv/helix"
STEAM_PLAYERS_URL = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_GAMING_CATEGORY = "20"
YOUTUBE_REGION = {Language.DE: "DE", Language.EN: "US"}

# Generous daily caps for the free APIs; the per-run limits in Settings are stricter.
TWITCH_DAILY_REQUESTS = 2000
STEAM_DAILY_REQUESTS = 2000


def _client(settings: Settings, client: httpx.Client | None) -> httpx.Client:
    return client or httpx.Client(timeout=settings.http_timeout_s)


class TwitchSource:
    name = "twitch"

    def __init__(self, settings: Settings, redis: Redis, client: httpx.Client | None = None):
        self.s, self.redis, self.http = settings, redis, _client(settings, client)

    def _request(self, method: str, url: str, **kw: Any) -> dict[str, Any]:
        quota.consume(self.redis, self.name, 1, TWITCH_DAILY_REQUESTS)
        r = self.http.request(method, url, **kw)
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        return data

    def fetch(self, known: list[KnownGame], languages: list[Language]) -> SourceResult:
        result = SourceResult(self.name)
        secret = self.s.twitch_client_secret.get_secret_value()
        if not self.s.twitch_client_id or not secret:
            result.skipped = "TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET not set"
            return result
        budget = self.s.twitch_max_requests_per_run
        try:
            token = self._request(
                "POST",
                TWITCH_TOKEN_URL,
                data={
                    "client_id": self.s.twitch_client_id,
                    "client_secret": secret,
                    "grant_type": "client_credentials",
                },
            )["access_token"]
            headers = {"Client-Id": self.s.twitch_client_id, "Authorization": f"Bearer {token}"}
            result.requests += 1
            top_n = max(0, min(20, budget - 2))
            games = self._request(
                "GET", f"{TWITCH_API}/games/top", params={"first": top_n}, headers=headers
            )["data"]
            result.requests += 1
            wanted = {lang.value for lang in languages}
            for game in games:
                if result.requests >= budget:
                    break
                streams = self._request(
                    "GET",
                    f"{TWITCH_API}/streams",
                    params={"game_id": game["id"], "first": 100},
                    headers=headers,
                )["data"]
                result.requests += 1
                viewers: dict[str, int] = {}
                for stream in streams:
                    lang = stream.get("language")
                    if lang in wanted:
                        viewers[lang] = viewers.get(lang, 0) + int(stream.get("viewer_count", 0))
                for lang_code, count in viewers.items():
                    result.observations.append(
                        Observation(
                            source=self.name,
                            game_name=game["name"],
                            metric="live_viewers",
                            value=float(count),
                            language=Language(lang_code),
                            twitch_game_id=str(game["id"]),
                            extra={"sample": "top 100 streams"},
                        )
                    )
        except (httpx.HTTPError, KeyError, ValueError, QuotaExceededError) as exc:
            result.errors.append(f"{type(exc).__name__}: {exc}")
        return result


class SteamSource:
    name = "steam"

    def __init__(self, settings: Settings, redis: Redis, client: httpx.Client | None = None):
        self.s, self.redis, self.http = settings, redis, _client(settings, client)

    def fetch(self, known: list[KnownGame], languages: list[Language]) -> SourceResult:
        result = SourceResult(self.name)
        apps = [g for g in known if g.steam_app_id][: self.s.steam_max_requests_per_run]
        if not apps:
            result.skipped = "no games with a Steam app id yet"
            return result
        for game in apps:
            try:
                quota.consume(self.redis, self.name, 1, STEAM_DAILY_REQUESTS)
                r = self.http.get(STEAM_PLAYERS_URL, params={"appid": game.steam_app_id})
                result.requests += 1
                r.raise_for_status()
                body = r.json()["response"]
                if body.get("result") != 1:
                    result.errors.append(f"app {game.steam_app_id}: result {body.get('result')}")
                    continue
                result.observations.append(
                    Observation(
                        source=self.name,
                        game_name=game.name,
                        metric="players",
                        value=float(body["player_count"]),
                        steam_app_id=game.steam_app_id,
                    )
                )
            except QuotaExceededError as exc:
                result.errors.append(str(exc))
                break
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                result.errors.append(f"app {game.steam_app_id}: {type(exc).__name__}: {exc}")
        return result


class YouTubeSource:
    """Most popular gaming videos per region, attributed to known games by title/tags."""

    name = "youtube"
    UNITS_PER_CALL = 1

    def __init__(self, settings: Settings, redis: Redis, client: httpx.Client | None = None):
        self.s, self.redis, self.http = settings, redis, _client(settings, client)

    def fetch(self, known: list[KnownGame], languages: list[Language]) -> SourceResult:
        result = SourceResult(self.name)
        key = self.s.youtube_api_key.get_secret_value()
        if not key:
            result.skipped = "YOUTUBE_API_KEY not set"
            return result
        if not known:
            result.skipped = "no known games to match video titles against"
            return result
        for lang in languages:
            try:
                quota.consume(
                    self.redis, self.name, self.UNITS_PER_CALL, self.s.youtube_daily_quota_units
                )
                r = self.http.get(
                    YOUTUBE_VIDEOS_URL,
                    params={
                        "part": "snippet,statistics",
                        "chart": "mostPopular",
                        "videoCategoryId": YOUTUBE_GAMING_CATEGORY,
                        "regionCode": YOUTUBE_REGION[lang],
                        "maxResults": 50,
                        "key": key,
                    },
                )
                result.requests += 1
                r.raise_for_status()
                items = r.json().get("items", [])
            except QuotaExceededError as exc:
                result.errors.append(str(exc))
                break
            except (httpx.HTTPError, ValueError) as exc:
                # Never log the URL: it contains the API key.
                result.errors.append(f"{lang.value}: {type(exc).__name__}")
                continue
            views: dict[str, float] = {}
            for item in items:
                snippet = item.get("snippet", {})
                text = " ".join([snippet.get("title", ""), *snippet.get("tags", [])]).lower()
                for game in known:
                    if game.name.lower() in text:
                        count = float(item.get("statistics", {}).get("viewCount", 0))
                        views[game.name] = views.get(game.name, 0.0) + count
                        break
            for name, total in views.items():
                result.observations.append(
                    Observation(
                        source=self.name,
                        game_name=name,
                        metric="video_views",
                        value=total,
                        language=lang,
                        extra={"sample": "most popular gaming videos"},
                    )
                )
        return result
