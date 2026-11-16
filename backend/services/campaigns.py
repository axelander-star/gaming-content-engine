"""Clipping campaigns (Content Rewards) as a licensed material source.

Flow:

1. The operator enters a campaign from its brief: page, pay per 1,000 views,
   platforms, languages, required hashtags and disclosure, clip length, end date,
   and the channels that are connected to the campaign. :func:`create` turns it
   into a source of type ``campaign`` with an approved license that only covers
   what the brief allows.
2. Material of the campaign is uploaded with that license and runs through the
   normal clip pipeline. The analysis creates variants only for the campaign
   channels (:func:`target_channels`).
3. Quality Control puts the disclosure and hashtags into the post text
   (:func:`apply_texts`), checks the campaign rules (:func:`rule_checks`) and stops
   at ``QUALITY_APPROVED``: a person approves every campaign clip
   (:func:`approve`).
4. When the post is published, :func:`on_published` creates a submission with
   the link and a deadline (``submission_window_min`` after posting). There is no
   official API for clippers, so the operator submits the link on the campaign
   page and ticks it off (:func:`mark_submitted`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import (
    CampaignStatus,
    ContentProjectStatus,
    Language,
    LicenseStatus,
    NotificationLevel,
    PlatformCode,
    PublishingJobStatus,
    SourceType,
    SubmissionStatus,
    VideoStatus,
)
from models.access import AuditLog, Notification
from models.campaigns import Campaign, CampaignSubmission
from models.channels import Channel
from models.production import Clip, GameplayFile, Variant
from models.projects import ContentProject
from models.publishing import Post, PublishingJob
from models.rights import Asset, License, Source
from models.trends import Game
from services import approval, gates, quality, workflow

ACTOR = "campaigns"
PROVIDER = "content_rewards"
#: Platforms a campaign clip can be published to by this system.
PLATFORMS = tuple(code.value for code in approval.RULES)
LANGUAGES = tuple(lang.value for lang in Language)
#: Share Content Rewards keeps from CPM payouts (estimate only).
PLATFORM_FEE = Decimal("0.10")
EDITABLE_FIELDS = (
    "name",
    "url",
    "game_id",
    "cpm_usd",
    "budget_usd",
    "min_views",
    "max_payout_per_clip_usd",
    "platforms",
    "languages",
    "channel_ids",
    "required_hashtags",
    "disclosure",
    "required_text",
    "min_duration_s",
    "max_duration_s",
    "submission_window_min",
    "ends_on",
    "brief",
    "material_links",
)


class CampaignError(ValueError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


# --- lookups --------------------------------------------------------------------------


def for_source(session: Session, source_id: int | None) -> Campaign | None:
    if source_id is None:
        return None
    return session.scalar(select(Campaign).where(Campaign.source_id == source_id))


def for_material(session: Session, material: GameplayFile) -> Campaign | None:
    asset = session.get(Asset, material.asset_id)
    return for_source(session, asset.source_id) if asset else None


def for_variant(session: Session, variant: Variant) -> Campaign | None:
    """Campaign of a clip variant (library videos never belong to a campaign)."""
    if variant.clip_id is None:
        return None
    material = gates.source_file(session, variant)
    return for_material(session, material) if material else None


def target_channels(session: Session, campaign: Campaign, project_id: int) -> list[Channel]:
    """Campaign channels of the topic area whose platform and language the brief allows."""
    ids = [int(i) for i in campaign.channel_ids or []]
    if not ids:
        return []
    channels = session.scalars(
        select(Channel).where(Channel.id.in_(ids), Channel.content_project_id == project_id)
    ).all()
    return [
        c
        for c in sorted(channels, key=lambda c: c.id)
        if c.platform.code.value in (campaign.platforms or [])
        and c.language.value in (campaign.languages or [])
    ]


# --- create and edit ------------------------------------------------------------------


def _clean_list(values: Any, allowed: tuple[str, ...], what: str) -> list[str]:
    out = list(dict.fromkeys(str(v).strip().lower() for v in values or [] if str(v).strip()))
    unknown = [v for v in out if v not in allowed]
    if unknown:
        raise CampaignError(f"Unbekannte {what}: {', '.join(unknown)}")
    if not out:
        raise CampaignError(f"{what}: mindestens eine Auswahl nötig")
    return out


def _validate(session: Session, campaign: Campaign) -> None:
    """Check a campaign after its fields were set (create and update)."""
    campaign.platforms = _clean_list(campaign.platforms, PLATFORMS, "Plattformen")
    campaign.languages = _clean_list(campaign.languages, LANGUAGES, "Sprachen")
    campaign.required_hashtags = approval.clean_hashtags(campaign.required_hashtags, 30)
    campaign.material_links = [
        str(u).strip() for u in campaign.material_links or [] if str(u).strip()
    ][:20]
    if not str(campaign.url or "").startswith("https://"):
        raise CampaignError("Kampagnenseite muss mit https:// beginnen")
    for link in campaign.material_links:
        if not link.startswith("https://"):
            raise CampaignError(f"Materiallink muss mit https:// beginnen: {link[:80]}")
    if campaign.game_id is not None and session.get(Game, campaign.game_id) is None:
        raise CampaignError("Spiel nicht gefunden", 404)
    lo, hi = campaign.min_duration_s, campaign.max_duration_s
    if lo is not None and hi is not None and lo > hi:
        raise CampaignError("Mindestlänge ist größer als Höchstlänge")
    if not 5 <= int(campaign.submission_window_min or 0) <= 24 * 60:
        raise CampaignError("Einreichungsfrist muss zwischen 5 Minuten und 24 Stunden liegen")
    ids = list(dict.fromkeys(int(i) for i in campaign.channel_ids or []))
    if not ids:
        raise CampaignError("Mindestens einen Kanal wählen, der mit der Kampagne verbunden ist")
    for cid in ids:
        channel = session.get(Channel, cid)
        if channel is None:
            raise CampaignError(f"Kanal #{cid} nicht gefunden", 404)
        if channel.content_project_id != campaign.content_project_id:
            raise CampaignError(f"Kanal „{channel.name}“ gehört zu einem anderen Themenbereich")
        if channel.platform.code.value not in campaign.platforms:
            raise CampaignError(
                f"Kanal „{channel.name}“: Plattform {channel.platform.name} zählt in der "
                "Kampagne nicht"
            )
        if channel.language.value not in campaign.languages:
            raise CampaignError(
                f"Kanal „{channel.name}“: Sprache {channel.language.value} ist in der "
                "Kampagne nicht erlaubt"
            )
    campaign.channel_ids = ids


def _sync_license(campaign: Campaign, lic: License, source: Source) -> None:
    """The license mirrors the brief: only these platforms, languages and dates."""
    lic.allowed_platforms = list(campaign.platforms)
    lic.allowed_languages = list(campaign.languages)
    lic.valid_until = campaign.ends_on
    lic.restrictions = ("Nur für Clips dieser Kampagne. " + (campaign.brief or "").strip()).strip()[
        :4000
    ]
    lic.document_uri = campaign.url
    source.name = f"Kampagne: {campaign.name}"[:200]
    source.url = campaign.url


def create(
    session: Session,
    data: dict[str, Any],
    user_id: int | None,
    *,
    now: datetime | None = None,
) -> Campaign:
    """Create a campaign with its own source and an approved license.

    ``rights_confirmed`` must be true: the operator confirms that the brief allows
    edited short clips of the campaign material, commercial and monetized, with the
    music and other parts of the material.
    """
    now = now or datetime.now(UTC)
    if data.get("rights_confirmed") is not True:
        raise CampaignError(
            "Bitte bestätigen, dass die Kampagne das Schneiden und Veröffentlichen ihres "
            "Materials erlaubt"
        )
    project = session.get(ContentProject, data.get("content_project_id"))
    if project is None:
        raise CampaignError("Themenbereich nicht gefunden", 404)
    if project.status == ContentProjectStatus.ARCHIVED:
        raise CampaignError("Themenbereich ist archiviert")
    campaign = Campaign(
        content_project_id=project.id,
        provider=PROVIDER,
        status=CampaignStatus.ACTIVE,
        submission_window_min=30,
        created_by_user_id=user_id,
    )
    for key in EDITABLE_FIELDS:
        if key in data and data[key] is not None:
            setattr(campaign, key, data[key])
    if not str(campaign.name or "").strip():
        raise CampaignError("Name fehlt")
    campaign.name = " ".join(str(campaign.name).split())[:200]
    _validate(session, campaign)

    source = Source(
        type=SourceType.CAMPAIGN,
        name="",
        provenance_notes=(
            "Clipping-Kampagne (Content Rewards). Material vom Kampagnen-Inhaber; "
            "Lizenz laut Kampagnenbeschreibung, nur für diese Kampagne."
        ),
    )
    lic = License(
        status=LicenseStatus.APPROVED,
        allows_commercial_use=True,
        allows_editing=True,
        allows_short_form=True,
        allows_monetization=True,
        music_cleared=True,
        verified_by_user_id=user_id,
        verified_at=now,
    )
    _sync_license(campaign, lic, source)
    session.add(source)
    session.flush()
    lic.source_id = source.id
    session.add(lic)
    session.flush()
    campaign.source_id = source.id
    campaign.license_id = lic.id
    session.add(campaign)
    session.flush()
    _audit(session, campaign, "campaign_created", user_id, {"name": campaign.name})
    return campaign


def update(
    session: Session, campaign: Campaign, data: dict[str, Any], user_id: int | None
) -> Campaign:
    for key in EDITABLE_FIELDS:
        if key in data:
            setattr(campaign, key, data[key])
    if not str(campaign.name or "").strip():
        raise CampaignError("Name fehlt")
    _validate(session, campaign)
    lic = session.get(License, campaign.license_id)
    source = session.get(Source, campaign.source_id)
    assert lic is not None and source is not None
    _sync_license(campaign, lic, source)
    _audit(session, campaign, "campaign_updated", user_id, {"fields": sorted(data)})
    return campaign


def set_status(
    session: Session, campaign: Campaign, status: CampaignStatus, user_id: int | None
) -> Campaign:
    """Pause, end or reactivate. A campaign that is not active stops new work: the
    rights check of its material fails, so no clip is made or published."""
    before = campaign.status
    campaign.status = status
    _audit(
        session,
        campaign,
        "campaign_status",
        user_id,
        {"before": before.value, "after": status.value},
    )
    return campaign


def status_problem(campaign: Campaign) -> str | None:
    if campaign.status == CampaignStatus.PAUSED:
        return "Kampagne ist pausiert"
    if campaign.status == CampaignStatus.ENDED:
        return "Kampagne ist beendet"
    return None


# --- texts and rules ------------------------------------------------------------------


def apply_texts(campaign: Campaign, variant: Variant) -> bool:
    """Put disclosure, required text and hashtags into the post text (idempotent)."""
    changed = False
    description = (variant.description or "").strip()
    extra = (campaign.required_text or "").strip()
    if extra and extra not in description:
        description = f"{description}\n\n{extra}".strip()
    disclosure = (campaign.disclosure or "").strip()
    if disclosure and not description.startswith(disclosure):
        description = f"{disclosure}\n{description}".strip()
    if description != (variant.description or "").strip():
        variant.description = description
        changed = True
    required = approval.clean_hashtags(campaign.required_hashtags, 30)
    have = list(variant.hashtags or [])
    lower = {t.lower() for t in have}
    missing = [t for t in required if t.lower() not in lower]
    if missing:
        # Required hashtags first so a platform limit never cuts them off.
        variant.hashtags = approval.clean_hashtags([*required, *have], 30)
        changed = True
    return changed


def text_problems(campaign: Campaign, variant: Variant) -> list[str]:
    problems = []
    description = (variant.description or "").strip()
    disclosure = (campaign.disclosure or "").strip()
    if disclosure and not description.startswith(disclosure):
        problems.append(f"Werbehinweis „{disclosure}“ fehlt am Anfang der Beschreibung")
    extra = (campaign.required_text or "").strip()
    if extra and extra not in description:
        problems.append(f"Pflichttext „{extra[:60]}“ fehlt")
    have = {t.lower() for t in variant.hashtags or []}
    missing = [t for t in campaign.required_hashtags or [] if str(t).lower() not in have]
    if missing:
        problems.append("Pflicht-Hashtags fehlen: " + ", ".join(f"#{t}" for t in missing))
    return problems


def rule_checks(
    session: Session, campaign: Campaign, variant: Variant, duration_s: float | None
) -> list[quality.Check]:
    """Campaign rules for one clip; all blocking (a rejected clip earns nothing)."""
    channel = session.get(Channel, variant.channel_id)
    assert channel is not None
    problem = status_problem(campaign)
    allowed = {c.id for c in target_channels(session, campaign, variant.content_project_id)}
    checks = [
        quality.Check(
            "campaign_active",
            problem is None,
            problem or f"Kampagne „{campaign.name}“ aktiv",
            blocking=True,
        ),
        quality.Check(
            "campaign_channel",
            channel.id in allowed,
            f"Kanal „{channel.name}“ "
            + ("zählt in der Kampagne" if channel.id in allowed else "ist nicht für die Kampagne")
            + f" ({channel.platform.code.value}, {channel.language.value})",
            blocking=True,
        ),
    ]
    lo, hi = campaign.min_duration_s, campaign.max_duration_s
    if lo is not None or hi is not None:
        d = float(duration_s or 0.0)
        ok = (lo is None or d >= lo) and (hi is None or d <= hi)
        span = f"{lo if lo is not None else 0}–{hi if hi is not None else '∞'} s"
        checks.append(
            quality.Check(
                "campaign_duration",
                ok,
                f"Länge {d:.1f} s (Kampagne: {span})",
                blocking=True,
                values={"duration_s": d, "min": lo, "max": hi},
            )
        )
    problems = text_problems(campaign, variant)
    checks.append(
        quality.Check(
            "campaign_texts",
            not problems,
            "; ".join(problems) or "Werbehinweis, Pflichttext und Hashtags vorhanden",
            blocking=True,
        )
    )
    return checks


# --- approval of campaign clips -------------------------------------------------------


def _campaign_variant(session: Session, variant: Variant) -> Campaign:
    campaign = for_variant(session, variant)
    if campaign is None:
        raise CampaignError("Kein Clip einer Kampagne", 404)
    return campaign


def approve(session: Session, variant: Variant, user_id: int | None) -> Variant:
    """Release a campaign clip; the Publishing Strategy Agent picks the time."""
    campaign = _campaign_variant(session, variant)
    if variant.status != VideoStatus.QUALITY_APPROVED:
        raise CampaignError(f"Clip ist {variant.status.value}, nicht freigabebereit", 409)
    code = approval.platform_of(session, variant)
    problems = approval.text_problems(variant, code) + text_problems(campaign, variant)
    for check in rule_checks(session, campaign, variant, clip_duration(session, variant)):
        if not check.passed and check.name != "campaign_texts":
            problems.append(check.detail)
    problem = gates.source_problem(session, variant)
    if problem:
        problems.append(problem)
    if problems:
        raise CampaignError("; ".join(problems))
    if code == PlatformCode.YOUTUBE:
        # Views only count on public videos.
        variant.publish_options = {**(variant.publish_options or {}), "privacy": "public"}
    workflow.transition(session, variant, VideoStatus.READY_TO_PUBLISH, actor=ACTOR)
    _log_variant(session, variant, "approved", user_id)
    return variant


def withdraw(session: Session, variant: Variant, user_id: int | None) -> Variant:
    _campaign_variant(session, variant)
    if variant.status == VideoStatus.SCHEDULED:
        jobs = session.scalars(
            select(PublishingJob).where(
                PublishingJob.variant_id == variant.id,
                PublishingJob.status.in_(
                    [PublishingJobStatus.SCHEDULED, PublishingJobStatus.RUNNING]
                ),
            )
        ).all()
        if any(j.status == PublishingJobStatus.RUNNING for j in jobs):
            raise CampaignError("Die Veröffentlichung läuft gerade", 409)
        for job in jobs:
            job.status = PublishingJobStatus.CANCELLED
            job.last_error = "Freigabe zurückgezogen"
        workflow.transition(session, variant, VideoStatus.READY_TO_PUBLISH, actor=ACTOR)
    if variant.status != VideoStatus.READY_TO_PUBLISH:
        raise CampaignError(f"Clip ist {variant.status.value}, nichts zurückzuziehen", 409)
    workflow.transition(session, variant, VideoStatus.QUALITY_APPROVED, actor=ACTOR)
    _log_variant(session, variant, "withdrawn", user_id)
    return variant


def discard(session: Session, variant: Variant, user_id: int | None) -> Variant:
    _campaign_variant(session, variant)
    if variant.status != VideoStatus.QUALITY_APPROVED:
        raise CampaignError("Nur nicht freigegebene Clips lassen sich verwerfen", 409)
    workflow.transition(session, variant, VideoStatus.ARCHIVED, actor=ACTOR)
    _log_variant(session, variant, "discarded", user_id)
    return variant


def edit_texts(
    session: Session,
    variant: Variant,
    *,
    title: str | None = None,
    description: str | None = None,
    hashtags: list[str] | str | None = None,
) -> Variant:
    campaign = _campaign_variant(session, variant)
    if variant.status != VideoStatus.QUALITY_APPROVED:
        raise CampaignError("Freigegebene Clips zuerst zurückziehen, dann bearbeiten", 409)
    rules = approval.RULES[approval.platform_of(session, variant)]
    if title is not None:
        variant.title = " ".join(title.split())[: rules.title_max]
    if description is not None:
        variant.description = description.strip()
    if hashtags is not None:
        variant.hashtags = approval.clean_hashtags(hashtags, rules.hashtags_max)
    apply_texts(campaign, variant)  # rules of the brief stay in the text
    return variant


def clip_duration(session: Session, variant: Variant) -> float | None:
    clip = session.get(Clip, variant.clip_id) if variant.clip_id else None
    if clip is None:
        return None
    return clip.duration_s if clip.duration_s is not None else clip.end_s - clip.start_s


# --- submissions ----------------------------------------------------------------------


def on_published(
    session: Session, variant: Variant, post: Post, now: datetime | None = None
) -> CampaignSubmission | None:
    """Create the submission of a published campaign clip (once per post)."""
    campaign = for_variant(session, variant)
    if campaign is None:
        return None
    existing = session.scalar(
        select(CampaignSubmission).where(CampaignSubmission.post_id == post.id)
    )
    if existing is not None:
        return existing
    now = now or datetime.now(UTC)
    posted_at = post.published_at or now
    window = timedelta(minutes=campaign.submission_window_min)
    sub = CampaignSubmission(
        campaign_id=campaign.id,
        post_id=post.id,
        variant_id=variant.id,
        channel_id=post.channel_id,
        post_url=post.url,
        posted_at=posted_at,
        deadline_at=posted_at + window if post.url else None,
        status=SubmissionStatus.OPEN,
    )
    session.add(sub)
    channel = session.get(Channel, post.channel_id)
    where = channel.name if channel else f"Kanal #{post.channel_id}"
    if post.url:
        body = (
            f"Link: {post.url}\nBis {sub.deadline_at:%H:%M} UTC auf der Kampagnenseite "
            f"einreichen: {campaign.url}"
        )
    else:
        body = (
            "Der Beitrag hat noch keinen öffentlichen Link (Test oder Entwurf). Nach dem "
            "Veröffentlichen den Link unter Kampagnen eintragen und dann einreichen."
        )
    session.add(
        Notification(
            level=NotificationLevel.WARNING if post.url else NotificationLevel.INFO,
            title=f"Clip für „{campaign.name}“ auf {where} veröffentlicht – jetzt einreichen"[:200],
            body=body,
        )
    )
    session.flush()
    return sub


def set_link(
    session: Session,
    sub: CampaignSubmission,
    url: str,
    user_id: int | None,
    now: datetime | None = None,
) -> CampaignSubmission:
    """Enter the public link of a post that had none (draft finished in the app)."""
    url = url.strip()
    if not url.startswith("https://"):
        raise CampaignError("Link muss mit https:// beginnen")
    if sub.status != SubmissionStatus.OPEN:
        raise CampaignError("Nur offene Einreichungen lassen sich ändern", 409)
    now = now or datetime.now(UTC)
    campaign = session.get(Campaign, sub.campaign_id)
    assert campaign is not None
    sub.post_url = url[:1000]
    if sub.deadline_at is None:
        # The operator just posted the draft: the window starts about now.
        sub.posted_at = now
        sub.deadline_at = now + timedelta(minutes=campaign.submission_window_min)
    _log_submission(session, sub, "link_set", user_id)
    return sub


def mark_submitted(
    session: Session, sub: CampaignSubmission, user_id: int | None, now: datetime | None = None
) -> CampaignSubmission:
    if sub.status == SubmissionStatus.SUBMITTED:
        return sub
    if not sub.post_url:
        raise CampaignError("Erst den Link des Beitrags eintragen")
    now = now or datetime.now(UTC)
    sub.status = SubmissionStatus.SUBMITTED
    sub.submitted_at = now
    sub.submitted_by_user_id = user_id
    _log_submission(session, sub, "submitted", user_id)
    return sub


def skip(
    session: Session, sub: CampaignSubmission, user_id: int | None, note: str | None = None
) -> CampaignSubmission:
    if sub.status == SubmissionStatus.SUBMITTED:
        raise CampaignError("Schon eingereicht", 409)
    sub.status = SubmissionStatus.SKIPPED
    sub.note = (note or "").strip()[:500] or None
    _log_submission(session, sub, "skipped", user_id)
    return sub


def reopen(session: Session, sub: CampaignSubmission, user_id: int | None) -> CampaignSubmission:
    """Undo „eingereicht“ or „übersprungen“ (e.g. ticked by mistake)."""
    sub.status = SubmissionStatus.OPEN
    sub.submitted_at = None
    sub.submitted_by_user_id = None
    _log_submission(session, sub, "reopened", user_id)
    return sub


@dataclass(frozen=True)
class SubmissionState:
    #: ``open``, ``overdue``, ``needs_link``, ``submitted`` or ``skipped``.
    state: str
    seconds_left: int | None
    late: bool


def state_of(sub: CampaignSubmission, now: datetime | None = None) -> SubmissionState:
    now = now or datetime.now(UTC)
    deadline = sub.deadline_at
    if sub.status == SubmissionStatus.SUBMITTED:
        late = bool(deadline and sub.submitted_at and sub.submitted_at > deadline)
        return SubmissionState("submitted", None, late)
    if sub.status == SubmissionStatus.SKIPPED:
        return SubmissionState("skipped", None, False)
    if not sub.post_url or deadline is None:
        return SubmissionState("needs_link", None, False)
    left = int((deadline - now).total_seconds())
    return SubmissionState("open" if left > 0 else "overdue", max(left, 0), left <= 0)


def estimated_payout(campaign: Campaign, views: int) -> Decimal | None:
    """Rough payout for ``views`` verified views after the platform fee and cap."""
    if campaign.cpm_usd is None:
        return None
    if campaign.min_views and views < campaign.min_views:
        return Decimal("0")
    gross = Decimal(views) / 1000 * Decimal(campaign.cpm_usd)
    if campaign.max_payout_per_clip_usd is not None:
        gross = min(gross, Decimal(campaign.max_payout_per_clip_usd))
    return (gross * (1 - PLATFORM_FEE)).quantize(Decimal("0.01"))


# --- audit ----------------------------------------------------------------------------


def _audit(
    session: Session, campaign: Campaign, action: str, user_id: int | None, after: dict[str, Any]
) -> None:
    session.add(
        AuditLog(
            actor_user_id=user_id,
            actor_agent=ACTOR,
            action=action,
            entity_type="campaigns",
            entity_id=campaign.id,
            after=after,
        )
    )


def _log_variant(session: Session, variant: Variant, action: str, user_id: int | None) -> None:
    session.add(
        AuditLog(
            actor_user_id=user_id,
            actor_agent=ACTOR,
            action=f"campaign_clip_{action}",
            entity_type="variants",
            entity_id=variant.id,
            after={"status": variant.status.value},
        )
    )


def _log_submission(
    session: Session, sub: CampaignSubmission, action: str, user_id: int | None
) -> None:
    session.add(
        AuditLog(
            actor_user_id=user_id,
            actor_agent=ACTOR,
            action=f"submission_{action}",
            entity_type="campaign_submissions",
            entity_id=sub.id,
            after={"status": sub.status.value, "url": sub.post_url},
        )
    )
