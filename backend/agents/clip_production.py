"""Agent 7: Clip Production (PROJECT_SPEC sections 6 and 7, steps 7–9).

Works on variants in ``SCENE_SELECTED``: renders the language-independent clip
of the variant's scene once (cut, start/end fades, 9:16 crop around the action
or blurred full frame, H.264/AAC 1080×1920), checks the technical parameters of
the result and moves the variant to ``EDITING``. The second language variant of
the same clip reuses the rendered file.

At most ``max_parallel_render_jobs`` renders run at the same time (operator
setting); when all slots are busy the run is skipped and dispatched again later.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from agents.base import Agent, AgentContext, AgentResult, PermanentError
from agents.gameplay_analysis import local_file
from core.enums import VideoStatus
from models.production import Clip, GameplayFile, Scene, Variant
from services import media, render, workflow
from services.controls import get_operations
from services.queue import get_redis


class ClipProductionAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        s, settings = ctx.session, ctx.settings
        variant = s.get(Variant, int(payload["entity_id"]))
        assert variant is not None  # guaranteed by the gate
        # Lock the clip so two language variants never render the same clip twice.
        clip = s.scalar(select(Clip).where(Clip.id == variant.clip_id).with_for_update())
        assert clip is not None
        scene = s.get(Scene, clip.scene_id)
        assert scene is not None
        material = s.get(GameplayFile, scene.gameplay_file_id)
        assert material is not None

        rendered_now = clip.storage_uri is None
        if rendered_now:
            path = local_file(settings, material.storage_uri)
            try:
                source = media.probe(settings, path)
            except media.MediaError as exc:
                raise PermanentError(f"Quelldatei nicht lesbar: {exc}") from exc
            limit = get_operations(s).max_parallel_render_jobs
            with render.render_slot(get_redis(), limit, settings.render_slot_ttl_s):
                try:
                    result = render.render(
                        settings,
                        path,
                        source,
                        clip.start_s,
                        clip.end_s,
                        scene.focus_x,
                        scene.spread or 0.0,
                    )
                except render.RenderError as exc:
                    raise PermanentError(f"Technische Prüfung des Clips: {exc}") from exc
            out = result.probe
            clip.storage_uri, clip.sha256 = result.stored.uri, result.stored.sha256
            clip.fingerprint = result.fingerprint
            clip.width, clip.height, clip.fps = out.width, out.height, out.fps
            clip.duration_s, clip.size_bytes = out.duration_s, out.size_bytes
            clip.video_codec, clip.audio_codec = out.video_codec, out.audio_codec
            clip.layout = result.plan.layout
            clip.render_params = {
                **result.plan.as_dict(),
                "preset": settings.render_preset,
                "crf": settings.render_crf,
                "realtime_factor": result.realtime_factor,
            }
            clip.render_seconds = result.render_seconds
            clip.rendered_at = datetime.now(UTC)

        variant.storage_uri, variant.sha256 = clip.storage_uri, clip.sha256
        variant.fingerprint = clip.fingerprint
        workflow.transition(s, variant, VideoStatus.EDITING, actor="clip_production")
        info = {
            "clip_id": clip.id,
            "rendered_now": rendered_now,
            "width": clip.width,
            "height": clip.height,
            "duration_s": clip.duration_s,
            "layout": clip.layout,
            "render_seconds": clip.render_seconds,
            "realtime_factor": (clip.render_params or {}).get("realtime_factor"),
        }
        ctx.decide(
            "clip_rendered" if rendered_now else "clip_reused",
            info,
            (
                f"Clip #{clip.id} rendered as {clip.width}x{clip.height} "
                f"({clip.layout}) in {clip.render_seconds}s."
                if rendered_now
                else f"Variant uses the already rendered clip #{clip.id}."
            ),
            entity_type="variants",
            entity_id=variant.id,
        )
        return AgentResult(output=info)
