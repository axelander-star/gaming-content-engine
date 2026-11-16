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
from models.planning import CalendarEvent, ContentFocus, EditorialDay, PlanRule
from models.production import Variant
from models.projects import ContentProject
from models.publishing import PublishingJob
from services import audit, events, plan_rules, planning

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
    from_rule: bool = False


class OccasionOut(BaseModel):
    day: date
    name: str
    kind: str
    languages: list[str]
    lead_days: int
    id: int | None
    project_id: int | None
    note: str | None
    ends_on: date | None


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
    events: list[OccasionOut] = []


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


def _occasion(o: events.Occasion) -> OccasionOut:
    return OccasionOut(
        day=o.day,
        name=o.name,
        kind=o.kind,
        languages=list(o.languages),
        lead_days=o.lead_days,
        id=o.id,
        project_id=o.project_id,
        note=o.note,
        ends_on=o.ends_on,
    )


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
                CalendarEntryOut(
                    id=e.id,
                    project_id=e.project_id,
                    project=e.project,
                    note=e.note,
                    from_rule=e.rule_id is not None,
                )
            )
    occasions: dict[date, list[OccasionOut]] = {}
    for o in events.between(db, start, end, project_id=project_id):
        occasions.setdefault(o.day, []).append(_occasion(o))

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
                events=occasions.get(d, []),
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
        from_rule=e.rule_id is not None,
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
    plan_rules.skip(db, entry)
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


# --- weekly rules (A5) -----------------------------------------------------------------


class RuleIn(BaseModel):
    project_id: int
    weekday: int = Field(ge=0, le=6)
    every_weeks: int = Field(default=1, ge=1, le=4)
    note: str | None = Field(default=None, max_length=500)


class RuleOut(BaseModel):
    id: int
    project_id: int
    project: str
    weekday: int
    every_weeks: int
    label: str
    starts_on: date
    note: str | None
    skipped: int


def _rule_out(r: plan_rules.RuleText) -> RuleOut:
    return RuleOut(
        id=r.rule.id,
        project_id=r.rule.content_project_id,
        project=r.project,
        weekday=r.rule.weekday,
        every_weeks=r.rule.every_weeks,
        label=r.label,
        starts_on=r.rule.starts_on,
        note=r.rule.note,
        skipped=len(r.rule.skipped_days or []),
    )


@router.get("/rules", response_model=list[RuleOut])
def list_rules(_: Viewer, db: DbSession) -> list[RuleOut]:
    return [_rule_out(r) for r in plan_rules.listed(db)]


@router.post("/rules", response_model=RuleOut, status_code=201)
def add_rule(body: RuleIn, user: Operator, db: DbSession, settings: AppSettings) -> RuleOut:
    project = _active_project(db, body.project_id)
    try:
        rule, created = plan_rules.create(
            db, settings, project, body.weekday,
            every_weeks=body.every_weeks, note=(body.note or "").strip() or None, user_id=user.id,
        )  # fmt: skip
    except planning.PlanningError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    if not created:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Diese Regel gibt es schon")
    audit.record(db, "plan.rule_added", user_id=user.id, entity_type="plan_rules",
                 entity_id=rule.id, after={"project": project.name, "weekday": body.weekday,
                                           "every_weeks": body.every_weeks})  # fmt: skip
    db.commit()
    return _rule_out(plan_rules.RuleText(rule, project.name))


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, user: Operator, db: DbSession, settings: AppSettings) -> None:
    rule = db.get(PlanRule, rule_id)
    if rule is None or not rule.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Regel nicht gefunden")
    removed = plan_rules.stop(db, settings, rule)
    audit.record(db, "plan.rule_stopped", user_id=user.id, entity_type="plan_rules",
                 entity_id=rule.id, after={"removed_days": removed})  # fmt: skip
    db.commit()


# --- holidays, occasions and own events (A5) -------------------------------------------


class EventIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    day: date
    ends_on: date | None = None
    languages: list[str] = Field(default_factory=lambda: ["de", "en"], min_length=1)
    project_id: int | None = None
    note: str | None = Field(default=None, max_length=1000)


@router.get("/events", response_model=list[OccasionOut])
def list_events(
    _: Viewer,
    db: DbSession,
    start: date,
    end: date,
    language: str | None = Query(default=None, pattern="^(de|en)$"),
) -> list[OccasionOut]:
    if end < start or (end - start).days > 400:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Zeitraum 1 bis 400 Tage")
    return [_occasion(o) for o in events.between(db, start, end, language)]


@router.post("/events", response_model=OccasionOut, status_code=201)
def add_event(body: EventIn, user: Operator, db: DbSession) -> OccasionOut:
    langs = sorted({x for x in body.languages if x in ("de", "en")})
    if not langs:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Sprache de oder en")
    if body.ends_on is not None and body.ends_on < body.day:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Das Ende liegt vor dem Anfang"
        )
    if body.project_id is not None and db.get(ContentProject, body.project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Themenbereich nicht gefunden")
    ev = CalendarEvent(
        name=" ".join(body.name.split())[:200],
        day=body.day,
        ends_on=body.ends_on,
        languages=langs,
        content_project_id=body.project_id,
        note=(body.note or "").strip() or None,
        created_by_user_id=user.id,
    )
    db.add(ev)
    db.flush()
    audit.record(db, "plan.event_added", user_id=user.id, entity_type="calendar_events",
                 entity_id=ev.id, after={"name": ev.name, "day": ev.day.isoformat()})  # fmt: skip
    db.commit()
    return OccasionOut(
        day=ev.day, name=ev.name, kind="own", languages=langs, lead_days=7, id=ev.id,
        project_id=ev.content_project_id, note=ev.note, ends_on=ev.ends_on,
    )  # fmt: skip


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: int, user: Operator, db: DbSession) -> None:
    ev = db.get(CalendarEvent, event_id)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Termin nicht gefunden")
    audit.record(db, "plan.event_removed", user_id=user.id, entity_type="calendar_events",
                 entity_id=ev.id, before={"name": ev.name})  # fmt: skip
    db.delete(ev)
    db.commit()
