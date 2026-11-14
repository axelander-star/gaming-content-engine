"""Agent 11: Voice (PROJECT_SPEC section 6, Phase 9).

Works on variants in ``VOICEOVER``. Speaks every beat of the latest script with the
voice of the variant's language, fits it into the beat's slot (speeding up by at
most ``MAX_TEMPO``) and mixes one voice track of clip length. Only providers that
are cleared for commercial use are accepted; a paid provider is only called after
the budget service agrees. Moves the variant to ``SUBTITLES``.
"""

from __future__ import annotations

import shutil
import uuid
from decimal import Decimal
from typing import Any

from agents.base import (
    Agent,
    AgentContext,
    AgentResult,
    PermanentError,
    ProviderUnavailableError,
)
from agents.localization import latest_script
from core.enums import CostCategory, VideoStatus
from models.production import Clip, Variant, Voiceover
from services import media, storage, voice, workflow
from services.controls import get_operations


class VoiceAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        s, settings = ctx.session, ctx.settings
        variant = s.get(Variant, int(payload["entity_id"]))
        assert variant is not None  # guaranteed by the gate
        clip = s.get(Clip, variant.clip_id)
        assert clip is not None
        script = latest_script(s, variant.id)
        if script is None or not script.beats:
            raise PermanentError("Kein Skript mit Zeitmarken vorhanden")
        name = get_operations(s).tts_provider
        provider = voice.get_provider(name, settings)
        if provider is None:
            raise ProviderUnavailableError(f"Stimm-Anbieter '{name}' ist nicht angebunden")
        if not provider.commercial_use_cleared:
            raise PermanentError(f"Stimm-Anbieter '{name}' ist nicht für kommerzielle Nutzung frei")
        voice_id = provider.voices.get(variant.language)
        if voice_id is None:
            raise PermanentError(f"Keine Stimme für {variant.language.value} bei '{name}'")
        clip_s = clip.duration_s or (clip.end_s - clip.start_s)
        spoken = sum(voice.spoken_seconds(str(b["text"]), variant.language) for b in script.beats)
        estimate = (provider.cost_per_second_eur * Decimal(str(round(spoken, 1)))).quantize(
            Decimal("0.0001")
        )
        if estimate > 0:
            ctx.authorize_cost(estimate)  # refused -> run is skipped, nothing is called

        work = storage.work_dir(settings) / f"voice-{uuid.uuid4().hex}"
        work.mkdir()
        try:
            parts = []
            for i, beat in enumerate(script.beats):
                path = work / f"{i}.wav"
                natural = provider.synthesize(str(beat["text"]), variant.language, voice_id, path)
                parts.append((path, voice.plan_segment(beat, natural, clip_s)))
            track = work / "voice.m4a"
            media.run(voice.mix_command(settings, parts, clip_s, track), timeout=600)
            stored = storage.store_path(settings, track, "voice", ".m4a")
            duration = media.duration(settings, storage.resolve(settings, stored.uri))
        except media.MediaError as exc:
            raise PermanentError(f"Stimme konnte nicht erzeugt werden: {exc}") from exc
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if estimate > 0:
            ctx.add_cost(estimate, CostCategory.TTS, provider=provider.name,
                         description=f"Stimme Variante #{variant.id}")  # fmt: skip

        segments = [seg.as_dict() for _, seg in parts]
        overflow = [seg for _, seg in parts if seg.overflow_s > 0]
        s.add(
            Voiceover(
                variant_id=variant.id,
                script_id=script.id,
                provider=provider.name,
                voice_id=voice_id,
                storage_uri=stored.uri,
                duration_s=duration,
                commercial_use_cleared=provider.commercial_use_cleared,
                segments=segments,
            )
        )
        workflow.transition(s, variant, VideoStatus.SUBTITLES, actor="voice")
        info = {
            "provider": provider.name,
            "voice_id": voice_id,
            "segments": len(segments),
            "max_tempo": max(seg.tempo for _, seg in parts),
            "overflow": [seg.kind for seg in overflow],
            "cost_eur": str(estimate),
        }
        ctx.decide(
            "voice_generated",
            info,
            f"Stimme {voice_id} ({provider.name}) für {len(segments)} Abschnitte, "
            f"Tempo bis {info['max_tempo']}×"
            + (
                f"; zu lang trotz Tempo: {', '.join(seg.kind for seg in overflow)}"
                if overflow
                else "; alle Abschnitte passen."
            ),
            entity_type="variants",
            entity_id=variant.id,
        )
        return AgentResult(output=info)
