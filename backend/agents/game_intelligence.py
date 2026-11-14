"""Agent 3: Game Intelligence (PROJECT_SPEC section 6).

Builds a profile for every game with a recent trend: audience, relevant game
modes, video ideas and a rating that includes our own channel performance.
Profiles are refreshed after ``PROFILE_MAX_AGE`` or when the payload says
``{"force": true}``. Works without paid calls (rule-based).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select

from agents.base import Agent, AgentContext, AgentResult
from models.trends import Game, Trend
from services.controls import get_operations
from services.game_intel import build_profile

PROFILE_MAX_AGE = timedelta(days=7)
TREND_WINDOW = timedelta(days=7)
BATCH = 50


class GameIntelligenceAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        now = datetime.now(UTC)
        languages = list(get_operations(ctx.session).languages)
        recent = select(Trend.game_id).where(Trend.detected_at >= now - TREND_WINDOW)
        query = select(Game).where(Game.id.in_(recent))
        if not payload.get("force"):
            query = query.where(
                or_(Game.profiled_at.is_(None), Game.profiled_at < now - PROFILE_MAX_AGE)
            )
        if ctx.settings.trend_sources_mode == "live":
            query = query.where(Game.is_test_data.is_(False))
        games = list(ctx.session.scalars(query.order_by(Game.id).limit(BATCH)))

        profiled = []
        for game in games:
            profile = build_profile(ctx.session, game, languages, now)
            game.profile = profile
            game.profiled_at = now
            ideas = ", ".join(i["format_label"] for i in profile["video_ideas"])
            has_own = any(p["score"] is not None for p in profile["channel_performance"].values())
            basis = "trend score + own performance" if has_own else "trend score, no own videos yet"
            ctx.decide(
                "game_profile",
                {
                    "rating": profile["rating"],
                    "audience": profile["audience"]["key"],
                    "rising": profile["rising"],
                },
                f"{game.name}: audience '{profile['audience']['de']}', "
                f"modes {profile['modes'] or '-'}, ideas: {ideas}. "
                f"Rating {profile['rating']} ({basis}).",
                entity_type="games",
                entity_id=game.id,
            )
            profiled.append({"game_id": game.id, "game": game.name, "rating": profile["rating"]})
        ctx.session.flush()
        return AgentResult(output={"profiled": profiled, "count": len(profiled)})
