"""Agent 4: Material Scout (PROJECT_SPEC sections 5 and 6).

Two jobs:

* **Per material** (stage ``DISCOVERED``): document the provenance, sort the
  material by game, report missing evidence and hand it to the rights check
  (``RIGHTS_PENDING``). The scout never approves anything.
* **Sweep** (``{"sweep": true}``, daily): compare current trends with the
  approved material and report which trending games still lack licensed
  footage, so the operator can ask creators or partners for it.

The scout does not download, record or scrape anything: material only enters
the system through registered, licensed sources (no unauthorised stream
recording or video takeover, section 5).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from agents.base import Agent, AgentContext, AgentResult
from core.enums import Language, MaterialStatus, NotificationLevel
from models.access import Notification
from models.production import GameplayFile
from models.rights import Asset, License, Source
from models.trends import Game
from services import workflow
from services.controls import get_operations
from services.trends import latest_trends

USABLE = (MaterialStatus.RIGHTS_APPROVED, MaterialStatus.ANALYZED)
TOP_TRENDS = 5


def provenance_gaps(
    material: GameplayFile, asset: Asset | None, source: Source | None, lic: License | None
) -> list[str]:
    gaps = []
    if asset is None or lic is None or source is None:
        return ["Kein Asset mit Quelle und Lizenz verknüpft"]
    if not (source.url or source.provenance_notes):
        gaps.append("Herkunft der Quelle nicht dokumentiert (URL oder Notiz)")
    if not lic.document_uri:
        gaps.append("Kein Lizenzdokument hochgeladen")
    if material.game_id is None:
        gaps.append("Material ist keinem Spiel zugeordnet")
    return gaps


class MaterialScoutAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        if payload.get("sweep"):
            return self._material_needs(ctx)
        return self._scout(ctx, int(payload["entity_id"]))

    def _scout(self, ctx: AgentContext, material_id: int) -> AgentResult:
        s = ctx.session
        material = s.get(GameplayFile, material_id)
        assert material is not None  # guaranteed by the gate
        asset = s.get(Asset, material.asset_id)
        source = s.get(Source, asset.source_id) if asset else None
        lic = s.get(License, asset.license_id) if asset else None
        if asset is not None and material.game_id is None and asset.game_id is not None:
            material.game_id = asset.game_id  # sort by game
        gaps = provenance_gaps(material, asset, source, lic)
        game = s.get(Game, material.game_id) if material.game_id else None
        info = {
            "source": source.name if source else None,
            "source_type": source.type.value if source else None,
            "license_id": lic.id if lic else None,
            "game": game.name if game else None,
            "categories": list(game.categories or []) if game else [],
            "missing_evidence": gaps,
        }
        if gaps:
            s.add(
                Notification(
                    level=NotificationLevel.WARNING,
                    title=f"Fehlende Nachweise für Material #{material.id}",
                    body="; ".join(gaps),
                )
            )
        workflow.transition(s, material, MaterialStatus.RIGHTS_PENDING, actor="material_scout")
        ctx.decide(
            "material_registered",
            info,
            f"Material #{material.id} from '{info['source']}' for game '{info['game']}' "
            f"handed to the rights check. Missing evidence: {gaps or 'none'}.",
            entity_type="gameplay_files",
            entity_id=material.id,
        )
        return AgentResult(output=info)

    def _material_needs(self, ctx: AgentContext) -> AgentResult:
        s = ctx.session
        needs: list[dict[str, Any]] = []
        seen: set[int] = set()
        for lang in get_operations(s).languages:
            for trend in latest_trends(s, Language(lang), TOP_TRENDS):
                if trend.game_id in seen:
                    continue
                seen.add(trend.game_id)
                usable = s.scalar(
                    select(GameplayFile.id)
                    .where(GameplayFile.game_id == trend.game_id, GameplayFile.status.in_(USABLE))
                    .limit(1)
                )
                if usable is None:
                    game = s.get(Game, trend.game_id)
                    needs.append(
                        {
                            "game_id": trend.game_id,
                            "game": game.name if game else "?",
                            "score": float(trend.score),
                            "language": lang.value,
                        }
                    )
        if needs:
            s.add(
                Notification(
                    level=NotificationLevel.INFO,
                    title=f"Lizenziertes Material fehlt für {len(needs)} Trend-Spiel(e)",
                    body=", ".join(n["game"] for n in needs),
                )
            )
        ctx.decide(
            "material_needs",
            {"needs": needs},
            f"{len(needs)} trending game(s) without approved material: "
            + (", ".join(n["game"] for n in needs) or "none")
            + ". Footage must come from licensed creators, partners or own uploads.",
        )
        return AgentResult(output={"needs": needs})
