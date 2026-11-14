"""Agent 5: Rights & License (PROJECT_SPEC sections 5 and 6).

* **Per material** (stage ``RIGHTS_PENDING``): checks every criterion,
  stores the full result in ``rights_checks`` and moves the material to
  ``RIGHTS_APPROVED`` only if everything passes, else ``RIGHTS_REJECTED``
  with the reasons. Missing evidence is reported to the operator.
* **Sweep** (``{"sweep": true}``, daily): expires outdated licenses, warns
  before a license expires and sends affected material back to the check.
"""

from __future__ import annotations

from typing import Any

from agents.base import Agent, AgentContext, AgentResult
from core.enums import MaterialStatus, NotificationLevel
from models.access import Notification
from models.production import GameplayFile
from models.rights import RightsCheck
from services import rights, workflow


class RightsLicenseAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        if payload.get("sweep"):
            sweep = rights.expiry_sweep(ctx.session, actor="rights_license")
            ctx.decide(
                "license_expiry",
                {
                    "expired": sweep.expired,
                    "expiring": sweep.expiring,
                    "rechecked": sweep.rechecked,
                },
                f"{len(sweep.expired)} license(s) expired, {len(sweep.expiring)} expire within "
                f"{rights.EXPIRY_WARNING_DAYS} days, {len(sweep.rechecked)} material(s) sent "
                "back to the rights check.",
            )
            return AgentResult(output=sweep.__dict__)

        material = ctx.session.get(GameplayFile, int(payload["entity_id"]))
        assert material is not None  # guaranteed by the gate
        result = rights.evaluate(ctx.session, material)
        check = RightsCheck(
            gameplay_file_id=material.id,
            license_id=result.license_id,
            agent_run_id=ctx.run.id,
            approved=result.approved,
            checks=result.as_json(),
            missing=result.missing,
            denied=result.denied,
        )
        ctx.session.add(check)
        target = (
            MaterialStatus.RIGHTS_APPROVED if result.approved else MaterialStatus.RIGHTS_REJECTED
        )
        workflow.transition(ctx.session, material, target, actor="rights_license")
        failed = [c for c in result.checks if c.outcome != "ok"]
        if result.missing:
            ctx.session.add(
                Notification(
                    level=NotificationLevel.WARNING,
                    title=f"Rechteprüfung Material #{material.id}: Nachweise fehlen",
                    body="; ".join(
                        f"{c.label}: {c.reason}" for c in failed if c.outcome == "missing"
                    ),
                )
            )
        reasoning = (
            "All criteria passed."
            if result.approved
            else "Rejected (deny by default): "
            + "; ".join(f"{c.key} {c.outcome}: {c.reason}" for c in failed)
        )
        ctx.session.flush()
        ctx.decide(
            "rights_check",
            {
                "approved": result.approved,
                "denied": result.denied,
                "missing": result.missing,
                "rights_check_id": check.id,
            },
            reasoning,
            inputs={"license_id": result.license_id},
            entity_type="gameplay_files",
            entity_id=material.id,
        )
        return AgentResult(
            output={
                "approved": result.approved,
                "denied": result.denied,
                "missing": result.missing,
            }
        )
