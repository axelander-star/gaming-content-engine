"""Agent 23 (A3): Community. Fetches comments, drafts natural replies, answers harmless ones.

Criticism, sensitive topics and TikTok always wait for the operator. Real replies
need every publishing switch; otherwise they are simulated and marked as test.
"""

from __future__ import annotations

from typing import Any

from agents.base import Agent, AgentContext, AgentResult, AgentSkipError
from services import comments


class CommunityAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        s, settings = ctx.session, ctx.settings
        channels = comments.channels_to_watch(s, settings)
        if not channels:
            raise AgentSkipError("Kein Kanal zum Beobachten")
        out: list[dict[str, Any]] = []
        for channel in channels:
            res = comments.run_channel(s, settings, channel)
            if res.fetched or res.drafted or res.sent or res.errors:
                row = {
                    "channel_id": channel.id,
                    "fetched": res.fetched,
                    "drafted": res.drafted,
                    "sent": res.sent,
                    "review": res.review,
                    "ignored": res.ignored,
                    "errors": res.errors,
                }
                out.append(row)
                ctx.decide(
                    "comments",
                    row,
                    f"{res.fetched} neue Kommentare, {res.sent} beantwortet, "
                    f"{res.review} zur Prüfung, {res.ignored} ignoriert",
                    entity_type="channels",
                    entity_id=channel.id,
                )
        return AgentResult(output={"channels": out})
