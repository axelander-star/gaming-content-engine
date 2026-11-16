"""Approval center (extension phase E8).

Library videos become posts per channel; a person checks texts, platforms and
options and approves each post. Approved posts are scheduled by the Publishing
Strategy Agent (amount and time stay dynamic) and published in mock mode unless
live publishing is explicitly switched on.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import AppSettings, DbSession, Operator, Viewer, csrf_protect
from core.enums import PublishingJobStatus, VideoStatus
from models.channels import Channel
from models.library import LibraryItem
from models.production import QualityCheck, Variant
from models.projects import ContentProject
from models.publishing import Post, PublishingJob
from services import ai, approval

router = APIRouter(prefix="/approval", tags=["approval"], dependencies=[Depends(csrf_protect)])

TWITCH_NOTE = (
    "Twitch bietet keine offizielle Schnittstelle zum Hochladen von Videos. Die Twitch-API "
    "kennt nur das Abrufen und Löschen von Videos und das Erstellen von Clips aus Streams. "
    "Twitch bleibt deshalb ein Kanal für Livestreams und Hinweise; Beiträge lassen sich dort "
    "nicht automatisch veröffentlichen."
)


def _http(exc: approval.ApprovalError) -> HTTPException:
    return HTTPException(exc.status_code, detail=str(exc))


class PlatformInfo(BaseModel):
    code: str
    title_max: int
    caption_max: int
    hashtags_max: int
    max_duration_s: float
    vertical: bool
    defaults: dict[str, Any]


class ApprovalInfo(BaseModel):
    publishing_mode: str
    platforms: list[PlatformInfo]
    youtube_privacy: list[str]
    youtube_formats: list[str]
    tiktok_modes: list[str]
    twitch_note: str


@router.get("/info", response_model=ApprovalInfo)
def approval_info(_: Viewer, settings: AppSettings) -> ApprovalInfo:
    return ApprovalInfo(
        publishing_mode=settings.publishing_mode,
        platforms=[
            PlatformInfo(
                code=code.value,
                title_max=r.title_max,
                caption_max=r.caption_max,
                hashtags_max=r.hashtags_max,
                max_duration_s=r.max_duration_s,
                vertical=r.vertical,
                defaults=approval.DEFAULT_OPTIONS.get(code, {}),
            )
            for code, r in approval.RULES.items()
        ],
        youtube_privacy=list(approval.YOUTUBE_PRIVACY),
        youtube_formats=list(approval.YOUTUBE_FORMATS),
        tiktok_modes=list(approval.TIKTOK_MODES),
        twitch_note=TWITCH_NOTE,
    )


class PostOut(BaseModel):
    id: int
    status: VideoStatus
    project_id: int
    project: str
    item_id: int
    item_title: str
    channel_id: int
    channel: str
    platform: str
    language: str
    title: str
    description: str
    hashtags: list[str]
    options: dict[str, Any]
    caption: str
    quality_score: float | None
    checks: list[dict[str, Any]]
    problems: list[str]
    scheduled_for: datetime | None
    published_url: str | None
    published_mock: bool | None
    updated_at: datetime | None


def _posts_out(db: Session, variants: list[Variant]) -> list[PostOut]:
    if not variants:
        return []
    ids = [v.id for v in variants]
    channels = {
        c.id: c
        for c in db.scalars(select(Channel).where(Channel.id.in_({v.channel_id for v in variants})))
    }
    items = {
        i.id: i
        for i in db.scalars(
            select(LibraryItem).where(LibraryItem.id.in_({v.library_item_id for v in variants}))
        )
    }
    projects = {
        pid: name for pid, name in db.execute(select(ContentProject.id, ContentProject.name))
    }
    checks: dict[int, QualityCheck] = {}
    for check in db.scalars(
        select(QualityCheck).where(QualityCheck.variant_id.in_(ids)).order_by(QualityCheck.id)
    ):
        checks[check.variant_id] = check  # latest wins
    jobs: dict[int, PublishingJob] = {}
    for planned in db.scalars(
        select(PublishingJob)
        .where(
            PublishingJob.variant_id.in_(ids),
            PublishingJob.status.in_([PublishingJobStatus.SCHEDULED, PublishingJobStatus.RUNNING]),
        )
        .order_by(PublishingJob.id)
    ):
        jobs[planned.variant_id] = planned
    posts: dict[int, Post] = {}
    for done in db.scalars(select(Post).where(Post.variant_id.in_(ids)).order_by(Post.id)):
        posts[done.variant_id] = done
    out = []
    for v in variants:
        channel = channels[v.channel_id]
        code = channel.platform.code
        item = items.get(v.library_item_id or 0)
        qc = checks.get(v.id)
        job = jobs.get(v.id)
        post = posts.get(v.id)
        out.append(
            PostOut(
                id=v.id,
                status=v.status,
                project_id=v.content_project_id,
                project=projects.get(v.content_project_id, "?"),
                item_id=v.library_item_id or 0,
                item_title=item.title if item else "?",
                channel_id=channel.id,
                channel=channel.name,
                platform=code.value,
                language=v.language.value,
                title=v.title or "",
                description=v.description or "",
                hashtags=list(v.hashtags or []),
                options=dict(v.publish_options or {}),
                caption=approval.caption(v),
                quality_score=v.quality_score,
                checks=list((qc.checks or {}).get("items", [])) if qc else [],
                problems=approval.text_problems(v, code)
                if v.status == VideoStatus.QUALITY_APPROVED
                else [],
                scheduled_for=job.scheduled_for if job else None,
                published_url=post.url if post else None,
                published_mock=post.is_mock if post else None,
                updated_at=v.updated_at,
            )
        )
    return out


def _variant(db: Session, variant_id: int) -> Variant:
    variant = db.get(Variant, variant_id)
    if variant is None or variant.library_item_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Beitrag nicht gefunden")
    return variant


@router.get("", response_model=list[PostOut])
def list_posts(
    _: Viewer,
    db: DbSession,
    project_id: Annotated[int | None, Query()] = None,
    item_id: Annotated[int | None, Query()] = None,
    post_status: Annotated[VideoStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[PostOut]:
    query = select(Variant).where(Variant.library_item_id.is_not(None))
    if project_id is not None:
        query = query.where(Variant.content_project_id == project_id)
    if item_id is not None:
        query = query.where(Variant.library_item_id == item_id)
    if post_status is not None:
        query = query.where(Variant.status == post_status)
    else:
        query = query.where(Variant.status != VideoStatus.ARCHIVED)
    variants = list(db.scalars(query.order_by(Variant.id.desc()).limit(limit)))
    return _posts_out(db, variants)


class SuggestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: int
    channel_id: int


class TextsOut(BaseModel):
    title: str
    description: str
    hashtags: list[str]


@router.post("/suggest", response_model=TextsOut)
def suggest(body: SuggestIn, user: Operator, db: DbSession, settings: AppSettings) -> TextsOut:
    item = db.get(LibraryItem, body.item_id)
    channel = db.get(Channel, body.channel_id)
    if item is None or channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Video oder Kanal nicht gefunden")
    if channel.content_project_id != item.content_project_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Kanal gehört zu einem anderen Themenbereich als das Video",
        )
    if channel.platform.code not in approval.RULES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Plattform ohne Upload")
    try:
        texts = approval.suggest_texts(db, settings, item, channel, user.id)
    except ai.AIBlockedError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"KI nicht verfügbar: {exc.reason}"
        ) from exc
    except (ai.AIRefusedError, ai.AIFailedError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    db.commit()  # keeps the AI call record
    return TextsOut(**texts)


class TextsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=5000)
    hashtags: list[str] = Field(default_factory=list, max_length=60)
    options: dict[str, Any] = Field(default_factory=dict)


class PrepareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: int
    channel_ids: list[int] = Field(default_factory=list, max_length=20)
    #: A6: all channels of the topic area (every platform, German and English) that do
    #: not have this video yet; ``channel_ids`` is ignored then.
    everywhere: bool = False
    #: Texts per channel id; channels without texts get an AI suggestion.
    texts: dict[int, TextsIn] = Field(default_factory=dict)


@router.post("/prepare", response_model=list[PostOut], status_code=201)
def prepare(body: PrepareIn, user: Operator, db: DbSession, settings: AppSettings) -> list[PostOut]:
    texts = {cid: t.model_dump() for cid, t in body.texts.items()}
    try:
        channel_ids = (
            [c.id for c in approval.open_channels(db, body.item_id)][:20]
            if body.everywhere
            else body.channel_ids
        )
        if body.everywhere and not channel_ids:
            raise approval.ApprovalError("Alle Kanäle haben dieses Video schon", 409)
        variants = approval.prepare(
            db,
            settings,
            body.item_id,
            channel_ids,
            user.id,
            texts=texts,
            skip_unfit=body.everywhere,
        )
    except approval.ApprovalError as exc:
        db.rollback()
        raise _http(exc) from exc
    except ai.AIBlockedError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"KI nicht verfügbar: {exc.reason}"
        ) from exc
    except (ai.AIRefusedError, ai.AIFailedError) as exc:
        db.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    db.commit()
    return _posts_out(db, variants)


class PostPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    hashtags: list[str] | None = Field(default=None, max_length=60)
    options: dict[str, Any] | None = None


@router.patch("/{variant_id}", response_model=PostOut)
def update_post(variant_id: int, body: PostPatch, _: Operator, db: DbSession) -> PostOut:
    variant = _variant(db, variant_id)
    try:
        approval.update(db, variant, **body.model_dump(exclude_unset=True))
    except approval.ApprovalError as exc:
        db.rollback()
        raise _http(exc) from exc
    db.commit()
    return _posts_out(db, [variant])[0]


def _act(db: Session, variant_id: int, action: Any, user_id: int) -> PostOut:
    variant = _variant(db, variant_id)
    try:
        action(db, variant, user_id)
    except approval.ApprovalError as exc:
        db.rollback()
        raise _http(exc) from exc
    db.commit()
    return _posts_out(db, [variant])[0]


@router.post("/{variant_id}/approve", response_model=PostOut)
def approve_post(variant_id: int, user: Operator, db: DbSession) -> PostOut:
    return _act(db, variant_id, approval.approve, user.id)


@router.post("/{variant_id}/withdraw", response_model=PostOut)
def withdraw_post(variant_id: int, user: Operator, db: DbSession) -> PostOut:
    return _act(db, variant_id, approval.withdraw, user.id)


@router.post("/{variant_id}/discard", response_model=PostOut)
def discard_post(variant_id: int, user: Operator, db: DbSession) -> PostOut:
    return _act(db, variant_id, approval.discard, user.id)
