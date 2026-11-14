"""Trend scoring, persistence and trend reports (Trend Research agent).

Score (0–100) per game and language, weighted sum of components in [0, 1]:

=================  ======  ==============================================
component          weight  meaning
=================  ======  ==============================================
volume             0.40    audience size relative to the biggest game of the source
                           (log scale over three orders of magnitude)
growth             0.30    change against the previous measurement
language_fit       0.15    interest in this language vs. the other one
own_performance    0.10    how our own videos of the game performed
novelty            0.05    new release / newly appeared game
=================  ======  ==============================================

Unknown components (e.g. no own videos yet) count as neutral 0.5 and are
flagged, so a missing value never looks like a good or a bad signal.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.catalog import audience_for
from core.enums import Language
from models.analytics import Metric
from models.production import Clip, GameplayFile, Scene, Variant
from models.publishing import Post
from models.trends import Game, Trend, TrendReport
from services.sources.base import Observation

WEIGHTS = {
    "volume": 0.40,
    "growth": 0.30,
    "language_fit": 0.15,
    "own_performance": 0.10,
    "novelty": 0.05,
}
NEUTRAL = 0.5
VOLUME_DECADES = 3
NEW_GAME_DAYS = 14
REPORT_SIZE = 10


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:200] or "game"


@dataclass
class ScoredTrend:
    game: Game
    language: Language
    score: float
    components: dict[str, float]
    unknown: list[str]
    per_source: dict[str, dict[str, Any]]
    audience: str
    is_mock: bool
    is_new: bool

    @property
    def growth_pct(self) -> float | None:
        rates = [s["growth_pct"] for s in self.per_source.values() if s["growth_pct"] is not None]
        return round(sum(rates) / len(rates), 1) if rates else None


# --- games ------------------------------------------------------------------


def resolve_games(
    session: Session, observations: list[Observation], now: datetime | None = None
) -> dict[str, Game]:
    """Find or create the game of every observation; returns game name -> Game."""
    games: dict[str, Game] = {}
    for obs in observations:
        game = games.get(obs.game_name) or _find_game(session, obs) or _new_game(session, obs, now)
        games[obs.game_name] = game
        if obs.twitch_game_id and not game.twitch_game_id:
            game.twitch_game_id = obs.twitch_game_id
        if obs.steam_app_id and not game.steam_app_id:
            game.steam_app_id = obs.steam_app_id
        if obs.categories and not game.categories:
            game.categories = list(obs.categories)
    session.flush()
    return games


def _new_game(session: Session, obs: Observation, now: datetime | None) -> Game:
    game = Game(
        created_at=now or datetime.now(UTC),  # first seen (explicit: DB now() is per transaction)
        name=obs.game_name[:200],
        slug=slugify(obs.game_name),
        categories=list(obs.categories),
        is_test_data=obs.is_mock,
    )
    session.add(game)
    session.flush()
    return game


def _find_game(session: Session, obs: Observation) -> Game | None:
    if obs.twitch_game_id:
        game = session.scalar(select(Game).where(Game.twitch_game_id == obs.twitch_game_id))
        if game:
            return game
    if obs.steam_app_id:
        game = session.scalar(select(Game).where(Game.steam_app_id == obs.steam_app_id))
        if game:
            return game
    return session.scalar(select(Game).where(Game.slug == slugify(obs.game_name)))


# --- own performance --------------------------------------------------------


def own_performance(session: Session, language: Language) -> dict[int, float]:
    """Average views per real post of each game relative to the average of all games.

    Returns component values in [0, 1] (1.0 = twice the average or better).
    Games without real posts are missing from the result (= unknown).
    """
    per_post = (
        select(
            GameplayFile.game_id.label("game_id"),
            Post.id.label("post_id"),
            func.max(Metric.views).label("views"),
        )
        .join(Scene, Scene.gameplay_file_id == GameplayFile.id)
        .join(Clip, Clip.scene_id == Scene.id)
        .join(Variant, Variant.clip_id == Clip.id)
        .join(Post, Post.variant_id == Variant.id)
        .join(Metric, Metric.post_id == Post.id)
        .where(Post.is_mock.is_(False), Variant.language == language, Metric.views.is_not(None))
        .group_by(GameplayFile.game_id, Post.id)
        .subquery()
    )
    rows = session.execute(
        select(per_post.c.game_id, func.avg(per_post.c.views))
        .where(per_post.c.game_id.is_not(None))
        .group_by(per_post.c.game_id)
    ).all()
    if not rows:
        return {}
    averages = {int(gid): float(avg or 0) for gid, avg in rows}
    overall = sum(averages.values()) / len(averages)
    if overall <= 0:
        return dict.fromkeys(averages, 0.0)
    return {gid: min(1.0, avg / overall / 2) for gid, avg in averages.items()}


# --- scoring ----------------------------------------------------------------


def _previous_values(session: Session, game_id: int, language: Language) -> dict[str, float]:
    last = session.scalar(
        select(Trend)
        .where(Trend.game_id == game_id, Trend.language == language)
        .order_by(Trend.detected_at.desc(), Trend.id.desc())
        .limit(1)
    )
    if last is None:
        return {}
    return {
        src: float(v["value"])
        for src, v in (last.metrics or {}).get("per_source", {}).items()
        if isinstance(v, dict) and "value" in v
    }


def _growth_component(rate: float) -> float:
    """Map a growth rate to [0, 1]: -50 % or less -> 0, 0 % -> 0.33, +100 % or more -> 1."""
    return max(0.0, min(1.0, (rate + 0.5) / 1.5))


def _volume_component(value: float, top: float) -> float:
    """1.0 for the biggest game of a source, 0 at a thousandth of it or less."""
    if value <= 0 or top <= 0:
        return 0.0
    return max(0.0, 1 - math.log10(top / value) / VOLUME_DECADES)


@dataclass
class _Bucket:
    values: dict[str, Observation] = field(default_factory=dict)  # source -> observation


def score_observations(
    session: Session,
    observations: list[Observation],
    languages: list[Language],
    now: datetime | None = None,
) -> list[ScoredTrend]:
    """Turn raw observations into scored trends per game and language."""
    now = now or datetime.now(UTC)
    games = resolve_games(session, observations, now)
    # Games that appeared after the very first research run count as newly detected.
    baseline = session.scalar(select(func.min(Trend.detected_at)))

    # language -> game -> source -> observation (language-neutral ones apply to every language)
    buckets: dict[Language, dict[str, _Bucket]] = {lang: defaultdict(_Bucket) for lang in languages}
    # source -> game -> language -> value, for the language fit
    by_lang: dict[str, dict[str, dict[Language, float]]] = defaultdict(lambda: defaultdict(dict))
    for obs in observations:
        targets = languages if obs.language is None else [obs.language]
        for lang in targets:
            if lang in buckets:
                buckets[lang][obs.game_name].values[obs.source] = obs
        if obs.language is not None:
            by_lang[obs.source][obs.game_name][obs.language] = obs.value

    results: list[ScoredTrend] = []
    for lang in languages:
        own = own_performance(session, lang)
        max_by_source: dict[str, float] = defaultdict(float)
        for bucket in buckets[lang].values():
            for src, obs in bucket.values.items():
                max_by_source[src] = max(max_by_source[src], obs.value)
        for name, bucket in buckets[lang].items():
            game = games[name]
            previous = _previous_values(session, game.id, lang)
            per_source: dict[str, dict[str, Any]] = {}
            volumes, growths, fits = [], [], []
            for src, obs in bucket.values.items():
                top = max_by_source[src]
                volume = _volume_component(obs.value, top)
                prev = obs.previous_value if obs.previous_value is not None else previous.get(src)
                rate = (obs.value - prev) / prev if prev else None
                per_source[src] = {
                    "metric": obs.metric,
                    "value": obs.value,
                    "previous": prev,
                    "growth_pct": round(rate * 100, 1) if rate is not None else None,
                }
                volumes.append(volume)
                if rate is not None:
                    growths.append(_growth_component(rate))
                split = by_lang[src].get(name)
                if obs.language is not None and split and max(split.values()) > 0:
                    fits.append(split.get(lang, 0.0) / max(split.values()))
            unknown: list[str] = []
            release_age = next(
                (o.extra.get("release_age_days") for o in bucket.values.values()
                 if o.extra.get("release_age_days") is not None),
                None,
            )  # fmt: skip
            created = game.created_at or now
            is_new = (release_age is not None and release_age <= NEW_GAME_DAYS) or (
                baseline is not None
                and created > baseline
                and now - created <= timedelta(days=NEW_GAME_DAYS)
            )
            components = {
                "volume": sum(volumes) / len(volumes) if volumes else 0.0,
                "growth": sum(growths) / len(growths) if growths else NEUTRAL,
                "language_fit": sum(fits) / len(fits) if fits else NEUTRAL,
                "own_performance": own.get(game.id, NEUTRAL),
                "novelty": 1.0 if is_new else 0.0,
            }
            if not growths:
                unknown.append("growth")
            if not fits:
                unknown.append("language_fit")
            if game.id not in own:
                unknown.append("own_performance")
            score = 100 * sum(WEIGHTS[k] * v for k, v in components.items())
            results.append(
                ScoredTrend(
                    game=game,
                    language=lang,
                    score=round(score, 2),
                    components={k: round(v, 3) for k, v in components.items()},
                    unknown=unknown,
                    per_source=per_source,
                    audience=audience_for(game.categories or [])[0],
                    is_mock=all(o.is_mock for o in bucket.values.values()),
                    is_new=is_new,
                )
            )
    results.sort(key=lambda t: (t.language.value, -t.score, t.game.name))
    return results


# --- persistence and reports ------------------------------------------------


def persist(
    session: Session, scored: list[ScoredTrend], now: datetime | None = None
) -> list[Trend]:
    now = now or datetime.now(UTC)
    rows = []
    for t in scored:
        row = Trend(
            game_id=t.game.id,
            source=",".join(sorted(t.per_source))[:64],
            language=t.language,
            score=Decimal(str(t.score)),
            metrics={
                "per_source": t.per_source,
                "components": t.components,
                "weights": WEIGHTS,
                "unknown": t.unknown,
                "is_new": t.is_new,
            },
            detected_at=now,
            period_start=now - timedelta(days=7),
            period_end=now,
            audience=t.audience,
            is_mock=t.is_mock,
        )
        session.add(row)
        rows.append(row)
    session.flush()
    return rows


def _item(t: ScoredTrend) -> dict[str, Any]:
    key, label_de, label_en = audience_for(t.game.categories or [])
    return {
        "game_id": t.game.id,
        "game": t.game.name,
        "score": t.score,
        "growth_pct": t.growth_pct,
        "components": t.components,
        "unknown": t.unknown,
        "audience": key,
        "audience_label": label_de if t.language == Language.DE else label_en,
        "sources": sorted(t.per_source),
        "is_new": t.is_new,
    }


def build_report(
    session: Session,
    language: Language,
    scored: list[ScoredTrend],
    sources: list[str],
    agent_run_id: int | None,
) -> TrendReport:
    mine = [t for t in scored if t.language == language]
    items = [_item(t) for t in mine[:REPORT_SIZE]]
    by_audience: dict[str, Any] = {}
    for t in mine:
        entry = by_audience.setdefault(
            t.audience, {"label": _item(t)["audience_label"], "games": []}
        )
        if len(entry["games"]) < 3:
            entry["games"].append({"game": t.game.name, "score": t.score})
    is_mock = bool(mine) and all(t.is_mock for t in mine)
    report = TrendReport(
        language=language,
        agent_run_id=agent_run_id,
        sources=sources,
        is_mock=is_mock,
        summary=_summary(language, mine, is_mock),
        items=items,
        by_audience=by_audience,
    )
    session.add(report)
    session.flush()
    return report


def _summary(language: Language, trends: list[ScoredTrend], is_mock: bool) -> str:
    prefix = "Testdaten. " if is_mock else ""
    if not trends:
        return f"{prefix}Keine Trenddaten für {language.value.upper()}."
    top = trends[0]
    parts = [f"Top-Trend ({language.value.upper()}): {top.game.name} mit Score {top.score:.0f}"]
    rising = [t for t in trends if t.growth_pct is not None]
    if rising:
        best = max(rising, key=lambda t: t.growth_pct or 0)
        if (best.growth_pct or 0) > 0:
            parts.append(f"stärkster Anstieg: {best.game.name} (+{best.growth_pct:.0f} %)")
    new = [t.game.name for t in trends if t.is_new]
    if new:
        parts.append("neu: " + ", ".join(new[:3]))
    return prefix + "; ".join(parts) + "."


def latest_trends(session: Session, language: Language, limit: int = 10) -> list[Trend]:
    """Latest trend row per game for ``language``, best score first."""
    latest = (
        select(Trend.game_id, func.max(Trend.id).label("max_id"))
        .where(Trend.language == language)
        .group_by(Trend.game_id)
        .subquery()
    )
    return list(
        session.scalars(
            select(Trend)
            .join(latest, Trend.id == latest.c.max_id)
            .order_by(Trend.score.desc(), Trend.id)
            .limit(limit)
        )
    )
