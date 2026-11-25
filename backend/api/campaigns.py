"""Clipping campaigns (Content Rewards): campaigns, clips to approve, submissions.

The engine cuts and publishes campaign clips; the operator approves each clip and
submits the link on the campaign page by hand (there is no official API for
clippers), then ticks it off here.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import AppSettings, DbSession, Operator, Viewer, csrf_protect
from core.enums import CampaignStatus, SubmissionStatus, VideoStatus
from models.campaigns import Campaign, CampaignSubmission
from models.channels import Channel
from models.production import Clip, GameplayFile, QualityCheck, Scene, Variant
from models.projects import ContentProject
from models.publishing import Post, PublishingJob
from models.rights import Asset
from services import approval, campaign_assist, campaign_fit, campaigns

router = APIRouter(prefix="/campaigns", tags=["campaigns"], dependencies=[Depends(csrf_protect)])


def _http(exc: campaigns.CampaignError) -> HTTPException:
    return HTTPException(exc.status_code, detail=str(exc))


# --- campaigns ------------------------------------------------------------------------


class CampaignFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=1000)
    game_id: int | None = None
    cpm_usd: Decimal | None = Field(default=None, ge=0, le=10000)
    budget_usd: Decimal | None = Field(default=None, ge=0)
    min_views: int | None = Field(default=None, ge=0)
    max_payout_per_clip_usd: Decimal | None = Field(default=None, ge=0)
    platforms: list[str] | None = Field(default=None, max_length=10)
    languages: list[str] | None = Field(default=None, max_length=5)
    channel_ids: list[int] | None = Field(default=None, max_length=50)
    required_hashtags: list[str] | None = Field(default=None, max_length=30)
    disclosure: str | None = Field(default=None, max_length=300)
    required_text: str | None = Field(default=None, max_length=500)
    min_duration_s: int | None = Field(default=None, ge=1, le=600)
    max_duration_s: int | None = Field(default=None, ge=1, le=600)
    submission_window_min: int | None = Field(default=None, ge=5, le=1440)
    ends_on: date | None = None
    brief: str | None = Field(default=None, max_length=10000)
    material_links: list[str] | None = Field(default=None, max_length=20)


class CampaignIn(CampaignFields):
    content_project_id: int
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=1000)
    platforms: list[str] = Field(min_length=1, max_length=10)
    languages: list[str] = Field(min_length=1, max_length=5)
    channel_ids: list[int] = Field(min_length=1, max_length=50)
    #: The brief allows edited, monetized short clips of the material (with its music).
    rights_confirmed: bool = False


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: CampaignStatus


class ProposalOut(BaseModel):
    title: str
    hook: str
    scenes: list[str]
    on_screen_text: list[str]
    caption: str
    length_s: int
    why: str
    facts: list[str]


class CampaignOut(BaseModel):
    id: int
    content_project_id: int
    project: str
    source_id: int
    license_id: int
    game_id: int | None
    provider: str
    name: str
    url: str
    status: CampaignStatus
    cpm_usd: float | None
    budget_usd: float | None
    min_views: int | None
    max_payout_per_clip_usd: float | None
    platforms: list[str]
    languages: list[str]
    channel_ids: list[int]
    channels: list[str]
    required_hashtags: list[str]
    disclosure: str | None
    required_text: str | None
    min_duration_s: int | None
    max_duration_s: int | None
    submission_window_min: int
    ends_on: date | None
    brief: str | None
    material_links: list[str]
    materials: int
    clips_waiting: int
    submissions_open: int
    submissions_done: int
    next_step: str
    proposals: list[ProposalOut]
    proposals_at: datetime | None
    proposals_source: str | None
    created_at: datetime


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _campaigns_out(db: Session, items: list[Campaign]) -> list[CampaignOut]:
    if not items:
        return []
    projects = dict(db.execute(select(ContentProject.id, ContentProject.name)).all())
    channels = dict(db.execute(select(Channel.id, Channel.name)).all())
    materials = dict(
        db.execute(
            select(Asset.source_id, func.count(GameplayFile.id))
            .join(GameplayFile, GameplayFile.asset_id == Asset.id)
            .where(Asset.source_id.in_([c.source_id for c in items]))
            .group_by(Asset.source_id)
        ).all()
    )
    waiting: dict[int, int] = {}
    for _variant, campaign in _clip_rows(db, items, [VideoStatus.QUALITY_APPROVED]):
        waiting[campaign.id] = waiting.get(campaign.id, 0) + 1
    counts: dict[tuple[int, SubmissionStatus], int] = {
        (cid, st): n
        for cid, st, n in db.execute(
            select(
                CampaignSubmission.campaign_id,
                CampaignSubmission.status,
                func.count(CampaignSubmission.id),
            )
            .where(CampaignSubmission.campaign_id.in_([c.id for c in items]))
            .group_by(CampaignSubmission.campaign_id, CampaignSubmission.status)
        )
    }
    out = []
    for c in items:
        open_subs = counts.get((c.id, SubmissionStatus.OPEN), 0)
        material_count = int(materials.get(c.source_id, 0))
        proposals = []
        for raw in c.proposals or []:
            try:
                proposals.append(ProposalOut.model_validate(raw))
            except ValueError:
                continue
        out.append(_campaign_out(c, projects, channels, material_count, waiting, counts, proposals))
        out[-1].next_step = campaign_assist.next_step(
            c,
            materials=material_count,
            clips_waiting=waiting.get(c.id, 0),
            submissions_open=open_subs,
        )
    return out


def _campaign_out(
    c: Campaign,
    projects: dict[int, str],
    channels: dict[int, str],
    material_count: int,
    waiting: dict[int, int],
    counts: dict[tuple[int, SubmissionStatus], int],
    proposals: list[ProposalOut],
) -> CampaignOut:
    return CampaignOut(
        id=c.id,
        content_project_id=c.content_project_id,
        project=projects.get(c.content_project_id, "?"),
        source_id=c.source_id,
        license_id=c.license_id,
        game_id=c.game_id,
        provider=c.provider,
        name=c.name,
        url=c.url,
        status=c.status,
        cpm_usd=_float(c.cpm_usd),
        budget_usd=_float(c.budget_usd),
        min_views=c.min_views,
        max_payout_per_clip_usd=_float(c.max_payout_per_clip_usd),
        platforms=list(c.platforms or []),
        languages=list(c.languages or []),
        channel_ids=[int(i) for i in c.channel_ids or []],
        channels=[channels.get(int(i), f"#{i}") for i in c.channel_ids or []],
        required_hashtags=list(c.required_hashtags or []),
        disclosure=c.disclosure,
        required_text=c.required_text,
        min_duration_s=c.min_duration_s,
        max_duration_s=c.max_duration_s,
        submission_window_min=c.submission_window_min,
        ends_on=c.ends_on,
        brief=c.brief,
        material_links=list(c.material_links or []),
        materials=material_count,
        clips_waiting=waiting.get(c.id, 0),
        submissions_open=counts.get((c.id, SubmissionStatus.OPEN), 0),
        submissions_done=counts.get((c.id, SubmissionStatus.SUBMITTED), 0),
        next_step="",
        proposals=proposals,
        proposals_at=c.proposals_at,
        proposals_source=c.proposals_source,
        created_at=c.created_at,
    )


def _campaign(db: Session, campaign_id: int) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Kampagne nicht gefunden")
    return campaign


class MatchIn(BaseModel):
    name: str = Field(default="", max_length=200)
    brief: str | None = Field(default=None, max_length=20000)
    game: str | None = Field(default=None, max_length=200)
    platforms: list[str] = Field(default_factory=list, max_length=10)
    languages: list[str] = Field(default_factory=list, max_length=10)
    cpm_usd: Decimal | None = Field(default=None, ge=0, le=1000)
    min_views: int | None = Field(default=None, ge=0)
    max_payout_per_clip_usd: Decimal | None = Field(default=None, ge=0)


class FitChannel(BaseModel):
    id: int
    name: str
    platform: str
    language: str


class FitOut(BaseModel):
    project_id: int
    project: str
    score: int
    reasons: list[str]
    channels: list[FitChannel]
    median_views: int | None
    usd_per_clip: float | None


class ParseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=20, max_length=campaign_assist.MAX_PASTE)


class ParseOut(BaseModel):
    fields: dict[str, Any]
    found: list[str]
    missing: list[str]
    source: str
    game: str | None


@router.post("/parse", response_model=ParseOut)
def parse_campaign_page(
    body: ParseIn, user: Operator, db: DbSession, settings: AppSettings
) -> ParseOut:
    """Fill the campaign form from text copied off the campaign page. Saves nothing."""
    result = campaign_assist.parse_page(db, settings, body.text, user.id)
    db.commit()
    return ParseOut(
        fields=result.fields,
        found=result.found,
        missing=result.missing,
        source=result.source,
        game=result.game,
    )


@router.post("/{campaign_id}/proposals", response_model=CampaignOut)
def refresh_proposals(
    campaign_id: int, user: Operator, db: DbSession, settings: AppSettings
) -> CampaignOut:
    """Write new video proposals from brief, current trends and research facts."""
    campaign = _campaign(db, campaign_id)
    campaign_assist.generate_proposals(db, settings, campaign, user.id)
    db.commit()
    return _campaigns_out(db, [campaign])[0]


@router.post("/match", response_model=list[FitOut])
def match_campaign(body: MatchIn, _: Viewer, db: DbSession) -> list[FitOut]:
    """Which topic area fits a campaign the operator is looking at (A8)."""
    return [FitOut(**f.as_dict()) for f in campaign_fit.rank(db, body.model_dump())]


@router.get("/{campaign_id}/fit", response_model=list[FitOut])
def campaign_fit_for(campaign_id: int, _: Viewer, db: DbSession) -> list[FitOut]:
    return [
        FitOut(**f.as_dict()) for f in campaign_fit.for_campaign(db, _campaign(db, campaign_id))
    ]


@router.get("", response_model=list[CampaignOut])
def list_campaigns(
    _: Viewer,
    db: DbSession,
    project_id: Annotated[int | None, Query()] = None,
) -> list[CampaignOut]:
    query = select(Campaign).order_by(Campaign.id.desc())
    if project_id is not None:
        query = query.where(Campaign.content_project_id == project_id)
    return _campaigns_out(db, list(db.scalars(query)))


@router.post("", response_model=CampaignOut, status_code=201)
def create_campaign(
    body: CampaignIn, user: Operator, db: DbSession, settings: AppSettings
) -> CampaignOut:
    try:
        campaign = campaigns.create(db, body.model_dump(), user.id)
    except campaigns.CampaignError as exc:
        db.rollback()
        raise _http(exc) from exc
    db.commit()
    campaign_assist.generate_proposals(db, settings, campaign, user.id)
    db.commit()
    return _campaigns_out(db, [campaign])[0]


@router.patch("/{campaign_id}", response_model=CampaignOut)
def update_campaign(
    campaign_id: int, body: CampaignFields, user: Operator, db: DbSession
) -> CampaignOut:
    campaign = _campaign(db, campaign_id)
    try:
        campaigns.update(db, campaign, body.model_dump(exclude_unset=True), user.id)
    except campaigns.CampaignError as exc:
        db.rollback()
        raise _http(exc) from exc
    db.commit()
    return _campaigns_out(db, [campaign])[0]


@router.post("/{campaign_id}/status", response_model=CampaignOut)
def set_campaign_status(
    campaign_id: int, body: StatusIn, user: Operator, db: DbSession
) -> CampaignOut:
    campaign = _campaign(db, campaign_id)
    campaigns.set_status(db, campaign, body.status, user.id)
    db.commit()
    return _campaigns_out(db, [campaign])[0]


# --- clips ----------------------------------------------------------------------------

CLIP_STATUSES = [
    VideoStatus.QUALITY_APPROVED,
    VideoStatus.READY_TO_PUBLISH,
    VideoStatus.SCHEDULED,
]


def _clip_rows(
    db: Session, items: list[Campaign], statuses: list[VideoStatus]
) -> list[tuple[Variant, Campaign]]:
    by_source = {c.source_id: c for c in items}
    if not by_source:
        return []
    rows = db.execute(
        select(Variant, Asset.source_id)
        .join(Clip, Clip.id == Variant.clip_id)
        .join(Scene, Scene.id == Clip.scene_id)
        .join(GameplayFile, GameplayFile.id == Scene.gameplay_file_id)
        .join(Asset, Asset.id == GameplayFile.asset_id)
        .where(Asset.source_id.in_(list(by_source)), Variant.status.in_(statuses))
        .order_by(Variant.id.desc())
    )
    return [(variant, by_source[source_id]) for variant, source_id in rows]


class ClipOut(BaseModel):
    id: int
    campaign_id: int
    campaign: str
    status: VideoStatus
    channel_id: int
    channel: str
    platform: str
    language: str
    title: str
    description: str
    hashtags: list[str]
    caption: str
    duration_s: float | None
    quality_score: float | None
    checks: list[dict[str, Any]]
    problems: list[str]
    scheduled_for: datetime | None


def _clips_out(db: Session, rows: list[tuple[Variant, Campaign]]) -> list[ClipOut]:
    if not rows:
        return []
    ids = [v.id for v, _ in rows]
    checks: dict[int, QualityCheck] = {}
    for check in db.scalars(
        select(QualityCheck).where(QualityCheck.variant_id.in_(ids)).order_by(QualityCheck.id)
    ):
        checks[check.variant_id] = check
    jobs: dict[int, PublishingJob] = {}
    for planned in db.scalars(
        select(PublishingJob).where(PublishingJob.variant_id.in_(ids)).order_by(PublishingJob.id)
    ):
        jobs[planned.variant_id] = planned
    out = []
    for v, c in rows:
        channel = db.get(Channel, v.channel_id)
        assert channel is not None
        code = channel.platform.code
        qc = checks.get(v.id)
        job = jobs.get(v.id)
        problems = (
            approval.text_problems(v, code) + campaigns.text_problems(c, v)
            if v.status == VideoStatus.QUALITY_APPROVED
            else []
        )
        out.append(
            ClipOut(
                id=v.id,
                campaign_id=c.id,
                campaign=c.name,
                status=v.status,
                channel_id=channel.id,
                channel=channel.name,
                platform=code.value,
                language=v.language.value,
                title=v.title or "",
                description=v.description or "",
                hashtags=list(v.hashtags or []),
                caption=approval.caption(v),
                duration_s=campaigns.clip_duration(db, v),
                quality_score=v.quality_score,
                checks=list((qc.checks or {}).get("items", [])) if qc else [],
                problems=problems,
                scheduled_for=(
                    job.scheduled_for if job and v.status == VideoStatus.SCHEDULED else None
                ),
            )
        )
    return out


def _clip(db: Session, variant_id: int) -> tuple[Variant, Campaign]:
    variant = db.get(Variant, variant_id)
    campaign = campaigns.for_variant(db, variant) if variant else None
    if variant is None or campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Kampagnen-Clip nicht gefunden")
    return variant, campaign


@router.get("/clips/list", response_model=list[ClipOut])
def list_clips(
    _: Viewer,
    db: DbSession,
    campaign_id: Annotated[int | None, Query()] = None,
) -> list[ClipOut]:
    query = select(Campaign)
    if campaign_id is not None:
        query = query.where(Campaign.id == campaign_id)
    return _clips_out(db, _clip_rows(db, list(db.scalars(query)), CLIP_STATUSES))


class ClipPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    hashtags: list[str] | None = Field(default=None, max_length=60)


@router.patch("/clips/{variant_id}", response_model=ClipOut)
def update_clip(variant_id: int, body: ClipPatch, _: Operator, db: DbSession) -> ClipOut:
    variant, campaign = _clip(db, variant_id)
    try:
        campaigns.edit_texts(db, variant, **body.model_dump(exclude_unset=True))
    except campaigns.CampaignError as exc:
        db.rollback()
        raise _http(exc) from exc
    db.commit()
    return _clips_out(db, [(variant, campaign)])[0]


def _clip_action(db: Session, variant_id: int, action: Any, user_id: int) -> ClipOut:
    variant, campaign = _clip(db, variant_id)
    try:
        action(db, variant, user_id)
    except campaigns.CampaignError as exc:
        db.rollback()
        raise _http(exc) from exc
    db.commit()
    return _clips_out(db, [(variant, campaign)])[0]


@router.post("/clips/{variant_id}/approve", response_model=ClipOut)
def approve_clip(variant_id: int, user: Operator, db: DbSession) -> ClipOut:
    return _clip_action(db, variant_id, campaigns.approve, user.id)


@router.post("/clips/{variant_id}/withdraw", response_model=ClipOut)
def withdraw_clip(variant_id: int, user: Operator, db: DbSession) -> ClipOut:
    return _clip_action(db, variant_id, campaigns.withdraw, user.id)


@router.post("/clips/{variant_id}/discard", response_model=ClipOut)
def discard_clip(variant_id: int, user: Operator, db: DbSession) -> ClipOut:
    return _clip_action(db, variant_id, campaigns.discard, user.id)


# --- submissions ----------------------------------------------------------------------


class SubmissionOut(BaseModel):
    id: int
    campaign_id: int
    campaign: str
    campaign_url: str
    channel_id: int
    channel: str
    platform: str
    title: str
    post_url: str | None
    is_mock: bool
    posted_at: datetime | None
    deadline_at: datetime | None
    #: ``open``, ``overdue``, ``needs_link``, ``submitted`` or ``skipped``.
    state: str
    seconds_left: int | None
    late: bool
    submitted_at: datetime | None
    note: str | None


def _submissions_out(db: Session, subs: list[CampaignSubmission]) -> list[SubmissionOut]:
    now = datetime.now(UTC)
    out = []
    for sub in subs:
        campaign = db.get(Campaign, sub.campaign_id)
        channel = db.get(Channel, sub.channel_id)
        variant = db.get(Variant, sub.variant_id)
        post = db.get(Post, sub.post_id)
        assert campaign is not None and channel is not None
        state = campaigns.state_of(sub, now)
        out.append(
            SubmissionOut(
                id=sub.id,
                campaign_id=campaign.id,
                campaign=campaign.name,
                campaign_url=campaign.url,
                channel_id=channel.id,
                channel=channel.name,
                platform=channel.platform.code.value,
                title=(variant.title if variant else None) or "",
                post_url=sub.post_url,
                is_mock=bool(post.is_mock) if post else False,
                posted_at=sub.posted_at,
                deadline_at=sub.deadline_at,
                state=state.state,
                seconds_left=state.seconds_left,
                late=state.late,
                submitted_at=sub.submitted_at,
                note=sub.note,
            )
        )
    return out


def _submission(db: Session, submission_id: int) -> CampaignSubmission:
    sub = db.get(CampaignSubmission, submission_id)
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Einreichung nicht gefunden")
    return sub


@router.get("/submissions/list", response_model=list[SubmissionOut])
def list_submissions(
    _: Viewer,
    db: DbSession,
    done: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[SubmissionOut]:
    """Open submissions (most urgent first) or, with ``done``, the finished ones."""
    if done:
        query = (
            select(CampaignSubmission)
            .where(CampaignSubmission.status != SubmissionStatus.OPEN)
            .order_by(CampaignSubmission.updated_at.desc())
        )
    else:
        query = (
            select(CampaignSubmission)
            .where(CampaignSubmission.status == SubmissionStatus.OPEN)
            .order_by(
                CampaignSubmission.deadline_at.asc().nulls_last(), CampaignSubmission.id.asc()
            )
        )
    return _submissions_out(db, list(db.scalars(query.limit(limit))))


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=1000)


class SkipIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=500)


def _submission_action(db: Session, submission_id: int, action: Any) -> SubmissionOut:
    sub = _submission(db, submission_id)
    try:
        action(sub)
    except campaigns.CampaignError as exc:
        db.rollback()
        raise _http(exc) from exc
    db.commit()
    return _submissions_out(db, [sub])[0]


@router.post("/submissions/{submission_id}/link", response_model=SubmissionOut)
def set_submission_link(
    submission_id: int, body: LinkIn, user: Operator, db: DbSession
) -> SubmissionOut:
    return _submission_action(
        db, submission_id, lambda sub: campaigns.set_link(db, sub, body.url, user.id)
    )


@router.post("/submissions/{submission_id}/submitted", response_model=SubmissionOut)
def mark_submitted(submission_id: int, user: Operator, db: DbSession) -> SubmissionOut:
    return _submission_action(
        db, submission_id, lambda sub: campaigns.mark_submitted(db, sub, user.id)
    )


@router.post("/submissions/{submission_id}/skip", response_model=SubmissionOut)
def skip_submission(
    submission_id: int, body: SkipIn, user: Operator, db: DbSession
) -> SubmissionOut:
    return _submission_action(
        db, submission_id, lambda sub: campaigns.skip(db, sub, user.id, body.note)
    )


@router.post("/submissions/{submission_id}/reopen", response_model=SubmissionOut)
def reopen_submission(submission_id: int, user: Operator, db: DbSession) -> SubmissionOut:
    return _submission_action(db, submission_id, lambda sub: campaigns.reopen(db, sub, user.id))
