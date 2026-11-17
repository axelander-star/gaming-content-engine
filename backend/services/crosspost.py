"""One video on every platform (Ausbau A6).

The clip pipeline makes a variant for the first channel of a topic area per
language (German and English). Once such a variant has passed the quality check
(``READY_TO_PUBLISH``), this step copies it to the other channels of the same
topic area and language, for example from YouTube DE to TikTok DE and Instagram
DE. A copy

* uses the same, already checked file (no new render, no extra cost),
* gets title, description and hashtags fitted to the platform (rule based: title
  and caption length, number of hashtags, ``#Shorts`` on YouTube),
* enters at ``READY_TO_PUBLISH`` with a quality record that points to the
  original, so the Publishing Strategy Agent decides per channel if and when it
  goes out; the amount stays dynamic.

Campaign clips are not copied (the brief names its channels), neither are library
videos (the approval center prepares those per channel) nor copies themselves.
Old videos are left alone: only originals from the last ``LOOKBACK_DAYS``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import PlatformCode, VideoStatus
from models.channels import Channel
from models.production import Clip, QualityCheck, Variant
from services import affiliate, approval, campaigns, quality, workflow

ACTOR = "crosspost"
LOOKBACK_DAYS = 7
SOURCE_STATUSES = (VideoStatus.READY_TO_PUBLISH, VideoStatus.SCHEDULED)
#: Hashtags per platform: few on TikTok/Instagram read as a person, not a bot.
HASHTAGS = {
    PlatformCode.YOUTUBE: 5,
    PlatformCode.TIKTOK: 5,
    PlatformCode.INSTAGRAM: 8,
    PlatformCode.FACEBOOK: 3,
}
#: Description length per platform; short captions work better in the feed apps.
DESCRIPTION = {
    PlatformCode.YOUTUBE: 1000,
    PlatformCode.TIKTOK: 300,
    PlatformCode.INSTAGRAM: 600,
    PlatformCode.FACEBOOK: 400,
}


def origin_id(variant: Variant) -> int | None:
    value = (variant.concept or {}).get("crosspost_of")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _cut(text: str, limit: int) -> str:
    text = " ".join(text.split()) if "\n" not in text else text.strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return f"{cut}…"


@dataclass(frozen=True)
class Texts:
    title: str
    description: str
    hashtags: list[str]


def fit_texts(variant: Variant, code: PlatformCode) -> Texts:
    """Title, description and hashtags of ``variant`` fitted to ``code``."""
    limits = quality.PLATFORM_RULES[code]
    rules = approval.RULES[code]
    tags = approval.clean_hashtags(variant.hashtags or [], rules.hashtags_max)
    tags = [t for t in tags if t.lower() not in {"shorts", "reels", "fyp"}]
    if code == PlatformCode.YOUTUBE:
        tags = [*tags[: HASHTAGS[code] - 1], "Shorts"]
    else:
        tags = tags[: HASHTAGS[code]]
    title = _cut(variant.title or "", min(limits.max_title, rules.title_max))
    description = _cut(variant.description or "", DESCRIPTION[code])
    return Texts(title, description, tags)


def targets(session: Session, variant: Variant) -> list[Channel]:
    """Other channels of the topic area and language that do not have this video yet."""
    if variant.clip_id is None or origin_id(variant) is not None:
        return []
    channels = session.scalars(
        select(Channel)
        .where(
            Channel.content_project_id == variant.content_project_id,
            Channel.language == variant.language,
            Channel.id != variant.channel_id,
        )
        .order_by(Channel.id)
    ).all()
    taken = set(
        session.scalars(
            select(Variant.channel_id).where(
                Variant.clip_id == variant.clip_id,
                Variant.variant_label == variant.variant_label,
            )
        )
    )
    return [
        c for c in channels
        if c.id not in taken and c.platform.code in approval.RULES and not c.is_paused
    ]  # fmt: skip


def copy_to(session: Session, variant: Variant, channel: Channel) -> Variant | str:
    """The copy for ``channel``, or the reason it cannot go there."""
    code = channel.platform.code
    clip = session.get(Clip, variant.clip_id) if variant.clip_id else None
    duration = (clip.duration_s if clip else None) or 0.0
    limit = quality.PLATFORM_RULES[code].max_duration_s
    if duration > limit:
        return f"{channel.platform.name}: Video {duration:.0f} s, erlaubt {limit:.0f} s"
    texts = fit_texts(variant, code)
    if not texts.title:
        return "Titel fehlt"
    copy = Variant(
        clip_id=variant.clip_id,
        channel_id=channel.id,
        content_project_id=variant.content_project_id,
        language=variant.language,
        variant_label=variant.variant_label,
        video_format=variant.video_format,
        hook_type=variant.hook_type,
        concept={**(variant.concept or {}), "crosspost_of": variant.id},
        status=VideoStatus.READY_TO_PUBLISH,
        storage_uri=variant.storage_uri,
        sha256=variant.sha256,
        fingerprint=variant.fingerprint,
        title=texts.title,
        description=texts.description,
        hashtags=texts.hashtags,
        publish_options={},
        quality_score=variant.quality_score,
    )
    affiliate.strip_for_channel(session, copy, channel.id)
    session.add(copy)
    session.flush()
    session.add(
        QualityCheck(
            variant_id=copy.id,
            passed=True,
            score=variant.quality_score,
            checks={
                "source": "crosspost",
                "crosspost_of": variant.id,
                "items": [
                    quality.Check(
                        "platform",
                        True,
                        f"Gleiches Video wie Variante #{variant.id}, Texte für "
                        f"{channel.platform.name} angepasst",
                        values={"platform": code.value},
                    ).as_dict()
                ],
            },
            reasons=[],
        )
    )
    workflow.record_entry(session, copy, actor=ACTOR)
    return copy


def spread(session: Session, variant: Variant) -> dict[str, Any]:
    made, skipped = [], []
    for channel in targets(session, variant):
        result = copy_to(session, variant, channel)
        if isinstance(result, str):
            skipped.append({"channel_id": channel.id, "reason": result})
        else:
            made.append({"channel_id": channel.id, "variant_id": result.id})
    session.flush()
    return {"variant_id": variant.id, "copies": made, "skipped": skipped}


def sweep(
    session: Session, settings: Settings, now: datetime | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """Copy fresh, approved clip variants to the other platforms; commits."""
    if not settings.crosspost_enabled:
        return []
    now = now or datetime.now(UTC)
    rows = session.scalars(
        select(Variant)
        .where(
            Variant.clip_id.is_not(None),
            Variant.status.in_(SOURCE_STATUSES),
            Variant.updated_at >= now - timedelta(days=LOOKBACK_DAYS),
        )
        .order_by(Variant.id)
        .limit(limit)
    ).all()
    out = []
    for variant in rows:
        if origin_id(variant) is not None or campaigns.for_variant(session, variant) is not None:
            continue
        result = spread(session, variant)
        if result["copies"] or result["skipped"]:
            out.append(result)
    session.commit()
    return out
