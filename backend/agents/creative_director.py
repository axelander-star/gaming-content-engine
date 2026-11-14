"""Agent 8: Creative Director (PROJECT_SPEC section 6, Phase 8).

Works on variants in ``EDITING`` that have no concept yet. Chooses format and hook
structure from the measured scene signals, the Game Intelligence profile and (from
Phase 14) the own performance per format, and plans up to ``creative_variants``
variants (A–D) of the same clip that really differ. The Script & Hook Agent writes
the texts next; the variant stays in ``EDITING`` until then.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from agents.base import Agent, AgentContext, AgentResult, PermanentError
from core.enums import VideoStatus
from models.production import Clip, GameplayFile, Scene, Variant
from models.trends import Game
from services import creative, workflow
from services.controls import get_operations

LABELS = ("A", "B", "C", "D")


def format_performance(_variant: Variant) -> dict[str, float]:
    """Own performance per format (0..1). Empty until the Learning Agent (Phase 14)."""
    return {}


class CreativeDirectorAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        s = ctx.session
        variant = s.get(Variant, int(payload["entity_id"]))
        assert variant is not None  # guaranteed by the gate
        clip = s.get(Clip, variant.clip_id)
        assert clip is not None
        scene = s.get(Scene, clip.scene_id)
        assert scene is not None
        material = s.get(GameplayFile, scene.gameplay_file_id)
        assert material is not None
        game = s.get(Game, material.game_id) if material.game_id else None
        ideas = (game.profile or {}).get("video_ideas", []) if game else []
        profile_formats = [i["format"] for i in ideas if isinstance(i, dict) and "format" in i]
        performance = format_performance(variant)

        ranked = creative.rank_concepts(scene.scores or {}, profile_formats, performance)
        if not ranked:
            fits = creative.format_fits(scene.scores or {})
            raise PermanentError(
                "Kein automatisch wählbares Format passt zur Szene "
                f"(beste Eignung {max(fits.values()):.2f}, nötig {creative.MIN_FORMAT_FIT})"
            )
        wanted = get_operations(s).creative_variants
        taken = set(
            s.scalars(
                select(Variant.variant_label).where(
                    Variant.clip_id == variant.clip_id, Variant.channel_id == variant.channel_id
                )
            )
        )
        free = [lbl for lbl in LABELS if lbl not in taken]
        chosen = creative.choose_variants(ranked, min(wanted, 1 + len(free)))

        self._apply(variant, chosen[0])
        planned = [
            {"variant_id": variant.id, "label": variant.variant_label, **chosen[0].as_dict()}
        ]
        for concept, label in zip(chosen[1:], free, strict=False):
            sibling = Variant(
                clip_id=variant.clip_id,
                channel_id=variant.channel_id,
                language=variant.language,
                variant_label=label,
                storage_uri=variant.storage_uri,
                sha256=variant.sha256,
                fingerprint=variant.fingerprint,
            )
            self._apply(sibling, concept)
            s.add(sibling)
            s.flush()
            workflow.transition(s, sibling, VideoStatus.EDITING, actor="creative_director")
            planned.append({"variant_id": sibling.id, "label": label, **concept.as_dict()})

        summary = ", ".join(f"{p['label']}: {p['video_format']}/{p['hook_type']}" for p in planned)
        ctx.decide(
            "concept_planned",
            {"variants": planned},
            f"{len(planned)} Variante(n) geplant ({summary}). Gewichte {creative.CONCEPT_WEIGHTS}; "
            "eigene Performance je Format noch ohne Daten (neutral 0,5).",
            inputs={
                "scene_scores": scene.scores,
                "format_fits": creative.format_fits(scene.scores or {}),
                "profile_formats": profile_formats,
                "wanted_variants": wanted,
            },
            entity_type="variants",
            entity_id=variant.id,
        )
        return AgentResult(output={"variants": planned})

    @staticmethod
    def _apply(variant: Variant, concept: creative.Concept) -> None:
        variant.video_format = concept.video_format
        variant.hook_type = concept.hook_type
        variant.concept = concept.as_dict()
