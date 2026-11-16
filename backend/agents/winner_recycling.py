"""Agent 25 (A7): Winner Recycling. Learns from hook A/B tests and reuses winners.

A post that ran at least twice as well as usual on its channel gets, a week later,
the same clip with a different hook (the best one in the channel's hook tests) and
an idea "Teil 2" in the idea lab. Local rules only, nothing is published here.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from agents.base import Agent, AgentContext, AgentResult, AgentSkipError
from models.publishing import Post
from services import winners


class WinnerRecyclingAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        s = ctx.session
        if not s.scalar(select(func.count(Post.id)).where(Post.published_at.is_not(None))):
            raise AgentSkipError("Noch keine veröffentlichten Beiträge")
        # in live mode test posts (synthetic numbers) never decide about real ones
        res = winners.run(s, include_mock=ctx.settings.publishing_mode != "live")
        recycled = res["recycled"]
        hooks = sum(1 for r in recycled if "new_hook" in r)
        ideas = sum(1 for r in recycled if "idea_id" in r)
        ctx.decide(
            "winner_recycling",
            res,
            f"{res['winners']} Gewinner fällig; {hooks} mit neuem Hook eingeplant, "
            f"{ideas} Ideen „Teil 2“ (Gewinner = mindestens {winners.WINNER_SCORE:.0f}× so gut "
            f"wie üblich, frühestens nach {winners.RECYCLE_AFTER_DAYS} Tagen).",
        )
        return AgentResult(output=res)
