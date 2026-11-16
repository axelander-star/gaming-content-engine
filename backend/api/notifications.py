"""Notifications for the bell and push settings (Ausbau A4)."""

from __future__ import annotations

from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.deps import Admin, AppSettings, DbSession, Viewer, csrf_protect
from core.enums import NotificationLevel
from models.access import Notification
from services import notify

router = APIRouter(
    prefix="/notifications", tags=["notifications"], dependencies=[Depends(csrf_protect)]
)


class NotificationOut(BaseModel):
    id: int
    created_at: datetime
    level: NotificationLevel
    kind: str | None
    title: str
    body: str | None
    link: str | None
    read: bool
    push_state: str | None


class NotificationListOut(BaseModel):
    unread: int
    items: list[NotificationOut]


class ReadIn(BaseModel):
    #: None marks everything as read.
    ids: list[int] | None = Field(default=None, max_length=500)


class ReadOut(BaseModel):
    marked: int
    unread: int


class PushOut(BaseModel):
    mode: str
    configured: bool
    min_level: str
    quiet_start: int
    quiet_end: int
    timezone: str


class TestOut(BaseModel):
    result: str


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        created_at=n.created_at,
        level=n.level,
        kind=n.kind,
        title=n.title,
        body=n.body,
        link=n.link,
        read=n.read_at is not None,
        push_state=n.push_state,
    )


@router.get("", response_model=NotificationListOut)
def list_notifications(
    _: Viewer,
    db: DbSession,
    limit: int = Query(default=30, ge=1, le=200),
    unread_only: bool = False,
) -> NotificationListOut:
    return NotificationListOut(
        unread=notify.unread_count(db),
        items=[_out(n) for n in notify.recent(db, limit, unread_only)],
    )


@router.post("/read", response_model=ReadOut)
def mark_read(body: ReadIn, _: Viewer, db: DbSession) -> ReadOut:
    marked = notify.mark_read(db, body.ids)
    return ReadOut(marked=marked, unread=notify.unread_count(db))


@router.get("/push", response_model=PushOut)
def push_settings(_: Viewer, settings: AppSettings) -> PushOut:
    return PushOut(
        mode=settings.push_mode,
        configured=notify.configured(settings),
        min_level=settings.push_min_level,
        quiet_start=settings.push_quiet_start,
        quiet_end=settings.push_quiet_end,
        timezone=settings.timezone,
    )


@router.post("/push/test", response_model=TestOut)
def push_test(_: Admin, settings: AppSettings) -> TestOut:
    """Send a test push (in mock mode nothing leaves the server)."""
    try:
        return TestOut(result=notify.test_push(settings))
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Push nicht angekommen ({type(exc).__name__}). Adresse und Thema prüfen.",
        ) from exc
