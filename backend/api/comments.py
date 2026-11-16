"""Comments (A3): list, edit and send replies, ignore, paste TikTok comments, run now."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy import func, select

from api.deps import AppSettings, DbSession, Operator, Viewer, csrf_protect
from core.enums import CommentKind, CommentStatus, PlatformCode
from models.channels import Channel
from models.comments import Comment
from models.production import Variant
from models.publishing import Post
from services import agent_control, comments
from services.controls import effective_controls
from services.orchestrator import submit
from services.queue import get_redis

router = APIRouter(prefix="/comments", tags=["comments"], dependencies=[Depends(csrf_protect)])


class CommentOut(BaseModel):
    id: int
    channel_id: int
    channel: str
    platform: PlatformCode
    post_title: str | None
    post_url: str | None
    author: str | None
    text: str
    like_count: int | None
    written_at: datetime | None
    kind: CommentKind
    status: CommentStatus
    review_reason: str | None
    reply_text: str | None
    reply_source: str | None
    reply_is_mock: bool
    replied_at: datetime | None
    error: str | None
    is_test: bool
    can_send: bool


class StatsOut(BaseModel):
    by_status: dict[str, int]
    auto_reply: bool
    live: bool


class ReplyIn(BaseModel):
    reply_text: str | None = Field(default=None, max_length=comments.MAX_REPLY_CHARS)


class ManualIn(BaseModel):
    channel_id: int
    text: str = Field(min_length=1, max_length=5000)
    author: str | None = Field(default=None, max_length=200)


def _out(db: DbSession, c: Comment) -> CommentOut:
    channel = db.get(Channel, c.channel_id)
    title = url = None
    if c.post_id is not None:
        post = db.get(Post, c.post_id)
        if post is not None:
            url = post.url
            v = db.get(Variant, post.variant_id)
            title = v.title if v else None
    manual = c.external_id.startswith("manual-")
    return CommentOut(
        id=c.id,
        channel_id=c.channel_id,
        channel=channel.name if channel else "?",
        platform=c.platform,
        post_title=title,
        post_url=url,
        author=c.author,
        text=c.text,
        like_count=c.like_count,
        written_at=c.written_at,
        kind=c.kind,
        status=c.status,
        review_reason=c.review_reason,
        reply_text=c.reply_text,
        reply_source=c.reply_source,
        reply_is_mock=c.reply_is_mock,
        replied_at=c.replied_at,
        error=c.error,
        is_test=c.external_id.startswith("mock-"),
        can_send=c.platform != PlatformCode.TIKTOK and not manual,
    )


def _get(db: DbSession, comment_id: int) -> Comment:
    c = db.get(Comment, comment_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Kommentar nicht gefunden")
    return c


@router.get("", response_model=list[CommentOut])
def list_comments(
    _: Viewer,
    db: DbSession,
    state: CommentStatus | None = None,
    platform: PlatformCode | None = None,
    channel_id: int | None = None,
    limit: int = 100,
) -> list[CommentOut]:
    q = select(Comment)
    if state is not None:
        q = q.where(Comment.status == state)
    if platform is not None:
        q = q.where(Comment.platform == platform)
    if channel_id is not None:
        q = q.where(Comment.channel_id == channel_id)
    q = q.order_by(Comment.id.desc()).limit(max(1, min(limit, 300)))
    return [_out(db, c) for c in db.scalars(q)]


@router.get("/stats", response_model=StatsOut)
def stats(_: Viewer, db: DbSession, settings: AppSettings) -> StatsOut:
    rows = db.execute(select(Comment.status, func.count(Comment.id)).group_by(Comment.status))
    return StatsOut(
        by_status={str(CommentStatus(s).value): int(n) for s, n in rows},
        auto_reply=settings.comment_auto_reply,
        live=settings.publishing_allowed,
    )


@router.post("/{comment_id}/send", response_model=CommentOut)
def send(
    comment_id: int, body: ReplyIn, user: Operator, db: DbSession, settings: AppSettings
) -> CommentOut:
    c = _get(db, comment_id)
    if body.reply_text is not None:
        text = comments.clean_reply(body.reply_text) or body.reply_text.strip()
        c.reply_text = text
    try:
        comments.send(db, settings, c, user.id)
    except comments.CommentError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return _out(db, c)


@router.put("/{comment_id}/reply", response_model=CommentOut)
def edit_reply(comment_id: int, body: ReplyIn, _: Operator, db: DbSession) -> CommentOut:
    c = _get(db, comment_id)
    if c.status in (CommentStatus.SENT, CommentStatus.IGNORED):
        raise HTTPException(422, detail="Der Kommentar ist schon erledigt.")
    c.reply_text = (body.reply_text or "").strip() or None
    db.commit()
    return _out(db, c)


@router.post("/{comment_id}/done", response_model=CommentOut)
def done(comment_id: int, user: Operator, db: DbSession) -> CommentOut:
    c = _get(db, comment_id)
    try:
        comments.mark_done(db, c, user.id)
    except comments.CommentError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return _out(db, c)


@router.post("/{comment_id}/ignore", response_model=CommentOut)
def ignore(comment_id: int, user: Operator, db: DbSession) -> CommentOut:
    c = _get(db, comment_id)
    try:
        comments.ignore(db, c, user.id)
    except comments.CommentError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return _out(db, c)


@router.post("/{comment_id}/redraft", response_model=CommentOut)
def redraft(comment_id: int, _: Operator, db: DbSession, settings: AppSettings) -> CommentOut:
    c = _get(db, comment_id)
    try:
        comments.redraft(db, settings, c)
    except comments.CommentError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return _out(db, c)


@router.post("/manual", response_model=CommentOut, status_code=201)
def manual(body: ManualIn, _: Operator, db: DbSession, settings: AppSettings) -> CommentOut:
    channel = db.get(Channel, body.channel_id)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Kanal nicht gefunden")
    try:
        c = comments.add_manual(db, settings, channel, body.text, body.author)
    except comments.CommentError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return _out(db, c)


class RunOut(BaseModel):
    job_id: str | None


@router.post("/run", response_model=RunOut)
def run_now(
    _: Operator,
    db: DbSession,
    settings: AppSettings,
    redis: Annotated[Redis, Depends(get_redis)],
) -> RunOut:
    """Fetch and answer now instead of waiting for the next scheduled run."""
    if effective_controls(db, settings).emergency_stop:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Not-Aus ist aktiv")
    if not agent_control.is_enabled(db, "community"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Agent Community ist pausiert")
    job = submit("community", {"sweep": True}, priority=True, connection=redis)
    return RunOut(job_id=job.id)
