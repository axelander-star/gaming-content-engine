"""Agent 12: Subtitle (PROJECT_SPEC section 6, Phase 9).

Works on variants in ``SUBTITLES``. Builds captions from the voice segments
(at most two short lines, minimum display time, reading speed checked), stores SRT
and WebVTT for the platforms and renders the final variant: captions burned in at
a position clear of the platform UI, voice mixed over the gameplay, which is
ducked while the voice speaks. The result is checked with ffprobe like a clip.
Moves the variant to ``QUALITY_CHECK``.
"""

from __future__ import annotations

import shutil
import time
import uuid
from typing import Any

from sqlalchemy import select

from agents.base import Agent, AgentContext, AgentResult, PermanentError
from agents.gameplay_analysis import local_file
from core.enums import VideoStatus
from models.production import Clip, Subtitle, Variant, Voiceover
from services import media, render, storage, subtitles, workflow
from services.controls import get_operations
from services.queue import get_redis
from services.voice import Segment


class SubtitleAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        s, settings = ctx.session, ctx.settings
        variant = s.get(Variant, int(payload["entity_id"]))
        assert variant is not None  # guaranteed by the gate
        clip = s.get(Clip, variant.clip_id)
        assert clip is not None
        vo = s.scalar(
            select(Voiceover)
            .where(Voiceover.variant_id == variant.id)
            .order_by(Voiceover.id.desc())
            .limit(1)
        )
        if vo is None or not vo.storage_uri:
            raise PermanentError("Keine Stimme vorhanden")
        if clip.storage_uri is None or not clip.width or not clip.height:
            raise PermanentError("Clip ist nicht gerendert")
        clip_s = clip.duration_s or (clip.end_s - clip.start_s)
        segments = [Segment(**seg) for seg in vo.segments or []]
        cues = subtitles.build_cues(segments, clip_s)
        issues = subtitles.readability_issues(cues)
        source = local_file(settings, clip.storage_uri)
        voice_path = local_file(settings, vo.storage_uri)

        work = storage.work_dir(settings) / f"subs-{uuid.uuid4().hex}"
        work.mkdir()
        try:
            stored_text = {}
            for fmt, text in (("srt", subtitles.to_srt(cues)), ("vtt", subtitles.to_vtt(cues))):
                path = work / f"captions.{fmt}"
                path.write_text(text, encoding="utf-8")
                stored_text[fmt] = storage.store_path(settings, path, "subtitles", f".{fmt}")
            ass = work / "captions.ass"
            ass.write_text(subtitles.to_ass(cues, clip.width, clip.height), encoding="utf-8")
            out = work / "variant.mp4"
            limit = get_operations(s).max_parallel_render_jobs
            began = time.monotonic()
            with render.render_slot(get_redis(), limit, settings.render_slot_ttl_s):
                try:
                    media.run(
                        subtitles.burn_command(settings, source, voice_path, ass, out),
                        timeout=settings.production_job_timeout_s,
                    )
                except media.MediaError as exc:
                    raise PermanentError(f"Untertitel einbrennen fehlgeschlagen: {exc}") from exc
            seconds = round(time.monotonic() - began, 1)
            probe = media.probe(settings, out)
            problems = _verify(settings, clip, clip_s, probe)
            if problems:
                raise PermanentError("Technische Prüfung der Variante: " + "; ".join(problems))
            stored_ass = storage.store_path(settings, ass, "subtitles", ".ass")
            final = storage.store_path(settings, out, "variants", ".mp4")
        finally:
            shutil.rmtree(work, ignore_errors=True)

        cue_dicts = [c.as_dict() for c in cues]
        for fmt, stored in (*stored_text.items(), ("ass", stored_ass)):
            s.add(
                Subtitle(
                    variant_id=variant.id,
                    language=variant.language,
                    format=fmt,
                    storage_uri=stored.uri,
                    cues=cue_dicts,
                    issues=issues,
                    burned_in=fmt == "ass",
                )
            )
        variant.storage_uri, variant.sha256 = final.uri, final.sha256
        workflow.transition(s, variant, VideoStatus.QUALITY_CHECK, actor="subtitle")
        info = {
            "cues": len(cues),
            "issues": issues,
            "render_seconds": seconds,
            "max_cps": round(max((c.cps for c in cues), default=0.0), 1),
            "storage_uri": final.uri,
        }
        ctx.decide(
            "subtitles_burned",
            info,
            f"{len(cues)} Untertitel (max. {info['max_cps']} Zeichen/s) eingebrannt, "
            f"SRT und VTT gespeichert, Variante in {seconds} s gerendert"
            + (f"; Hinweise: {'; '.join(issues)}" if issues else "; gut lesbar."),
            entity_type="variants",
            entity_id=variant.id,
        )
        return AgentResult(output=info)


def _verify(settings: Any, clip: Clip, clip_s: float, out: media.Probe) -> list[str]:
    issues = []
    if out.video_codec != "h264" or out.audio_codec != "aac":
        issues.append(f"Codecs {out.video_codec}/{out.audio_codec} statt H.264/AAC")
    if (out.width, out.height) != (clip.width, clip.height):
        issues.append(f"Auflösung {out.width}×{out.height} statt {clip.width}×{clip.height}")
    if abs(out.duration_s - clip_s) > 0.5:
        issues.append(f"Länge {out.duration_s:.1f} s statt {clip_s:.1f} s")
    if out.size_bytes > settings.max_clip_bytes:
        issues.append(f"Datei zu groß ({out.size_bytes / 1024**2:.0f} MB)")
    return issues
