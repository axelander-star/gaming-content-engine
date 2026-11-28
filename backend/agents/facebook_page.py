"""Agent 27: Facebook Page. Runs the Facebook Page behind each Instagram channel.

Instagram professional accounts always belong to a Facebook Page. With the Meta
login the engine may run that Page too, so the operator has nothing to do there:
the agent takes the Page over as a channel of its own, fills its profile from the
channel assistant (description, profile picture, cover photo), copies every
Instagram video to it and watches the connection. See services/facebook_page.py.
"""

from __future__ import annotations

from typing import Any

from agents.base import Agent, AgentContext, AgentResult
from services import facebook_page


class FacebookPageAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        res = facebook_page.run(ctx.session, ctx.settings)
        output = res.as_dict()
        problems = sum(len(v) for v in res.problems.values())
        ctx.decide(
            "facebook_page",
            output,
            f"{len(res.linked)} Facebook-Seiten übernommen oder aktualisiert, "
            f"{len(res.synced)} Profile übertragen, {res.copies} Instagram-Videos für "
            f"Facebook vorbereitet, {problems} Hinweise",
        )
        return AgentResult(output=output)
