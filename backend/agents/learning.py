"""Agent 17: Learning (PROJECT_SPEC sections 6 and 12, Phase 14).

Runs a few times a day (scheduler). Each run:

1. finishes a trial whose test period is over (keep or roll back),
2. while no trial runs: derives factors per game, format and hook from all
   judged posts (:mod:`services.learning`) and, if they differ from the version
   that applies now, starts a new trial version.

Nothing is learned from few data: groups need enough posts on several days. All
versions stay stored for rollback.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agents.base import Agent, AgentContext, AgentResult
from core.enums import NotificationLevel
from models.access import Notification
from services import learning


class LearningAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        s = ctx.session
        now = datetime.now(UTC)
        samples = learning.collect(s, include_mock=ctx.settings.publishing_mode != "live")
        current = learning.current(s)
        info: dict[str, Any] = {"samples": len(samples)}

        if current is not None and current.status == learning.TRIAL:
            outcome = learning.evaluate(s, current, samples, now)
            info["trial"] = {"version": current.version, "outcome": outcome or "läuft"}
            if outcome is None:
                return AgentResult(output=info)
            result = current.evaluation.get("result", outcome)
            s.add(
                Notification(
                    level=NotificationLevel.INFO,
                    title=f"Lernversion {current.version}: {result}",
                    body="; ".join(current.reasons or [])[:2000],
                )
            )
            ctx.decide(
                "trial_" + outcome,
                {"version": current.version, **current.evaluation},
                f"Test von Version {current.version}: {result}.",
            )
            current = learning.current(s)

        stats = learning.group_stats(samples)
        new_weights, reasons = learning.derive(stats)
        old = current.weights if current else {}
        if not learning.changed(old or {}, new_weights):
            info["change"] = False
            return AgentResult(output=info)
        version = learning.start_trial(s, new_weights, reasons, stats, samples, now)
        info.update({"change": True, "version": version.version, "reasons": reasons})
        ctx.decide(
            "trial_started",
            {"version": version.version, "weights": new_weights},
            "Neue Lernversion im Test: "
            + ("; ".join(reasons) or "frühere Muster gelten nicht mehr"),
            inputs={"samples": len(samples), "baseline": version.evidence.get("baseline")},
        )
        return AgentResult(output=info)
