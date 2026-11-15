"""Editorial calendar (extension phase E6): week/month view, add, move, remove.

The calendar sets which topic area runs on which day and which topics get the
focus. How many posts a channel gets stays with the Publishing Strategy Agent;
the planned videos shown here are its decisions.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.deps import AppSettings, DbSession, Operator, Viewer, csrf_protect
from core.enums import ContentProjectStatus, PublishingJobStatus
from models.channels import Channel
from models.planning import ContentFocus, EditorialDay
from models.production import Variant
from models.projects import ContentProject
from models.publishing import PublishingJob
from services import audit, planning

router = APIRouter(prefix="/planning", tags=["planning"], dependencies=[Depends(csrf_protect)])

MAX_RANGE_DAYS = 62
SHOWN_JOBS = (
    PublishingJobStatus.SCHEDULED,
    PublishingJobStatus.RUNNING,
    PublishingJobStatus.SUCCEEDED,
    PublishingJobStatus.FAILED,
)


class CalendarEntryOut(BaseModel):
    id: int
    project_id: int
    project: str
    note: str | None


class CalendarVideoOut(BaseModel):
    job_id: int
    variant_id: int
    title: str
    channel: str
    project_id: int
    at: datetime
    status: PublishingJobStatus
    is_mock: bool


class CalendarDayOut(BaseModel):
    day: date
    weekday: str
    is_today: bool
    entries: list[CalendarEntryOut]
    videos: list[CalendarVideoOut]


class CalendarFocusOut(BaseModel):
    id: int
    project_id: int
    project: str
    topic: str
    starts_on: date
    ends_on: date
    note: str | None


class CalendarOut(BaseModel):
    start: date
    end: date
    today: date
    days: list[CalendarDayOut]
    focus: list[CalendarFocusOut]


@router.get("/calendar", response_model=CalendarOut)
def calendar(
    _: Viewer,
    db: DbSession,
    settings: AppSettings,
    start: date,
    end: date,
    project_id: int | None = Query(default=None),
) -> CalendarOut:
    if end < start or (end - start).days >= MAX_RANGE_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Zeitraum 1 bis {MAX_RANGE_DAYS} Tage",
        )
    tz = ZoneInfo(settings.timezone)
    today = planning.today(settings)
    entries: dict[date, list[CalendarEntryOut]] = {}
    for e in planning.plan_between(db, start, end):
        if project_id is None or e.project_id == project_id:
            entries.setdefault(e.day, []).append(
                CalendarEntryOut(id=e.id, project_id=e.project_id, project=e.project, note=e.note)
            )

    lo = datetime.combine(start, time(0), tz).astimezone(UTC)
    hi = datetime.combine(end + timedelta(days=1), time(0), tz).astimezone(UTC)
    query = (
        select(PublishingJob, Variant, Channel.name)
        .join(Variant, Variant.id == PublishingJob.variant_id)
        .join(Channel, Channel.id == PublishingJob.channel_id)
        .where(
            PublishingJob.scheduled_for >= lo,
            PublishingJob.scheduled_for < hi,
            PublishingJob.status.in_(SHOWN_JOBS),
        )
        .order_by(PublishingJob.scheduled_for)
        .limit(500)
    )
    if project_id is not None:
        query = query.where(PublishingJob.content_project_id == project_id)
    videos: dict[date, list[CalendarVideoOut]] = {}
    for job, variant, channel in db.execute(query):
        assert job.scheduled_for is not None
        local = job.scheduled_for.astimezone(tz)
        videos.setdefault(local.date(), []).append(
            CalendarVideoOut(
                job_id=job.id,
                variant_id=variant.id,
                title=variant.title or f"Variante {variant.variant_label}",
                channel=channel,
                project_id=job.content_project_id,
                at=job.scheduled_for,
                status=job.status,
                is_mock=job.mode.value != "live",
            )
        )

    days = []
    d = start
    while d <= end:
        days.append(
            CalendarDayOut(
                day=d,
                weekday=planning.WEEKDAYS_DE[d.weekday()],
                is_today=d == today,
                entries=entries.get(d, []),
                videos=videos.get(d, []),
            )
        )
        d += timedelta(days=1)
    focus = [
        CalendarFocusOut(
            id=f.id,
            project_id=f.project_id,
            project=f.project,
            topic=f.topic,
            starts_on=f.starts_on,
            ends_on=f.ends_on,
            note=f.note,
        )
        for f in planning.focus_between(db, start, end)
        if project_id is None or f.project_id == project_id
    ]
    return CalendarOut(start=start, end=end, today=today, days=days, focus=focus)


# --- plan entries --------------------------------------------------------------------


class DayIn(BaseModel):
    day: date
    project_id: int
    note: str | None = Field(default=None, max_length=500)


class DayPatch(BaseModel):
    day: date | None = None
    note: str | None = Field(default=None, max_length=500)


def _active_project(db: DbSession, project_id: int) -> ContentProject:
    project = db.get(ContentProject, project_id)
    if project is None or project.status == ContentProjectStatus.ARCHIVED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Themenbereich nicht gefunden")
    if project.status != ContentProjectStatus.ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"{project.name} ist pausiert")
    return project


def _entry_out(db: DbSession, e: EditorialDay) -> CalendarEntryOut:
    project = db.get(ContentProject, e.content_project_id)
    return CalendarEntryOut(
        id=e.id,
        project_id=e.content_project_id,
        project=project.name if project else "?",
        note=e.note,
    )


@router.post("/days", response_model=CalendarEntryOut, status_code=201)
def add_day(body: DayIn, user: Operator, db: DbSession, settings: AppSettings) -> CalendarEntryOut:
    project = _active_project(db, body.project_id)
    note = (body.note or "").strip() or None
    try:
        entry = planning.add_day(db, settings, body.day, project, note, user.id)
    except planning.PlanningError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    if entry is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="An dem Tag schon eingeplant")
    audit.record(db, "plan.day_added", user_id=user.id, entity_type="editorial_days",
                 entity_id=entry.id, after={"day": body.day.isoformat(),
                                            "project": project.name})  # fmt: skip
    db.commit()
    db.refresh(entry)
    return _entry_out(db, entry)


@router.patch("/days/{entry_id}", response_model=CalendarEntryOut)
def update_day(
    entry_id: int, body: DayPatch, user: Operator, db: DbSession, settings: AppSettings
) -> CalendarEntryOut:
    entry = db.get(EditorialDay, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Eintrag nicht gefunden")
    before = {"day": entry.day.isoformat(), "note": entry.note}
    fields = body.model_dump(exclude_unset=True)
    if "note" in fields:
        entry.note = (body.note or "").strip() or None
    if body.day is not None:
        try:
            planning.move_day(db, settings, entry, body.day)
        except planning.PlanningError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    audit.record(db, "plan.day_updated", user_id=user.id, entity_type="editorial_days",
                 entity_id=entry.id, before=before,
                 after={"day": entry.day.isoformat(), "note": entry.note})  # fmt: skip
    db.commit()
    db.refresh(entry)
    return _entry_out(db, entry)


@router.delete("/days/{entry_id}", status_code=204)
def delete_day(entry_id: int, user: Operator, db: DbSession) -> None:
    entry = db.get(EditorialDay, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Eintrag nicht gefunden")
    audit.record(db, "plan.day_removed", user_id=user.id, entity_type="editorial_days",
                 entity_id=entry.id, before={"day": entry.day.isoformat(),
                                             "project_id": entry.content_project_id})  # fmt: skip
    db.delete(entry)
    db.commit()


# --- focus ---------------------------------------------------------------------------


class FocusIn(BaseModel):
    project_id: int
    topic: str = Field(min_length=1, max_length=200)
    starts_on: date
    ends_on: date
    note: str | None = Field(default=None, max_length=1000)


@router.post("/focus", response_model=CalendarFocusOut, status_code=201)
def add_focus(
    body: FocusIn, user: Operator, db: DbSession, settings: AppSettings
) -> CalendarFocusOut:
    project = _active_project(db, body.project_id)
    try:
        focus = planning.add_focus(db, settings, project, body.topic, body.starts_on,
                                   body.ends_on, body.note, user.id)  # fmt: skip
    except planning.PlanningError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    audit.record(db, "plan.focus_added", user_id=user.id, entity_type="content_focus",
                 entity_id=focus.id,
                 after={"topic": focus.topic, "project": project.name})  # fmt: skip
    db.commit()
    db.refresh(focus)
    return CalendarFocusOut(
        id=focus.id,
        project_id=project.id,
        project=project.name,
        topic=focus.topic,
        starts_on=focus.starts_on,
        ends_on=focus.ends_on,
        note=focus.note,
    )


@router.delete("/focus/{focus_id}", status_code=204)
def delete_focus(focus_id: int, user: Operator, db: DbSession) -> None:
    focus = db.get(ContentFocus, focus_id)
    if focus is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Schwerpunkt nicht gefunden")
    audit.record(db, "plan.focus_removed", user_id=user.id, entity_type="content_focus",
                 entity_id=focus.id, before={"topic": focus.topic})  # fmt: skip
    db.delete(focus)
    db.commit()
