"""Agent 10: Localization (PROJECT_SPEC sections 2 and 6, Phase 9).

Works on variants in ``LOCALIZATION``. Checks the latest script of the variant for
its own language (see ``services.localization``), fixes mechanical problems, adds
the audience hashtag, makes sure hook and title are not a copy of the other
language version and moves the variant to ``VOICEOVER``. A change creates a new
script version, so every edit stays traceable.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.base import Agent, AgentContext, AgentResult, PermanentError
from core.enums import VideoStatus
from models.production import Clip, GameplayFile, Scene, Script, Variant
from models.rights import Asset, Source
from models.trends import Game
from services import localization, workflow


def latest_script(session: Session, variant_id: int) -> Script | None:
    return session.scalar(
        select(Script)
        .where(Script.variant_id == variant_id)
        .order_by(Script.version.desc())
        .limit(1)
    )


class LocalizationAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        s = ctx.session
        variant = s.get(Variant, int(payload["entity_id"]))
        assert variant is not None  # guaranteed by the gate
        script = latest_script(s, variant.id)
        if script is None:
            raise PermanentError("Kein Skript vorhanden")
        if script.language != variant.language:
            raise PermanentError(
                f"Skript ist {script.language.value}, Variante ist {variant.language.value}"
            )
        names = self._names(s, variant)
        lang = variant.language

        fixes: list[str] = []
        problems: list[str] = []
        beats = []
        for beat in script.beats or []:
            check = localization.check_text(str(beat["text"]), lang, names)
            fixes += [f"{beat['kind']}: {f}" for f in check.fixes]
            problems += [f"{beat['kind']}: {p}" for p in check.problems]
            beats.append({**beat, "text": check.text})
        title = localization.check_text(script.title or "", lang, names, sentence=False)
        fixes += [f"Titel: {f}" for f in title.fixes]
        problems += [f"Titel: {p}" for p in title.problems]
        description, desc_fixes = localization.adapt_description(script.description or "", lang)
        fixes += desc_fixes

        texts = {"hook": _beat(beats, "hook"), "title": title.text}
        copies = []
        for other in self._other_languages(s, variant):
            other_script = latest_script(s, other.id)
            if other_script is not None:
                copies += localization.same_as_other_language(
                    texts, {"hook": other_script.hook or "", "title": other_script.title or ""}
                )
        if copies:
            problems.append(
                f"identisch mit anderer Sprachfassung: {', '.join(sorted(set(copies)))}"
            )
        if problems:
            raise PermanentError("Lokalisierung: " + "; ".join(problems))

        version = script.version
        if fixes:
            version += 1
            spoken = [b["text"] for b in beats if b["kind"] not in ("hook", "cta")]
            cta = _beat(beats, "cta")
            s.add(
                Script(
                    variant_id=variant.id,
                    language=lang,
                    hook=_beat(beats, "hook"),
                    voiceover_text=" ".join([*spoken, cta]).strip(),
                    call_to_action=cta or None,
                    title=title.text,
                    description=description,
                    version=version,
                    hook_type=script.hook_type,
                    beats=beats,
                    source=f"{script.source}+localized",
                )
            )
            variant.title, variant.description = title.text, description
        workflow.transition(s, variant, VideoStatus.VOICEOVER, actor="localization")
        info = {"script_version": version, "fixes": fixes, "language": lang.value}
        ctx.decide(
            "localized",
            info,
            (
                f"{lang.value.upper()}-Fassung geprüft: {len(fixes)} Anpassung(en)"
                + (f" ({'; '.join(fixes)})" if fixes else ", keine Änderung nötig")
                + "; Sprache, Form und Abgrenzung zur anderen Sprachfassung in Ordnung."
            ),
            entity_type="variants",
            entity_id=variant.id,
        )
        return AgentResult(output=info)

    @staticmethod
    def _names(s: Any, variant: Variant) -> list[str]:
        clip = s.get(Clip, variant.clip_id)
        scene = s.get(Scene, clip.scene_id) if clip else None
        material = s.get(GameplayFile, scene.gameplay_file_id) if scene else None
        names: list[str] = []
        if material and material.game_id:
            game = s.get(Game, material.game_id)
            names.append(game.name if game else "")
        asset = s.get(Asset, material.asset_id) if material else None
        source = s.get(Source, asset.source_id) if asset else None
        names.append(source.name if source else "")
        return [n for n in names if n]

    @staticmethod
    def _other_languages(s: Any, variant: Variant) -> list[Variant]:
        return list(
            s.scalars(
                select(Variant).where(
                    Variant.clip_id == variant.clip_id,
                    Variant.variant_label == variant.variant_label,
                    Variant.language != variant.language,
                )
            )
        )


def _beat(beats: list[dict[str, Any]], kind: str) -> str:
    return next((str(b["text"]) for b in beats if b["kind"] == kind), "")
