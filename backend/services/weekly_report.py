"""Weekly report by e-mail (Ausbau A10).

Every Monday morning (``REPORT_WEEKDAY``/``REPORT_HOUR``, local time) the engine
writes one short plain-text mail about the last full week (Monday to Sunday):

* posts, views and the change to the week before, per topic area and in total;
* the best posts of the week;
* channels that grow or drop clearly, and "consider pausing" suggestions;
* money: revenue entered, Content Rewards estimate, AI cost this month;
* what waits for the operator: comments to check, campaign links to submit,
  new sponsor inquiries, prepared accounts, warnings of the week;
* newsletter sign-ups, and the plan for the coming week.

It goes through :mod:`services.mailer`: with ``MAIL_MODE=mock`` (default) it only
lands in the dashboard outbox. One report per week; "Jetzt senden" in the
dashboard sends one at any time.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import (
    ChannelSetupStatus,
    CommentStatus,
    NotificationLevel,
    SubmissionStatus,
)
from models.access import Notification
from models.campaigns import CampaignSubmission
from models.channel_setup import ChannelSetupTask
from models.channels import Channel
from models.comments import Comment
from models.marketing import NewsletterSubscriber, OutgoingMail
from models.production import Variant
from models.projects import ContentProject
from models.publishing import Post
from models.revenue import RevenueEntry
from models.sponsors import SponsorInquiry
from services import accounts, budget, mailer, planning

KIND = "weekly_report"
CHANGE = 0.3  # ±30 % views week over week marks a channel as growing / dropping
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


@dataclass
class Report:
    start: date
    end: date
    subject: str
    lines: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip() + "\n"


def _n(value: float | int) -> str:
    return f"{value:,.0f}".replace(",", ".")


def _pct(now: int, before: int) -> str:
    if not before:
        return "neu" if now else "–"
    change = (now - before) / before * 100
    return f"{change:+.0f} %".replace("-", "−")


def _eur(value: Decimal | float) -> str:
    return f"{float(value):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def period(settings: Settings, now: datetime) -> tuple[datetime, datetime, date, date, str]:
    """The last full week (Monday 00:00 to Monday 00:00, local time) and its subject."""
    tz = ZoneInfo(settings.timezone)
    local = now.astimezone(tz)
    monday = (local - timedelta(days=local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end = monday.astimezone(UTC)
    start = end - timedelta(days=7)
    first, last = start.astimezone(tz).date(), (end - timedelta(seconds=1)).astimezone(tz).date()
    kw = first.isocalendar().week
    return start, end, first, last, f"Wochenbericht KW {kw}: {first:%d.%m.}–{last:%d.%m.%Y}"


def build(session: Session, settings: Settings, now: datetime | None = None) -> Report:
    now = now or datetime.now(UTC)
    local = now.astimezone(ZoneInfo(settings.timezone))
    start, end, first, last, subject = period(settings, now)
    before = start - timedelta(days=7)
    week = accounts._windows(session, start, end)
    prev = accounts._windows(session, before, start)
    channels = {c.id: c for c in session.scalars(select(Channel))}
    projects = {p.id: p.name for p in session.scalars(select(ContentProject))}

    report = Report(first, last, subject)
    out = report.lines
    posts = sum(w.posts for w in week.values())
    views = sum(w.views for w in week.values())
    views_prev = sum(w.views for w in prev.values())
    out.append(f"Wochenbericht {first:%d.%m.}–{last:%d.%m.%Y}")
    out.append("")
    if settings.publishing_mode != "live":
        out.append("Testbetrieb: Es wird nichts echt veröffentlicht, die Zahlen sind Testdaten.")
        out.append("")
    out.append(
        f"Kurz: {posts} Beiträge, {_n(views)} Aufrufe ({_pct(views, views_prev)} zur Vorwoche)."
    )
    report.data.update(posts=posts, views=views, views_prev=views_prev)

    # per topic area
    per: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0])
    for cid, w in week.items():
        if cid in channels:
            p = per[channels[cid].content_project_id]
            p[0], p[1] = p[0] + w.posts, p[1] + w.views
    for cid, w in prev.items():
        if cid in channels:
            per[channels[cid].content_project_id][2] += w.views
    if per:
        out += ["", "Themenbereiche"]
        for pid, (n, v, pv) in sorted(per.items(), key=lambda kv: -kv[1][1]):
            out.append(f"- {projects.get(pid, '?')}: {n} Beiträge, {_n(v)} Aufrufe ({_pct(v, pv)})")

    # best posts
    latest = accounts._latest_metrics()
    top = session.execute(
        select(Post.channel_id, Variant.title, Post.url, latest.c.views)
        .join(Variant, Variant.id == Post.variant_id)
        .join(latest, latest.c.post_id == Post.id)
        .where(Post.published_at >= start, Post.published_at < end, latest.c.views.is_not(None))
        .order_by(latest.c.views.desc())
        .limit(3)
    ).all()
    if top:
        out += ["", "Lief am besten"]
        for cid, title, url, v in top:
            name = channels[cid].name if cid in channels else "?"
            out.append(
                f"- {title or 'Ohne Titel'} ({name}): {_n(v)} Aufrufe"
                + (f"\n  {url}" if url else "")
            )

    # channels moving
    up, down = [], []
    for cid in set(week) | set(prev):
        wa, wb = week.get(cid), prev.get(cid)
        va, vb = (wa.views if wa else 0), (wb.views if wb else 0)
        if vb >= 100 and va >= vb * (1 + CHANGE):
            up.append((cid, va, vb))
        elif vb >= 100 and va <= vb * (1 - CHANGE):
            down.append((cid, va, vb))
    overview = accounts.overview(session, settings, now)
    pause = [a for a in overview if a.status == "pause_suggested"]
    if up or down or pause:
        out += ["", "Kanäle"]
        for cid, va, vb in sorted(up, key=lambda x: -x[1]):
            out.append(f"- wächst: {channels[cid].name} ({_pct(va, vb)})")
        for cid, va, vb in sorted(down, key=lambda x: x[1]):
            out.append(f"- lässt nach: {channels[cid].name} ({_pct(va, vb)})")
        for a in pause:
            out.append(f"- Pausieren erwägen: {a.name}")

    # money
    summary = accounts.summary(overview)
    revenue = session.scalar(
        select(func.coalesce(func.sum(RevenueEntry.amount_eur), 0)).where(
            RevenueEntry.period_end >= first
        )
    )
    cost = budget.spent_this_month(session, now)
    out += ["", "Geld"]
    out.append(f"- Einnahmen eingetragen (diese Woche): {_eur(Decimal(revenue or 0))}")
    estimate = summary.get("estimate_30d")
    if estimate:
        out.append(f"- Content Rewards, geschätzt (30 Tage): {_eur(estimate)}")
    out.append(f"- Kosten diesen Monat (KI und Dienste): {_eur(cost)}")
    report.data.update(revenue=float(revenue or 0), cost_month=float(cost))

    # to do
    todo = []
    review = session.scalar(
        select(func.count(Comment.id)).where(Comment.status == CommentStatus.REVIEW)
    )
    if review:
        todo.append(f"{review} Kommentare warten auf deine Antwort (Kommentare)")
    subs = session.scalar(
        select(func.count(CampaignSubmission.id)).where(
            CampaignSubmission.status == SubmissionStatus.OPEN
        )
    )
    if subs:
        todo.append(f"{subs} Kampagnen-Links einreichen (Kampagnen)")
    sponsors_new = session.scalar(
        select(func.count(SponsorInquiry.id)).where(SponsorInquiry.status == "new")
    )
    if sponsors_new:
        todo.append(f"{sponsors_new} neue Sponsorenanfragen (Sponsoren)")
    setup = session.scalar(
        select(func.count(ChannelSetupTask.id)).where(
            ChannelSetupTask.status == ChannelSetupStatus.OPEN
        )
    )
    if setup:
        todo.append(f"{setup} vorbereitete Konten anlegen (Kanal-Assistent)")
    warnings = session.scalars(
        select(Notification.title)
        .where(
            Notification.created_at >= start,
            Notification.level.in_(
                (NotificationLevel.WARNING, NotificationLevel.ERROR, NotificationLevel.CRITICAL)
            ),
        )
        .order_by(Notification.created_at.desc())
        .limit(5)
    ).all()
    out += ["", "Wartet auf dich"]
    out += [f"- {t}" for t in todo] or ["- Nichts Dringendes."]
    if warnings:
        out += ["", "Warnungen der Woche"]
        out += [f"- {w}" for w in warnings]
    report.data["todo"] = todo

    # newsletter
    confirmed_week = session.scalar(
        select(func.count(NewsletterSubscriber.id)).where(
            NewsletterSubscriber.status == "confirmed",
            NewsletterSubscriber.confirmed_at >= start,
        )
    )
    confirmed = session.scalar(
        select(func.count(NewsletterSubscriber.id)).where(
            NewsletterSubscriber.status == "confirmed"
        )
    )
    if confirmed:
        out += ["", f"Newsletter: {confirmed} Leser ({confirmed_week or 0} neu diese Woche)"]

    # next week
    today = local.date()
    plan = planning.plan_between(session, today, today + timedelta(days=6))
    out += ["", "Nächste Woche im Plan"]
    if plan:
        days: dict[date, list[str]] = defaultdict(list)
        for e in plan:
            days[e.day].append(e.project)
        for d in sorted(days):
            out.append(f"- {WEEKDAYS[d.weekday()]} {d:%d.%m.}: {', '.join(days[d])}")
    else:
        out.append("- Noch nichts eingeplant; die Strategie verteilt selbst.")
    out += ["", "Alles Weitere im Dashboard."]
    if settings.push_click_base_url:
        out.append(settings.push_click_base_url.rstrip("/"))
    return report


def sent_this_week(session: Session, settings: Settings, now: datetime) -> bool:
    """A report for the last full week exists already (the subject names the week)."""
    subject = period(settings, now)[4]
    return (
        session.scalar(
            select(OutgoingMail.id).where(
                OutgoingMail.kind == KIND, OutgoingMail.subject == subject
            )
        )
        is not None
    )


def send(session: Session, settings: Settings, now: datetime | None = None) -> OutgoingMail:
    report = build(session, settings, now)
    return mailer.send(
        session, settings, settings.report_email or "", report.subject, report.text, kind=KIND
    )


def maybe_send(
    session: Session, settings: Settings, now: datetime | None = None
) -> OutgoingMail | None:
    """Send this week's report once the configured weekday and hour are reached."""
    if not settings.report_enabled:
        return None
    now = now or datetime.now(UTC)
    local = now.astimezone(ZoneInfo(settings.timezone))
    due = (local.weekday(), local.hour) >= (settings.report_weekday, settings.report_hour)
    if not due or sent_this_week(session, settings, now):
        return None
    return send(session, settings, now)
