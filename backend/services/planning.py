"""Editorial plan: which topic area is on which day, and which topics get the focus.

The plan never says how many posts a channel gets; that stays with the
Publishing Strategy Agent (``services/strategy.py``).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import ContentProjectStatus
from models.planning import ContentFocus, EditorialDay
from models.projects import ContentProject

WEEKDAYS_DE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")

#: How far ahead or back the plan may be changed.
MAX_DAYS_AHEAD = 120
MAX_DAYS_BACK = 7


class PlanningError(ValueError):
    """A plan change that is not allowed (German message for the user)."""


def today(settings: Settings) -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def format_day(day: date) -> str:
    return f"{WEEKDAYS_DE[day.weekday()]}, {day.strftime('%d.%m.%Y')}"


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")


def find_project(session: Session, name: str) -> ContentProject:
    """Project by name or slug (case-insensitive, umlauts folded); not archived."""
    wanted = _norm(name.strip())
    projects = session.scalars(
        select(ContentProject)
        .where(ContentProject.status != ContentProjectStatus.ARCHIVED)
        .order_by(ContentProject.priority, ContentProject.id)
    ).all()
    for p in projects:
        if wanted in (_norm(p.name), _norm(p.slug)):
            return p
    prefix = [p for p in projects if _norm(p.name).startswith(wanted) and len(wanted) >= 3]
    if len(prefix) == 1:
        return prefix[0]
    names = ", ".join(p.name for p in projects) or "keine"
    raise PlanningError(f"Themenbereich „{name}“ nicht gefunden (vorhanden: {names})")


def check_day(settings: Settings, day: date) -> None:
    now = today(settings)
    if day < now - timedelta(days=MAX_DAYS_BACK):
        raise PlanningError(f"{format_day(day)} liegt zu weit zurück")
    if day > now + timedelta(days=MAX_DAYS_AHEAD):
        raise PlanningError(f"{format_day(day)} liegt mehr als {MAX_DAYS_AHEAD} Tage voraus")


# --- reads ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanEntry:
    id: int
    day: date
    project_id: int
    project: str
    note: str | None
    rule_id: int | None = None


@dataclass(frozen=True)
class FocusEntry:
    id: int
    project_id: int
    project: str
    topic: str
    starts_on: date
    ends_on: date
    note: str | None


def plan_between(session: Session, start: date, end: date) -> list[PlanEntry]:
    rows = session.execute(
        select(EditorialDay, ContentProject.name)
        .join(ContentProject, ContentProject.id == EditorialDay.content_project_id)
        .where(EditorialDay.day >= start, EditorialDay.day <= end)
        .order_by(EditorialDay.day, ContentProject.priority, ContentProject.id)
    ).all()
    return [
        PlanEntry(d.id, d.day, d.content_project_id, name, d.note, d.rule_id) for d, name in rows
    ]


def focus_between(session: Session, start: date, end: date) -> list[FocusEntry]:
    rows = session.execute(
        select(ContentFocus, ContentProject.name)
        .join(ContentProject, ContentProject.id == ContentFocus.content_project_id)
        .where(ContentFocus.starts_on <= end, ContentFocus.ends_on >= start)
        .order_by(ContentFocus.starts_on, ContentFocus.id)
    ).all()
    return [
        FocusEntry(f.id, f.content_project_id, name, f.topic, f.starts_on, f.ends_on, f.note)
        for f, name in rows
    ]


# --- changes -------------------------------------------------------------------------


def add_day(
    session: Session, settings: Settings, day: date, project: ContentProject,
    note: str | None, user_id: int | None,
) -> EditorialDay | None:  # fmt: skip
    """Plan ``project`` on ``day``; ``None`` if it was already planned."""
    check_day(settings, day)
    existing = session.scalar(
        select(EditorialDay).where(
            EditorialDay.day == day, EditorialDay.content_project_id == project.id
        )
    )
    if existing is not None:
        return None
    entry = EditorialDay(
        day=day,
        content_project_id=project.id,
        note=(note or None) and note[:500],
        created_by_user_id=user_id,
    )
    session.add(entry)
    session.flush()
    return entry


def remove_day(
    session: Session, settings: Settings, day: date, project: ContentProject
) -> EditorialDay | None:
    """Take ``project`` off ``day``; returns the removed row (detached) or ``None``."""
    check_day(settings, day)
    existing = session.scalar(
        select(EditorialDay).where(
            EditorialDay.day == day, EditorialDay.content_project_id == project.id
        )
    )
    if existing is None:
        return None
    from services import plan_rules

    plan_rules.skip(session, existing)
    session.delete(existing)
    session.flush()
    return existing


def add_focus(
    session: Session, settings: Settings, project: ContentProject, topic: str,
    starts_on: date, ends_on: date, note: str | None, user_id: int | None,
) -> ContentFocus:  # fmt: skip
    topic = " ".join(topic.split())
    if not topic:
        raise PlanningError("Kein Thema angegeben")
    if ends_on < starts_on:
        raise PlanningError("Das Ende liegt vor dem Anfang")
    if (ends_on - starts_on).days > 31:
        raise PlanningError("Ein Fokus gilt höchstens 31 Tage")
    check_day(settings, starts_on)
    check_day(settings, ends_on)
    focus = ContentFocus(
        content_project_id=project.id,
        topic=topic[:200],
        starts_on=starts_on,
        ends_on=ends_on,
        note=note or None,
        created_by_user_id=user_id,
    )
    session.add(focus)
    session.flush()
    return focus


# --- effect on the Publishing Strategy Agent (E6) -------------------------------------


def day_block(session: Session, day: date, project_id: int) -> str | None:
    """Why a channel of ``project_id`` gets no posts on ``day`` according to the plan.

    A day without any plan entry is open for every topic area. Once a day has
    hand-made entries, only the planned topic areas post that day (entries from a
    weekly rule add their area without closing the day for the others). The *amount* per channel
    is never set here; it stays with the Publishing Strategy Agent.
    """
    rows = list(
        session.execute(
            select(EditorialDay.content_project_id, ContentProject.name, EditorialDay.rule_id)
            .join(ContentProject, ContentProject.id == EditorialDay.content_project_id)
            .where(EditorialDay.day == day)
            .order_by(ContentProject.priority, ContentProject.id)
        ).all()
    )
    # Entries from weekly rules add an area to the day; only hand-made ones are exclusive.
    names = [(pid, name) for pid, name, rule_id in rows if rule_id is None]
    if not names or any(pid == project_id for pid, _, _ in rows):
        return None
    planned = ", ".join(name for _, name in names)
    return f"Redaktionsplan: am {format_day(day)} nur {planned}"


def focus_topics(session: Session, day: date, project_id: int) -> list[str]:
    """Focus topics of a topic area that apply on ``day``."""
    return [f.topic for f in focus_between(session, day, day) if f.project_id == project_id]


def move_day(
    session: Session, settings: Settings, entry: EditorialDay, new_day: date
) -> EditorialDay:
    """Move a plan entry to another day (refused if the area is already planned there)."""
    check_day(settings, new_day)
    if new_day == entry.day:
        return entry
    clash = session.scalar(
        select(EditorialDay.id).where(
            EditorialDay.day == new_day,
            EditorialDay.content_project_id == entry.content_project_id,
        )
    )
    if clash is not None:
        raise PlanningError(f"Am {format_day(new_day)} ist der Bereich schon eingeplant")
    from services import plan_rules

    plan_rules.skip(session, entry)  # a weekly rule must not fill the old day again
    entry.day = new_day
    session.flush()
    return entry
