"""Agent 9: Script & Hook (PROJECT_SPEC section 6, Phase 8).

Works on variants in ``EDITING`` whose concept is chosen. Writes hook, voiceover
beats with timing, call to action, title and description in the variant's own
language (separate wording per language, no translation) and moves the variant to
``LOCALIZATION``. Uses the free templates unless the operator has connected a text
model (``ai_provider``); a model call is only made after the budget service agrees.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from agents.base import Agent, AgentContext, AgentResult, BudgetExceededError
from core.enums import CostCategory, VideoStatus
from models.production import Clip, GameplayFile, Scene, Script, Variant
from models.rights import Asset, Source
from models.trends import Game
from services import creative, llm, workflow
from services.controls import get_operations


class ScriptHookAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        s = ctx.session
        variant = s.get(Variant, int(payload["entity_id"]))
        assert variant is not None and variant.video_format and variant.hook_type
        clip = s.get(Clip, variant.clip_id)
        assert clip is not None
        scene = s.get(Scene, clip.scene_id)
        assert scene is not None
        material = s.get(GameplayFile, scene.gameplay_file_id)
        assert material is not None
        game = s.get(Game, material.game_id) if material.game_id else None
        asset = s.get(Asset, material.asset_id)
        source = s.get(Source, asset.source_id) if asset else None

        draft = creative.write_script(
            language=variant.language,
            video_format=variant.video_format,
            hook_type=variant.hook_type,
            game=game.name if game else "",
            source_name=source.name if source else "",
            duration_s=clip.duration_s or (clip.end_s - clip.start_s),
            seed=f"{variant.channel_id}:{variant.clip_id}:{variant.variant_label}",
        )
        origin, draft, note = self._refine(ctx, variant, draft)

        version = (
            s.scalar(select(func.max(Script.version)).where(Script.variant_id == variant.id)) or 0
        ) + 1
        script = Script(
            variant_id=variant.id,
            language=variant.language,
            hook=draft.hook,
            voiceover_text=draft.voiceover_text,
            call_to_action=draft.call_to_action or None,
            title=draft.title,
            description=draft.description,
            version=version,
            hook_type=variant.hook_type,
            beats=draft.beats,
            source=origin,
        )
        s.add(script)
        variant.title, variant.description = draft.title, draft.description
        s.flush()
        workflow.transition(s, variant, VideoStatus.LOCALIZATION, actor="script_hook")
        info = {
            "script_id": script.id,
            "version": version,
            "source": origin,
            "words": draft.words,
            "word_budget": draft.word_budget,
            "title": draft.title,
        }
        ctx.decide(
            "script_written",
            info,
            f"Skript v{version} ({variant.language.value}, {variant.video_format}/"
            f"{variant.hook_type}) aus {origin}; {draft.words} von {draft.word_budget} "
            "Wörtern im ruhigen Sprechtempo." + (f" {note}" if note else ""),
            entity_type="variants",
            entity_id=variant.id,
        )
        return AgentResult(output=info)

    @staticmethod
    def _refine(
        ctx: AgentContext, variant: Variant, draft: creative.ScriptDraft
    ) -> tuple[str, creative.ScriptDraft, str | None]:
        """Origin of the text, the (possibly improved) draft and a note for the log."""
        provider = get_operations(ctx.session).ai_provider
        try:
            model = llm.get_model(provider, ctx.settings)
        except llm.LLMNotConfiguredError as exc:
            return "template", draft, f"{exc}; Vorlage verwendet."
        if model is None:
            return "template", draft, None
        try:
            ctx.authorize_cost(model.estimated_cost_eur)
        except BudgetExceededError as exc:
            return "template", draft, f"KI-Aufruf nicht freigegeben ({exc}); Vorlage verwendet."
        brief = f"{variant.video_format}/{variant.hook_type}"
        improved = model.rewrite(draft, variant.language, brief)
        ctx.add_cost(model.estimated_cost_eur, CostCategory.AI, provider=model.name,
                     description=f"Skript Variante #{variant.id}")  # fmt: skip
        return model.name, improved, None
