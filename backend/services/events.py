"""Holidays and occasions for the calendar and the idea lab (Ausbau A5).

Built in, computed for any year (no external service, no cost):

* German public holidays that apply nationwide, plus Heiligabend and Silvester;
* occasions people buy or watch for: Valentinstag, Muttertag, Halloween,
  Singles' Day, Black Friday, Cyber Monday, Nikolaus, 1. Advent;
* US dates for the English channels: Mother's Day, Father's Day, Independence
  Day, Thanksgiving.

Dates that move every year without a fixed rule (gamescom, Summer Game Fest, a
game launch) are added by hand as :class:`CalendarEvent`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from models.planning import CalendarEvent

DE = ("de",)
EN = ("en",)
BOTH = ("de", "en")


@dataclass(frozen=True)
class Occasion:
    day: date
    name: str
    kind: str  # holiday | occasion | own
    languages: tuple[str, ...]
    #: How many days ahead videos for it should be ready.
    lead_days: int = 7
    id: int | None = None  # own events only
    project_id: int | None = None
    note: str | None = None
    ends_on: date | None = None


def easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The ``n``-th ``weekday`` (0 = Monday) of a month."""
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def built_in(year: int) -> list[Occasion]:
    e = easter(year)
    thanksgiving = nth_weekday(year, 11, 3, 4)
    christmas = date(year, 12, 25)
    advent1 = christmas - timedelta(days=christmas.weekday() + 1 + 21)
    return [
        Occasion(date(year, 1, 1), "Neujahr", "holiday", DE, 5),
        Occasion(date(year, 2, 14), "Valentinstag", "occasion", BOTH, 14),
        Occasion(e - timedelta(days=2), "Karfreitag", "holiday", DE, 7),
        Occasion(e, "Ostern", "holiday", BOTH, 10),
        Occasion(e + timedelta(days=1), "Ostermontag", "holiday", DE, 7),
        Occasion(date(year, 5, 1), "Tag der Arbeit", "holiday", DE, 3),
        Occasion(nth_weekday(year, 5, 6, 2), "Muttertag", "occasion", DE, 14),
        Occasion(nth_weekday(year, 5, 6, 2), "Mother's Day", "occasion", EN, 14),
        Occasion(e + timedelta(days=39), "Christi Himmelfahrt / Vatertag", "holiday", DE, 10),
        Occasion(e + timedelta(days=49), "Pfingsten", "holiday", DE, 5),
        Occasion(e + timedelta(days=50), "Pfingstmontag", "holiday", DE, 3),
        Occasion(nth_weekday(year, 6, 6, 3), "Father's Day", "occasion", EN, 14),
        Occasion(date(year, 7, 4), "Independence Day", "holiday", EN, 7),
        Occasion(date(year, 10, 3), "Tag der Deutschen Einheit", "holiday", DE, 3),
        Occasion(date(year, 10, 31), "Halloween", "occasion", BOTH, 14),
        Occasion(date(year, 11, 11), "Singles' Day", "occasion", BOTH, 10),
        Occasion(thanksgiving, "Thanksgiving", "holiday", EN, 10),
        Occasion(thanksgiving + timedelta(days=1), "Black Friday", "occasion", BOTH, 21),
        Occasion(thanksgiving + timedelta(days=4), "Cyber Monday", "occasion", BOTH, 14),
        Occasion(advent1, "1. Advent", "occasion", DE, 10),
        Occasion(date(year, 12, 6), "Nikolaus", "occasion", DE, 10),
        Occasion(date(year, 12, 24), "Heiligabend", "holiday", DE, 21),
        Occasion(christmas, "Weihnachten", "holiday", BOTH, 21),
        Occasion(date(year, 12, 26), "2. Weihnachtstag", "holiday", DE, 7),
        Occasion(date(year, 12, 31), "Silvester", "holiday", BOTH, 7),
    ]


def own(session: Session, start: date, end: date) -> list[Occasion]:
    rows = session.scalars(
        select(CalendarEvent)
        .where(
            CalendarEvent.day <= end,
            or_(
                CalendarEvent.day >= start,
                CalendarEvent.ends_on >= start,
            ),
        )
        .order_by(CalendarEvent.day, CalendarEvent.id)
    )
    return [
        Occasion(
            day=r.day,
            name=r.name,
            kind="own",
            languages=tuple(str(x) for x in r.languages or BOTH),
            lead_days=7,
            id=r.id,
            project_id=r.content_project_id,
            note=r.note,
            ends_on=r.ends_on,
        )
        for r in rows
    ]


def between(
    session: Session | None,
    start: date,
    end: date,
    language: str | None = None,
    project_id: int | None = None,
) -> list[Occasion]:
    """Holidays, occasions and own events in ``[start, end]``, by day."""
    found = [
        o for year in range(start.year, end.year + 1) for o in built_in(year)
        if start <= o.day <= end
    ]  # fmt: skip
    if session is not None:
        found += [
            o for o in own(session, start, end)
            if project_id is None or o.project_id in (None, project_id)
        ]  # fmt: skip
    if language:
        found = [o for o in found if language in o.languages]
    return sorted(found, key=lambda o: (o.day, o.kind != "own", o.name))


def upcoming(
    session: Session | None,
    today: date,
    days: int = 30,
    language: str | None = None,
    project_id: int | None = None,
) -> list[Occasion]:
    """Occasions worth preparing for now: within ``days`` and inside their lead time."""
    return [
        o for o in between(session, today, today + timedelta(days=days), language, project_id)
        if (o.day - today).days <= max(o.lead_days, 3)
    ]  # fmt: skip


def describe(o: Occasion, today: date) -> str:
    delta = (o.day - today).days
    when = "heute" if delta == 0 else "morgen" if delta == 1 else f"in {delta} Tagen"
    return f"{o.name} ({o.day:%d.%m.}, {when})"
