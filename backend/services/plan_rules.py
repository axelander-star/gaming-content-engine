"""Recurring plan entries: "jeden Donnerstag Uhren" (Ausbau A5).

A rule puts its topic area on its weekday for the next ``HORIZON_DAYS``; the
scheduler tops this up every 15 minutes, so the plan fills itself. A day the
operator removes by hand is remembered and not filled again.

Rule entries *add* the area to the day: other areas may still post then. Only
hand-made entries make a day exclusive (see :func:`services.planning.day_block`).
How many videos the area gets stays with the Publishing Strategy Agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import ContentProjectStatus
from models.planning import EditorialDay, PlanRule
from models.projects import ContentProject
from services import planning
from services.planning import WEEKDAYS_DE, PlanningError

HORIZON_DAYS = 28


@dataclass(frozen=True)
class RuleText:
    rule: PlanRule
    project: str

    @property
    def label(self) -> str:
        day = WEEKDAYS_DE[self.rule.weekday]
        every = (
            f"jeden {day}"
            if self.rule.every_weeks == 1
            else f"jeden {self.rule.every_weeks}. {day}"
        )
        return f"{every}: {self.project}"


def first_day(rule: PlanRule, start: date) -> date:
    return start + timedelta(days=(rule.weekday - start.weekday()) % 7)


def days_of(rule: PlanRule, start: date, end: date) -> list[date]:
    """The rule's days in ``[start, end]``."""
    anchor = first_day(rule, rule.starts_on)
    d = max(anchor, first_day(rule, start))
    # keep the rhythm of every n-th week counted from the rule's first day
    offset = ((d - anchor).days // 7) % rule.every_weeks
    if offset:
        d += timedelta(days=7 * (rule.every_weeks - offset))
    out = []
    last = min(end, rule.ends_on) if rule.ends_on else end
    skipped = {str(x) for x in rule.skipped_days or []}
    while d <= last:
        if d.isoformat() not in skipped:
            out.append(d)
        d += timedelta(days=7 * rule.every_weeks)
    return out


def create(
    session: Session,
    settings: Settings,
    project: ContentProject,
    weekday: int,
    *,
    every_weeks: int = 1,
    note: str | None = None,
    user_id: int | None = None,
) -> tuple[PlanRule, bool]:
    """Add a rule (or return the existing one) and fill the plan; ``(rule, created)``."""
    if not 0 <= weekday <= 6:
        raise PlanningError("Unbekannter Wochentag")
    if not 1 <= every_weeks <= 4:
        raise PlanningError("Rhythmus: jede bis jede 4. Woche")
    if project.status == ContentProjectStatus.ARCHIVED:
        raise PlanningError(f"{project.name} ist archiviert")
    existing = session.scalar(
        select(PlanRule).where(
            PlanRule.content_project_id == project.id,
            PlanRule.weekday == weekday,
            PlanRule.active.is_(True),
        )
    )
    if existing is not None:
        return existing, False
    rule = PlanRule(
        content_project_id=project.id,
        weekday=weekday,
        every_weeks=every_weeks,
        starts_on=planning.today(settings),
        note=(note or None) and note[:500],
        created_by_user_id=user_id,
    )
    session.add(rule)
    session.flush()
    apply(session, settings, rules=[rule])
    return rule, True


def stop(session: Session, settings: Settings, rule: PlanRule) -> int:
    """Switch a rule off and take its future, untouched entries out of the plan."""
    rule.active = False
    rule.ends_on = planning.today(settings)
    future = session.scalars(
        select(EditorialDay).where(
            EditorialDay.rule_id == rule.id, EditorialDay.day > planning.today(settings)
        )
    ).all()
    for entry in future:
        session.delete(entry)
    session.flush()
    return len(future)


def skip(session: Session, entry: EditorialDay) -> None:
    """Remember that the operator removed a rule entry, so it is not filled again."""
    if entry.rule_id is None:
        return
    rule = session.get(PlanRule, entry.rule_id)
    if rule is None:
        return
    days = [str(x) for x in rule.skipped_days or []]
    if entry.day.isoformat() not in days:
        rule.skipped_days = [*days, entry.day.isoformat()][-200:]


def apply(
    session: Session,
    settings: Settings,
    rules: list[PlanRule] | None = None,
    today: date | None = None,
) -> int:
    """Put every active rule's days of the next ``HORIZON_DAYS`` into the plan."""
    today = today or planning.today(settings)
    end = today + timedelta(days=HORIZON_DAYS)
    if rules is None:
        rules = list(session.scalars(select(PlanRule).where(PlanRule.active.is_(True))))
    added = 0
    for rule in rules:
        project = session.get(ContentProject, rule.content_project_id)
        if project is None or project.status == ContentProjectStatus.ARCHIVED:
            continue
        planned = set(
            session.scalars(
                select(EditorialDay.day).where(
                    EditorialDay.content_project_id == project.id,
                    EditorialDay.day >= today,
                    EditorialDay.day <= end,
                )
            )
        )
        for d in days_of(rule, today, end):
            if d in planned:
                continue
            session.add(
                EditorialDay(
                    day=d,
                    content_project_id=project.id,
                    note=rule.note or f"jeden {WEEKDAYS_DE[rule.weekday]}",
                    rule_id=rule.id,
                    created_by_user_id=rule.created_by_user_id,
                )
            )
            added += 1
    session.flush()
    return added


def listed(session: Session) -> list[RuleText]:
    rows = session.execute(
        select(PlanRule, ContentProject.name)
        .join(ContentProject, ContentProject.id == PlanRule.content_project_id)
        .where(PlanRule.active.is_(True))
        .order_by(PlanRule.weekday, ContentProject.priority, PlanRule.id)
    )
    return [RuleText(rule, name) for rule, name in rows]
