"""Agent 13: Quality Control (PROJECT_SPEC sections 6 and 9, Phase 10).

Works on variants in ``QUALITY_CHECK``. Checks the finished file before anything
can be planned for publishing:

* technical: file present and unchanged (SHA-256), decodes without errors,
  H.264/AAC, yuv420p, vertical 1080x1920 or 720x1280, at most 60 fps;
* platform: duration, title, description and file size within the limits of the
  channel's platform;
* rights: the source material is still licensed, the voice is cleared for
  commercial use, captions exist;
* picture and sound: loudness, true peak, silence, black and frozen picture,
  voice that did not fit its slot, caption readability;
* duplicates: exact copy (same file), visually near-identical video or the same
  scene of the same material already approved for the same channel. Sibling
  variants of one clip (A/B test) are allowed.

Blocking findings reject the variant regardless of the score; the others lower
the score, which must reach the operator's ``min_quality_score``. Approved
variants move on to ``READY_TO_PUBLISH``; rejected ones go to ``QUALITY_REJECTED``
with their reasons and a notification for the operator.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.base import Agent, AgentContext, AgentResult, PermanentError
from agents.gameplay_analysis import local_file
from agents.localization import latest_script
from core.config import Settings
from core.enums import NotificationLevel, VideoStatus
from models.access import Notification
from models.channels import Channel
from models.production import (
    Clip,
    QualityCheck,
    Scene,
    Subtitle,
    Variant,
    Voiceover,
)
from services import gates, media, quality, storage, workflow
from services.controls import get_operations
from services.quality import Check
from services.voice import Segment

#: Variants that count as "already in use" for duplicate detection.
DONE = (
    VideoStatus.QUALITY_APPROVED,
    VideoStatus.READY_TO_PUBLISH,
    VideoStatus.SCHEDULED,
    VideoStatus.PUBLISHED,
    VideoStatus.ANALYTICS_PENDING,
    VideoStatus.ANALYZED,
)
MAX_FPS = 60.0
SCENE_OVERLAP_SHARE = 0.5  # share of the shorter clip that makes "the same scene"
MAX_COMPARISONS = 500


class QualityControlAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        s, settings = ctx.session, ctx.settings
        variant = s.get(Variant, int(payload["entity_id"]))
        assert variant is not None  # guaranteed by the gate
        clip = s.get(Clip, variant.clip_id)
        assert clip is not None
        channel = s.get(Channel, variant.channel_id)
        assert channel is not None

        checks: list[Check] = []
        measured: dict[str, Any] = {}
        probe = _technical(settings, variant, checks)
        if probe is not None:
            measured["probe"] = probe.as_dict()
            checks += _platform(variant, channel, probe)
            checks += _picture_and_sound(settings, variant, probe, measured)
        checks += _rights_voice_subtitles(s, variant)
        checks += _duplicates(s, variant, clip)

        score = quality.score(checks)
        minimum = get_operations(s).min_quality_score
        blocking = [c for c in checks if c.blocking and not c.passed]
        failed = [c for c in checks if not c.passed]
        passed = not blocking and score >= minimum
        reasons = [c.detail for c in blocking] + [c.detail for c in failed if not c.blocking]
        if not blocking and score < minimum:
            reasons.insert(0, f"Qualitätswert {score:.2f} unter Mindestwert {minimum:.2f}")

        s.add(
            QualityCheck(
                variant_id=variant.id,
                passed=passed,
                score=score,
                checks={
                    "items": [c.as_dict() for c in checks],
                    "min_score": minimum,
                    "measured": measured,
                },
                reasons=reasons,
            )
        )
        variant.quality_score = score
        if passed:
            workflow.transition(s, variant, VideoStatus.QUALITY_APPROVED, actor="quality_control")
            s.flush()
            workflow.transition(s, variant, VideoStatus.READY_TO_PUBLISH, actor="quality_control")
        else:
            workflow.transition(s, variant, VideoStatus.QUALITY_REJECTED, actor="quality_control")
            s.add(
                Notification(
                    level=NotificationLevel.WARNING,
                    title=f"Variante #{variant.id} ({variant.variant_label}, "
                    f"{variant.language.value}) abgelehnt",
                    body="; ".join(reasons)[:2000],
                )
            )

        info = {
            "passed": passed,
            "score": score,
            "min_score": minimum,
            "blocking": [c.name for c in blocking],
            "findings": [c.name for c in failed if not c.blocking],
            "reasons": reasons,
        }
        ctx.decide(
            "quality_approved" if passed else "quality_rejected",
            info,
            (
                f"Freigegeben mit Qualitätswert {score:.2f} (Minimum {minimum:.2f})"
                if passed
                else f"Abgelehnt (Qualitätswert {score:.2f}): " + "; ".join(reasons)
            )
            + f". {len(checks) - len(failed)} von {len(checks)} Prüfungen bestanden.",
            inputs={"checks": [c.as_dict() for c in checks]},
            entity_type="variants",
            entity_id=variant.id,
        )
        return AgentResult(output=info)


# --- check groups -------------------------------------------------------------------


def _technical(settings: Settings, variant: Variant, checks: list[Check]) -> media.Probe | None:
    """File, integrity, decoding and format. Returns the probe if the file is usable."""
    if not variant.storage_uri:
        checks.append(Check("file", False, "Keine fertige Videodatei", blocking=True))
        return None
    try:
        path = local_file(settings, variant.storage_uri)
    except PermanentError as exc:  # not local or missing
        checks.append(Check("file", False, str(exc), blocking=True))
        return None
    digest = storage.sha256_file(path)
    if variant.sha256 and digest != variant.sha256:
        checks.append(
            Check("integrity", False, "Datei wurde nach dem Rendern verändert", blocking=True)
        )
        return None
    checks.append(Check("integrity", True, "Datei unverändert", values={"sha256": digest}))
    try:
        probe = media.probe(settings, path)
    except media.MediaError as exc:
        checks.append(Check("decode", False, f"Datei nicht lesbar: {exc}", blocking=True))
        return None
    errors = quality.decode_errors(settings, path)
    if errors:
        checks.append(
            Check("decode", False, f"Fehlerhafter Export: {errors[0][:200]}", blocking=True)
        )
        return None
    checks.append(Check("decode", True, "Vollständig dekodierbar"))

    problems = []
    if probe.video_codec != "h264" or probe.audio_codec != "aac":
        problems.append(f"Codecs {probe.video_codec}/{probe.audio_codec} statt H.264/AAC")
    if probe.pix_fmt not in (None, "yuv420p"):
        problems.append(f"Pixelformat {probe.pix_fmt} statt yuv420p")
    if (probe.width, probe.height) not in quality.VERTICAL_SIZES:
        problems.append(f"Auflösung {probe.width}×{probe.height} ist kein Hochformat 9:16")
    if probe.fps > MAX_FPS + 0.5:
        problems.append(f"{probe.fps:.0f} fps (max. {MAX_FPS:.0f})")
    checks.append(
        Check(
            "format",
            not problems,
            "; ".join(problems) or "H.264/AAC, Hochformat",
            blocking=True,
            values={"width": probe.width, "height": probe.height, "fps": probe.fps},
        )
    )
    return probe


def _platform(variant: Variant, channel: Channel, probe: media.Probe) -> list[Check]:
    rules = quality.PLATFORM_RULES.get(channel.platform.code)
    if rules is None:
        return [Check("platform", False, "Keine Regeln für diese Plattform", blocking=True)]
    title, description = variant.title or "", variant.description or ""
    problems = []
    if probe.duration_s > rules.max_duration_s:
        problems.append(f"Länge {probe.duration_s:.0f} s (max. {rules.max_duration_s:.0f} s)")
    if not title.strip():
        problems.append("Titel fehlt")
    elif len(title) > rules.max_title:
        problems.append(f"Titel {len(title)} Zeichen (max. {rules.max_title})")
    if len(description) > rules.max_description:
        problems.append(f"Beschreibung {len(description)} Zeichen (max. {rules.max_description})")
    if probe.size_bytes > rules.max_bytes:
        problems.append(f"Datei {probe.size_bytes / 1024**2:.0f} MB zu groß")
    return [
        Check(
            "platform",
            not problems,
            "; ".join(problems) or f"Innerhalb der Grenzen von {channel.platform.name}",
            blocking=True,
            values={"platform": channel.platform.code.value},
        )
    ]


def _picture_and_sound(
    settings: Settings, variant: Variant, probe: media.Probe, measured: dict[str, Any]
) -> list[Check]:
    assert variant.storage_uri
    path = local_file(settings, variant.storage_uri)
    checks = []
    try:
        lufs, peak = quality.loudness(settings, path)
        black_s, frozen_s = quality.black_and_frozen(settings, path)
    except (media.MediaError, ValueError) as exc:
        return [Check("measure", False, f"Messung fehlgeschlagen: {exc}", blocking=True)]
    measured.update(lufs=lufs, true_peak=peak, black_s=black_s, frozen_s=frozen_s)

    low, high = quality.LOUDNESS_RANGE
    if lufs <= quality.SILENT_LUFS:
        checks.append(
            Check("silent", False, "Kein hörbarer Ton", penalty=quality.PENALTY["silent"])
        )
    else:
        checks.append(
            Check(
                "loudness",
                low <= lufs <= high,
                f"Lautheit {lufs:.1f} LUFS" + ("" if low <= lufs <= high else " (Ziel -14)"),
                penalty=quality.PENALTY["loudness"],
                values={"lufs": lufs},
            )
        )
        checks.append(
            Check(
                "true_peak",
                peak <= quality.MAX_TRUE_PEAK,
                f"Spitzenpegel {peak:.1f} dBTP"
                + ("" if peak <= quality.MAX_TRUE_PEAK else " (Übersteuerung möglich)"),
                penalty=quality.PENALTY["true_peak"],
                values={"true_peak": peak},
            )
        )
    duration = max(0.1, probe.duration_s)
    if black_s >= duration - 0.5:
        checks.append(Check("black", False, "Bild ist durchgehend schwarz", blocking=True))
    else:
        checks.append(
            Check(
                "black",
                black_s <= quality.MAX_BLACK_S,
                f"{black_s:.1f} s schwarzes Bild",
                penalty=quality.PENALTY["black"],
                values={"black_s": black_s},
            )
        )
    share = frozen_s / duration
    checks.append(
        Check(
            "frozen",
            share <= quality.MAX_FREEZE_SHARE,
            f"{share:.0%} Standbild",
            penalty=quality.PENALTY["frozen"],
            values={"frozen_s": frozen_s},
        )
    )
    return checks


def _rights_voice_subtitles(s: Session, variant: Variant) -> list[Check]:
    checks = []
    source = gates.source_file(s, variant)
    problem = "Quellmaterial nicht gefunden" if source is None else gates.rights_check(s, source)
    checks.append(Check("rights", problem is None, problem or "Lizenz gültig", blocking=True))

    vo = s.scalar(
        select(Voiceover)
        .where(Voiceover.variant_id == variant.id)
        .order_by(Voiceover.id.desc())
        .limit(1)
    )
    if vo is None:
        checks.append(Check("voice", False, "Keine Stimme vorhanden", blocking=True))
    else:
        checks.append(
            Check(
                "voice",
                vo.commercial_use_cleared,
                f"Stimme {vo.provider}/{vo.voice_id}"
                + ("" if vo.commercial_use_cleared else " ohne kommerzielle Nutzungsrechte"),
                blocking=True,
            )
        )
        overflow = sum(Segment(**seg).overflow_s for seg in vo.segments or [])
        checks.append(
            Check(
                "voice_overflow",
                overflow <= 0.05,
                f"Sprechtext {overflow:.1f} s zu lang für seine Szene"
                if overflow > 0.05
                else "Sprechtext passt in die Szenen",
                penalty=quality.PENALTY["voice_overflow"],
            )
        )

    subs = s.scalars(select(Subtitle).where(Subtitle.variant_id == variant.id)).all()
    formats = {sub.format for sub in subs}
    missing = {"srt", "ass"} - formats
    checks.append(
        Check(
            "subtitles",
            not missing,
            "Untertitel fehlen" if missing else "Untertitel eingebrannt und als Datei",
            blocking=True,
            values={"formats": sorted(formats)},
        )
    )
    issues = next((sub.issues for sub in subs if sub.format == "srt"), []) or []
    checks.append(
        Check(
            "subtitle_issue",
            not issues,
            "; ".join(issues[:3]) if issues else "Untertitel gut lesbar",
            penalty=quality.PENALTY["subtitle_issue"],
        )
    )
    script = latest_script(s, variant.id)
    if script is not None and script.language != variant.language:
        checks.append(Check("language", False, "Skriptsprache passt nicht", blocking=True))
    return checks


def _duplicates(s: Session, variant: Variant, clip: Clip) -> list[Check]:
    """Exact, visual and scene duplicates against variants already in use."""
    checks = []
    if variant.sha256:
        same = s.scalar(
            select(Variant.id).where(
                Variant.sha256 == variant.sha256,
                Variant.id != variant.id,
                Variant.status.in_(DONE),
            )
        )
        checks.append(
            Check(
                "duplicate_exact",
                same is None,
                f"Identische Datei wie Variante #{same}" if same else "Keine identische Datei",
                blocking=True,
            )
        )

    scene = s.get(Scene, clip.scene_id)
    others = s.execute(
        select(Variant, Clip, Scene)
        .join(Clip, Clip.id == Variant.clip_id)
        .join(Scene, Scene.id == Clip.scene_id)
        .where(
            Variant.channel_id == variant.channel_id,
            Variant.id != variant.id,
            Variant.clip_id != variant.clip_id,  # siblings of one clip are an A/B test
            Variant.status.in_(DONE),
        )
        .order_by(Variant.id.desc())
        .limit(MAX_COMPARISONS)
    ).all()
    worst: tuple[float, int] | None = None
    same_scene: int | None = None
    for other, other_clip, other_scene in others:
        sim = quality.similarity(variant.fingerprint, other.fingerprint)
        if worst is None or sim > worst[0]:
            worst = (sim, other.id)
        if scene is not None and other_scene.gameplay_file_id == scene.gameplay_file_id:
            shorter = min(clip.end_s - clip.start_s, other_clip.end_s - other_clip.start_s)
            shared = quality.overlap_s(
                (clip.start_s, clip.end_s), (other_clip.start_s, other_clip.end_s)
            )
            if shorter > 0 and shared / shorter >= SCENE_OVERLAP_SHARE and same_scene is None:
                same_scene = other.id
    similar = worst is not None and worst[0] >= quality.DUPLICATE_SHARE
    checks.append(
        Check(
            "duplicate_visual",
            not similar,
            f"Bild zu {worst[0]:.0%} gleich wie Variante #{worst[1]}"
            if similar and worst
            else "Kein ähnliches Video auf diesem Kanal",
            blocking=True,
            values={"similarity": worst[0] if worst else 0.0, "compared": len(others)},
        )
    )
    checks.append(
        Check(
            "duplicate_scene",
            same_scene is None,
            f"Gleiche Szene wie Variante #{same_scene} auf diesem Kanal"
            if same_scene
            else "Szene auf diesem Kanal neu",
            blocking=True,
        )
    )
    siblings = s.scalars(
        select(Variant.variant_label).where(
            Variant.clip_id == variant.clip_id,
            Variant.channel_id == variant.channel_id,
            Variant.id != variant.id,
        )
    ).all()
    if siblings:
        checks.append(
            Check(
                "ab_test",
                True,
                "A/B-Test mit Variante " + ", ".join(sorted(siblings)),
                values={"siblings": sorted(siblings)},
            )
        )
    return checks
