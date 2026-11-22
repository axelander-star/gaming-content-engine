"""Trend alarm (Ausbau A11): alarms with facts, drafts and the one-tap approval."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import Admin, AppSettings, DbSession, Operator, Viewer, csrf_protect
from models.channels import Channel
from models.library import OwnProduction
from models.projects import ContentProject
from models.trend_alarms import TrendAlarm
from services import agent_control, approval, audit, competitors, trend_alarm
from services.controls import effective_controls
from services.orchestrator import submit
from services.queue import get_redis

router = APIRouter(
    prefix="/trend-alarms", tags=["trend-alarms"], dependencies=[Depends(csrf_protect)]
)


class AutopilotChannel(BaseModel):
    id: int
    name: str
    platform: str
    language: str
    project: str
    is_paused: bool
    trend_autopilot: bool


class InfoOut(BaseModel):
    mode: Literal["mock", "live"]
    threshold: int
    max_per_day: int
    drafts: int
    min_views: int
    regions: list[str]
    autopilot_enabled: bool
    autopilot_min_score: int
    publishing_mode: str
    push_mode: str
    channels: list[AutopilotChannel]


class PostOut(BaseModel):
    variant_id: int
    channel: str
    platform: str
    status: str


class DraftOut(BaseModel):
    angle: str | None
    production_id: int
    title: str | None
    status: str | None
    item_id: int | None
    duration_s: float | None
    error: str | None
    posts: list[PostOut]


class AlarmOut(BaseModel):
    id: int
    created_at: datetime
    content_project_id: int
    project: str
    source: str
    title: str
    url: str | None
    creator: str | None
    published_at: datetime | None
    metrics: dict[str, Any]
    score: int
    facts: list[str]
    status: str
    autopilot: bool
    approved_production_id: int | None
    decided_at: datetime | None
    error: str | None
    is_mock: bool
    drafts: list[DraftOut]


def _channel(c: Channel) -> AutopilotChannel:
    return AutopilotChannel(
        id=c.id,
        name=c.name,
        platform=c.platform.code.value,
        language=c.language.value,
        project=c.content_project.name,
        is_paused=c.is_paused,
        trend_autopilot=c.trend_autopilot,
    )


@router.get("/info", response_model=InfoOut)
def info(_: Viewer, db: DbSession, settings: AppSettings) -> InfoOut:
    channels = db.scalars(select(Channel).order_by(Channel.content_project_id, Channel.id)).all()
    return InfoOut(
        mode="live" if competitors.live(settings) else "mock",
        threshold=settings.trend_alarm_threshold,
        max_per_day=settings.trend_alarm_max_per_day,
        drafts=settings.trend_alarm_drafts,
        min_views=settings.trend_alarm_min_views,
        regions=[r.strip().upper() for r in settings.trend_alarm_regions.split(",") if r.strip()],
        autopilot_enabled=settings.trend_autopilot_enabled,
        autopilot_min_score=settings.trend_autopilot_min_score,
        publishing_mode=settings.publishing_mode,
        push_mode=settings.push_mode,
        channels=[_channel(c) for c in channels if c.platform.code in approval.RULES],
    )


def _alarm_out(db: Session, alarm: TrendAlarm) -> AlarmOut:
    project = db.get(ContentProject, alarm.content_project_id)
    posts: dict[int, list[PostOut]] = {}
    for v in trend_alarm.alarm_variants(db, alarm.id):
        pid = int((v.concept or {}).get("production_id", 0))
        channel = db.get(Channel, v.channel_id)
        posts.setdefault(pid, []).append(
            PostOut(
                variant_id=v.id,
                channel=channel.name if channel else "?",
                platform=channel.platform.code.value if channel else "?",
                status=v.status.value,
            )
        )
    drafts = []
    for d in alarm.drafts or []:
        pid = int(d.get("production_id") or 0)
        prod = db.get(OwnProduction, pid) if pid else None
        drafts.append(
            DraftOut(
                angle=d.get("angle"),
                production_id=pid,
                title=prod.title if prod else None,
                status=prod.status.value if prod else None,
                item_id=prod.output_item_id if prod else None,
                duration_s=prod.duration_s if prod else None,
                error=prod.error_message if prod else None,
                posts=posts.get(pid, []),
            )
        )
    return AlarmOut(
        id=alarm.id,
        created_at=alarm.created_at,
        content_project_id=alarm.content_project_id,
        project=project.name if project else "?",
        source=alarm.source,
        title=alarm.title,
        url=alarm.url,
        creator=alarm.creator,
        published_at=alarm.published_at,
        metrics=alarm.metrics or {},
        score=alarm.score,
        facts=[str(f) for f in alarm.facts or []],
        status=alarm.status,
        autopilot=alarm.autopilot,
        approved_production_id=alarm.approved_production_id,
        decided_at=alarm.decided_at,
        error=alarm.error,
        is_mock=alarm.is_mock,
        drafts=drafts,
    )


@router.get("", response_model=list[AlarmOut])
def list_alarms(
    _: Viewer,
    db: DbSession,
    view: Literal["open", "all"] = "open",
    limit: int = Query(default=30, ge=1, le=100),
) -> list[AlarmOut]:
    q = select(TrendAlarm)
    if view == "open":
        q = q.where(TrendAlarm.status.in_(trend_alarm.OPEN))
    rows = db.scalars(q.order_by(TrendAlarm.id.desc()).limit(limit)).all()
    return [_alarm_out(db, a) for a in rows]


def _alarm(db: Session, alarm_id: int, *, lock: bool = False) -> TrendAlarm:
    q = select(TrendAlarm).where(TrendAlarm.id == alarm_id)
    alarm = db.scalar(q.with_for_update() if lock else q)
    if alarm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Alarm nicht gefunden")
    return alarm


@router.get("/{alarm_id}", response_model=AlarmOut)
def get_alarm(alarm_id: int, _: Viewer, db: DbSession) -> AlarmOut:
    return _alarm_out(db, _alarm(db, alarm_id))


class ScanIn(BaseModel):
    project_id: int | None = None


@router.post("/scan")
def scan_now(
    body: ScanIn,
    admin: Admin,
    db: DbSession,
    settings: AppSettings,
    redis: Annotated[Redis, Depends(get_redis)],
) -> dict[str, str]:
    if effective_controls(db, settings).emergency_stop:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Not-Aus ist aktiv")
    if not agent_control.is_enabled(db, "trend_alarm"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Agent pausiert: trend_alarm")
    payload: dict[str, Any] = {"manual": True}
    if body.project_id is not None:
        payload["project_id"] = body.project_id
    job = submit("trend_alarm", payload, priority=True, connection=redis)
    audit.record(db, "trend_alarm.scan_manual", user_id=admin.id, entity_type="agents",
                 after={"job": job.id, "project_id": body.project_id})  # fmt: skip
    db.commit()
    return {"job": job.id}


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    production_id: int


def _error(exc: trend_alarm.TrendAlarmError | approval.ApprovalError) -> HTTPException:
    return HTTPException(exc.status_code, detail=str(exc))


@router.post("/{alarm_id}/approve", response_model=AlarmOut)
def approve(alarm_id: int, body: ApproveIn, user: Operator, db: DbSession) -> AlarmOut:
    """The one tap from the phone: this draft goes out on every channel of the area."""
    alarm = _alarm(db, alarm_id, lock=True)
    try:
        approved = trend_alarm.approve_draft(db, alarm, body.production_id, user.id)
    except (trend_alarm.TrendAlarmError, approval.ApprovalError) as exc:
        db.rollback()
        raise _error(exc) from exc
    audit.record(db, "trend_alarm.approved", user_id=user.id, entity_type="trend_alarms",
                 entity_id=alarm.id, after={"production_id": body.production_id,
                                            "variants": [v.id for v in approved]})  # fmt: skip
    db.commit()
    return _alarm_out(db, alarm)


@router.post("/{alarm_id}/dismiss", response_model=AlarmOut)
def dismiss(alarm_id: int, user: Operator, db: DbSession) -> AlarmOut:
    alarm = _alarm(db, alarm_id, lock=True)
    try:
        trend_alarm.dismiss(db, alarm, user.id)
    except (trend_alarm.TrendAlarmError, approval.ApprovalError) as exc:
        db.rollback()
        raise _error(exc) from exc
    audit.record(db, "trend_alarm.dismissed", user_id=user.id, entity_type="trend_alarms",
                 entity_id=alarm.id)  # fmt: skip
    db.commit()
    return _alarm_out(db, alarm)


class AutopilotIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.patch("/autopilot/{channel_id}", response_model=AutopilotChannel)
def set_autopilot(
    channel_id: int, body: AutopilotIn, admin: Admin, db: DbSession
) -> AutopilotChannel:
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Kanal nicht gefunden")
    before = channel.trend_autopilot
    channel.trend_autopilot = body.enabled
    audit.record(db, "trend_alarm.autopilot", user_id=admin.id, entity_type="channels",
                 entity_id=channel.id, before={"trend_autopilot": before},
                 after={"trend_autopilot": body.enabled})  # fmt: skip
    db.commit()
    db.refresh(channel)
    return _channel(channel)
