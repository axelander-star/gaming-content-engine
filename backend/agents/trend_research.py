"""Agent 2: Trend Research (PROJECT_SPEC section 6).

Collects observations from the configured sources (mock by default), detects
new games, scores the potential of each game per language, sorts trends by
audience and writes one trend report per language.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from redis.exceptions import RedisError
from sqlalchemy import select

from agents.base import Agent, AgentContext, AgentResult
from core.config import Settings
from models.trends import Game
from services import source_status, trends
from services.controls import get_operations
from services.sources import get_sources
from services.sources.base import KnownGame, Observation, TrendSource

SourcesFactory = Callable[[Settings], list[TrendSource]]
log = logging.getLogger("trend_research")


def _record_status(settings: Settings, result: Any) -> None:
    """Connection status for the dashboard; failing to store it never stops the run."""
    try:
        from services.queue import get_redis

        source_status.record(get_redis(), result, settings.trend_sources_mode)
    except RedisError as exc:
        log.warning("could not store source status", extra={"error": str(exc)})


def _default_sources(settings: Settings) -> list[TrendSource]:
    redis = None
    if settings.trend_sources_mode == "live":
        from services.queue import get_redis

        redis = get_redis()
    return get_sources(settings, redis)


class TrendResearchAgent(Agent):
    def __init__(self, sources: SourcesFactory | None = None) -> None:
        self._sources = sources or _default_sources

    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        languages = list(get_operations(ctx.session).languages)
        live = ctx.settings.trend_sources_mode == "live"
        query = select(Game)
        if live:
            query = query.where(Game.is_test_data.is_(False))  # never mix test data into live
        known = [
            KnownGame(g.name, g.steam_app_id, g.twitch_game_id) for g in ctx.session.scalars(query)
        ]

        observations: list[Observation] = []
        report: dict[str, dict[str, Any]] = {}
        for source in self._sources(ctx.settings):
            result = source.fetch(known, languages)
            _record_status(ctx.settings, result)
            report[source.name] = {
                "requests": result.requests,
                "observations": len(result.observations),
                "errors": result.errors[:5],
                "skipped": result.skipped,
            }
            observations.extend(result.observations)
            names = {k.name for k in known}
            for obs in result.observations:  # games found by one source help the next one
                if obs.game_name not in names:
                    known.append(KnownGame(obs.game_name, obs.steam_app_id, obs.twitch_game_id))
                    names.add(obs.game_name)

        if not observations:
            ctx.decide(
                "no_trend_data",
                {"sources": report},
                "No source delivered data; no trends were written.",
            )
            return AgentResult(output={"sources": report, "trends": 0})

        scored = trends.score_observations(ctx.session, observations, languages)
        trends.persist(ctx.session, scored)
        used = sorted({o.source for o in observations})
        output: dict[str, Any] = {"sources": report, "trends": len(scored), "reports": {}}
        for lang in languages:
            rep = trends.build_report(ctx.session, lang, scored, used, ctx.run.id)
            output["reports"][lang.value] = rep.id
            top = rep.items[:3]
            ctx.decide(
                "trend_report",
                {
                    "language": lang.value,
                    "top": [i["game"] for i in top],
                    "scores": [i["score"] for i in top],
                },
                rep.summary + f" Weights: {trends.WEIGHTS}.",
                inputs={"sources": report, "observations": len(observations)},
                entity_type="trend_reports",
                entity_id=rep.id,
            )
        return AgentResult(output=output)
