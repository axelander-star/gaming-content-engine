"""Common types for trend sources.

A source returns *observations*: one measured value for one game from one
source (e.g. live viewers on Twitch). Scoring happens in ``services.trends``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from core.enums import Language


@dataclass(frozen=True)
class KnownGame:
    """A game the system already knows, passed to sources that need ids or names."""

    name: str
    steam_app_id: int | None = None
    twitch_game_id: str | None = None


@dataclass(frozen=True)
class Observation:
    source: str  # youtube | twitch | steam
    game_name: str
    metric: str  # video_views | live_viewers | players
    value: float
    language: Language | None = None  # None = not language specific
    previous_value: float | None = None  # same metric some days earlier, if the source knows it
    twitch_game_id: str | None = None
    steam_app_id: int | None = None
    categories: tuple[str, ...] = ()
    is_mock: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceResult:
    source: str
    observations: list[Observation] = field(default_factory=list)
    requests: int = 0
    errors: list[str] = field(default_factory=list)
    skipped: str | None = None  # reason if the source did not run at all
    detail: str | None = None  # short human-readable outcome (connection test)


class TrendSource(Protocol):
    name: str

    def fetch(self, known: list[KnownGame], languages: list[Language]) -> SourceResult: ...


class QuotaExceededError(RuntimeError):
    """Raised when a source would exceed its configured request or unit budget."""
