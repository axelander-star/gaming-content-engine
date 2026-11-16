"""Agent 24 (A5): Competitor Radar. Watches other YouTube channels of a niche.

Videos that run far above a channel's usual views go to the idea lab as hints
(never copied). Official YouTube Data API only, about 3 quota units per channel.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from agents.base import Agent, AgentContext, AgentResult, AgentSkipError
from models.competitors import Competitor
from services import competitors


class CompetitorRadarAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        s, settings = ctx.session, ctx.settings
        active = s.scalar(select(func.count(Competitor.id)).where(Competitor.active.is_(True)))
        if not active:
            raise AgentSkipError("Keine Konkurrenzkanäle eingetragen")
        project_id = payload.get("project_id")
        res = competitors.scan(
            s, settings, project_id=int(project_id) if project_id is not None else None
        )
        output = {
            "checked": res.checked,
            "videos": res.videos,
            "outliers": res.outliers,
            "new_research_items": res.items,
            "errors": res.errors,
            "mode": "live" if competitors.live(settings) else "mock",
        }
        ctx.decide(
            "competitor_radar",
            output,
            f"{res.checked} Kanäle geprüft, {res.outliers} auffällige Videos, "
            f"{res.items} neue Hinweise fürs Ideenlabor",
        )
        return AgentResult(output=output)
