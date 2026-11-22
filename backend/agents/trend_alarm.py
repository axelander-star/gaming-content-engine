"""Agent 26 (A11): Trend Alarm. Spots topics that take off and prepares drafts.

Reads the YouTube trending list (official API, 1 quota unit per call) and the
competitor radar, scores every signal transparently and, from the threshold on,
opens an alarm with several own-production drafts and a push to the phone.
"""

from __future__ import annotations

from typing import Any

from agents.base import Agent, AgentContext, AgentResult
from services import trend_alarm


class TrendAlarmAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        project_id = payload.get("project_id")
        res = trend_alarm.scan(
            ctx.session,
            ctx.settings,
            project_id=int(project_id) if project_id is not None else None,
            manual=bool(payload.get("manual")),
        )
        output = {
            "mode": res.mode,
            "signals": res.signals,
            "alarms": res.alarms,
            "drafts": res.drafts,
            "finished": res.finished,
            "expired": res.expired,
            "errors": res.errors,
        }
        ctx.decide(
            "trend_alarm",
            output,
            f"{res.signals} Signale geprüft, {len(res.alarms)} neue Alarme, "
            f"{res.drafts} Entwürfe in Arbeit",
        )
        return AgentResult(output=output)
