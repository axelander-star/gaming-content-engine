"""Mock trend sources: deterministic test data, no network access.

The games are fictional so test data can never be mistaken for real market
data. Values depend only on the date, so a run is reproducible: the same day
always yields the same numbers. Each game has a growth rate; some rise, some
fall, one is "new" (recently released).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import ClassVar

from core.enums import Language
from services.sources.base import KnownGame, Observation, SourceResult

REFERENCE_DAY = date(2026, 1, 1)
CYCLE_DAYS = 28  # growth restarts every 4 weeks so values stay in a sane range
LOOKBACK_DAYS = 7


@dataclass(frozen=True)
class MockGame:
    name: str
    categories: tuple[str, ...]
    twitch_viewers: int
    steam_players: int
    youtube_views: int
    daily_growth: float
    de_share: float  # share of German-speaking interest (0..1)
    release_age_days: int | None = None  # set for new releases
    twitch_game_id: str | None = None
    steam_app_id: int | None = None


CATALOG: tuple[MockGame, ...] = (
    MockGame(
        "Skyforge Arena",
        ("battle_royale", "shooter"),
        85_000,
        120_000,
        4_200_000,
        0.045,
        0.22,
        twitch_game_id="mock-1001",
        steam_app_id=None,
    ),
    MockGame(
        "Iron Tactics",
        ("strategy",),
        12_000,
        40_000,
        600_000,
        0.01,
        0.35,
        twitch_game_id="mock-1002",
    ),
    MockGame(
        "Neon Drift Rivals",
        ("racing",),
        9_000,
        25_000,
        900_000,
        0.06,
        0.30,
        release_age_days=6,
        twitch_game_id="mock-1003",
    ),
    MockGame(
        "Hollow Lantern",
        ("horror", "indie"),
        22_000,
        30_000,
        1_500_000,
        0.03,
        0.18,
        twitch_game_id="mock-1004",
    ),
    MockGame(
        "Kingdoms of Ember",
        ("rpg",),
        40_000,
        150_000,
        2_600_000,
        -0.01,
        0.20,
        twitch_game_id="mock-1005",
    ),
    MockGame(
        "Pitch Masters 27",
        ("sports",),
        30_000,
        90_000,
        3_100_000,
        0.0,
        0.40,
        twitch_game_id="mock-1006",
    ),
    MockGame(
        "Blockwright",
        ("sandbox",),
        55_000,
        70_000,
        5_000_000,
        0.015,
        0.25,
        twitch_game_id="mock-1007",
    ),
    MockGame(
        "Rift Legends",
        ("moba", "strategy"),
        70_000,
        0,
        2_000_000,
        -0.02,
        0.15,
        twitch_game_id="mock-1008",
    ),
    MockGame(
        "Dust & Bullets",
        ("shooter",),
        18_000,
        35_000,
        1_100_000,
        0.035,
        0.27,
        twitch_game_id="mock-1009",
    ),
    MockGame(
        "Paper Moon Café",
        ("indie",),
        3_000,
        8_000,
        250_000,
        0.08,
        0.30,
        release_age_days=3,
        twitch_game_id="mock-1010",
    ),
)


def _noise(*parts: object) -> float:
    """Deterministic factor in [0.95, 1.05]."""
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return 0.95 + (int.from_bytes(digest[:4], "big") % 10_001) / 100_000


def mock_value(base: float, growth: float, day: date, *key: object, days_back: int = 0) -> float:
    """Value on ``day`` (``days_back`` earlier for the comparison value).

    The growth exponent runs in 28-day cycles; the comparison value is taken
    on the same cycle so growth is never distorted by the cycle restart.
    """
    n = (day - REFERENCE_DAY).days % CYCLE_DAYS - days_back
    noise_day = date.fromordinal(day.toordinal() - days_back).isoformat()
    return round(base * (1 + growth) ** n * _noise(*key, noise_day), 1)


def _today(now: datetime | None) -> date:
    return (now or datetime.now(UTC)).date()


class MockSource:
    """One mock source (``youtube``, ``twitch`` or ``steam``)."""

    METRICS: ClassVar[dict[str, str]] = {
        "youtube": "video_views",
        "twitch": "live_viewers",
        "steam": "players",
    }

    def __init__(self, name: str, now: datetime | None = None) -> None:
        if name not in self.METRICS:
            raise ValueError(f"unknown mock source {name}")
        self.name = name
        self._now = now

    def _base(self, game: MockGame) -> int:
        return {
            "youtube": game.youtube_views,
            "twitch": game.twitch_viewers,
            "steam": game.steam_players,
        }[self.name]

    def fetch(self, known: list[KnownGame], languages: list[Language]) -> SourceResult:
        today = _today(self._now)
        result = SourceResult(self.name, requests=1)
        for game in CATALOG:
            base = self._base(game)
            if base <= 0:
                continue  # e.g. not on Steam
            # Steam has no language split; YouTube and Twitch are split by language.
            splits: list[tuple[Language | None, float]] = (
                [(None, 1.0)]
                if self.name == "steam"
                else [
                    (lang, game.de_share if lang == Language.DE else 1 - game.de_share)
                    for lang in languages
                ]
            )
            for lang, share in splits:
                key = (self.name, game.name, lang)
                extra = {"release_age_days": game.release_age_days} if game.release_age_days else {}
                result.observations.append(
                    Observation(
                        source=self.name,
                        game_name=game.name,
                        metric=self.METRICS[self.name],
                        value=mock_value(base * share, game.daily_growth, today, *key),
                        previous_value=mock_value(
                            base * share, game.daily_growth, today, *key, days_back=LOOKBACK_DAYS
                        ),
                        language=lang,
                        twitch_game_id=game.twitch_game_id,
                        steam_app_id=game.steam_app_id,
                        categories=game.categories,
                        is_mock=True,
                        extra=extra,
                    )
                )
        return result
