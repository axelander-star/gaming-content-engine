"""Agent 6: Gameplay Analysis (PROJECT_SPEC sections 6 and 7, steps 2 and 4–7).

Works on rights-approved material (``RIGHTS_APPROVED``):

1. technical check with ffprobe (format, length, resolution, frame rate),
2. scene detection and rating (``services.analysis``),
3. selection of the best scenes (score at least ``MIN_SCENE_SCORE``, at most
   ``MAX_CLIPS_PER_MATERIAL``) with start and end snapped to shot boundaries,
4. for every selected scene one clip and one variant per language, which the
   Clip Production Agent renders next (``SCENE_SELECTED``).

The material then moves to ``ANALYZED``. A file that fails the technical check
is marked FAILED without automatic retries; the operator has to replace it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.base import Agent, AgentContext, AgentResult, PermanentError
from core.config import Settings
from core.enums import Language, MaterialStatus, NotificationLevel
from models.access import Notification
from models.channels import Channel
from models.production import Clip, GameplayFile, Scene, Variant
from services import analysis, media, storage, workflow
from services.controls import get_operations

SCENES_KEPT = 10  # rated scenes stored for the dashboard, selected or not


def local_file(settings: Settings, uri: str) -> Path:
    try:
        path = storage.resolve(settings, uri)
    except storage.StorageError as exc:
        raise PermanentError(
            f"Datei nicht lokal verfügbar ({uri.split('://')[0]}://); bitte hochladen"
        ) from exc
    if not path.is_file():
        raise PermanentError("Datei fehlt im Speicher")
    return path


def primary_channel(session: Session, language: Language) -> Channel | None:
    """Channel a new variant starts on. Publishing Strategy (Phase 11) distributes it."""
    return session.scalar(
        select(Channel).where(Channel.language == language).order_by(Channel.id).limit(1)
    )


class GameplayAnalysisAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        s, settings = ctx.session, ctx.settings
        material = s.get(GameplayFile, int(payload["entity_id"]))
        assert material is not None  # guaranteed by the gate
        path = local_file(settings, material.storage_uri)

        try:
            probe = media.probe(settings, path)
        except media.MediaError as exc:
            raise PermanentError(f"Datei nicht lesbar: {exc}") from exc
        material.duration_s = probe.duration_s
        material.width, material.height, material.fps = probe.width, probe.height, probe.fps
        material.video_codec, material.audio_codec = probe.video_codec, probe.audio_codec
        issues = media.technical_issues(settings, probe)
        if issues:
            raise PermanentError("Technische Prüfung: " + "; ".join(issues))

        features = analysis.extract(settings, path, probe)
        candidates = analysis.find_scenes(settings, features, SCENES_KEPT)
        for scene in list(material.scenes):  # re-analysis replaces unused old scenes
            if not scene.selected:
                s.delete(scene)
        s.flush()

        selected: list[dict[str, Any]] = []
        languages = list(get_operations(s).languages)
        for rank, cand in enumerate(candidates, start=1):
            pick = (
                cand.score >= settings.min_scene_score
                and len(selected) < settings.max_clips_per_material
            )
            scene = Scene(
                gameplay_file_id=material.id,
                start_s=cand.start_s,
                end_s=cand.end_s,
                score=cand.score,
                scores=cand.scores,
                tags=cand.tags,
                rank=rank,
                focus_x=cand.focus_x,
                spread=cand.spread,
                selected=pick,
            )
            s.add(scene)
            s.flush()
            if not pick:
                continue
            clip = Clip(scene_id=scene.id, start_s=cand.start_s, end_s=cand.end_s)
            s.add(clip)
            s.flush()
            variants = []
            for lang in languages:
                channel = primary_channel(s, lang)
                if channel is None:
                    continue
                variant = Variant(
                    clip_id=clip.id, channel_id=channel.id, language=lang, variant_label="A"
                )
                s.add(variant)
                variants.append(lang.value)
            selected.append(
                {
                    "scene_id": scene.id,
                    "clip_id": clip.id,
                    "start_s": cand.start_s,
                    "end_s": cand.end_s,
                    "score": cand.score,
                    "tags": cand.tags,
                    "variants": variants,
                }
            )

        workflow.transition(s, material, MaterialStatus.ANALYZED, actor="gameplay_analysis")
        if not selected:
            s.add(
                Notification(
                    level=NotificationLevel.INFO,
                    title=f"Keine geeignete Szene in Material #{material.id}",
                    body=f"Beste Bewertung {candidates[0].score:.2f}"
                    if candidates
                    else "Keine Szene gefunden",
                )
            )
        summary = analysis.summary(features)
        ctx.decide(
            "scenes_selected",
            {"selected": selected, "rated": len(candidates)},
            f"{len(candidates)} scene(s) rated, {len(selected)} selected "
            f"(min score {settings.min_scene_score}, max {settings.max_clips_per_material}). "
            f"Weights: {analysis.WEIGHTS}.",
            inputs={"probe": probe.as_dict(), "signals": summary},
            entity_type="gameplay_files",
            entity_id=material.id,
        )
        return AgentResult(
            output={"probe": probe.as_dict(), "signals": summary, "selected": selected}
        )
