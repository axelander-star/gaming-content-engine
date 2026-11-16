"""Notifications for the bell and push to the phone (Ausbau A4).

Every part of the engine adds :class:`Notification` rows (system check, licences,
campaigns, the watchdog). :func:`deliver` runs once a minute in the scheduler and
pushes the important ones to the phone through ntfy (https://docs.ntfy.sh/publish/):
one HTTP ``POST`` of the text to the topic URL, title and priority as headers.

Kept deliberately quiet so it does not annoy:

* only from ``PUSH_MIN_LEVEL`` (default: warning) upwards, the rest stays in the bell;
* no push during quiet hours (default 22–7 local time) unless critical; what came in
  overnight goes out as one summary push in the morning;
* the same title is pushed at most once per ``WATCHDOG_REPEAT_HOURS``;
* more than three at once are combined into one push.

``PUSH_MODE=mock`` (default) only marks notifications as ``mock``: nothing leaves
the server.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import NotificationLevel
from models.access import Notification

log = logging.getLogger(__name__)

ORDER = {
    NotificationLevel.INFO: 0,
    NotificationLevel.WARNING: 1,
    NotificationLevel.ERROR: 2,
    NotificationLevel.CRITICAL: 3,
}
#: ntfy priorities: 5 max, 4 high, 3 default, 2 low.
_PRIORITY = {
    NotificationLevel.INFO: "2",
    NotificationLevel.WARNING: "3",
    NotificationLevel.ERROR: "4",
    NotificationLevel.CRITICAL: "5",
}
_TAGS = {
    NotificationLevel.INFO: "information_source",
    NotificationLevel.WARNING: "warning",
    NotificationLevel.ERROR: "x",
    NotificationLevel.CRITICAL: "rotating_light",
}
#: Older notifications are never pushed (they would only be noise).
MAX_AGE = timedelta(hours=12)
COMBINE_FROM = 4
MAX_BODY = 3500  # ntfy sends longer messages as attachment (limit 4096 bytes)

#: Tests swap in an ``httpx.MockTransport``.
TRANSPORT: httpx.BaseTransport | None = None


@dataclass(frozen=True)
class PushResult:
    sent: int = 0
    combined: int = 0
    skipped: int = 0
    failed: int = 0
    waiting: int = 0


def add(
    session: Session,
    title: str,
    body: str | None = None,
    *,
    level: NotificationLevel = NotificationLevel.INFO,
    kind: str | None = None,
    link: str | None = None,
    dedup_key: str | None = None,
    user_id: int | None = None,
) -> Notification:
    row = Notification(
        title=title[:200],
        body=(body or None) and body[:4000],
        level=level,
        kind=kind,
        link=link,
        dedup_key=dedup_key,
        user_id=user_id,
    )
    session.add(row)
    session.flush()
    return row


def recently(session: Session, dedup_key: str, hours: int, now: datetime) -> bool:
    """Whether a notification with this key was created within the last ``hours``."""
    since = now - timedelta(hours=hours)
    return (
        session.scalar(
            select(func.count(Notification.id)).where(
                Notification.dedup_key == dedup_key, Notification.created_at >= since
            )
        )
        or 0
    ) > 0


def configured(settings: Settings) -> bool:
    return bool(settings.push_ntfy_url.get_secret_value().strip())


def in_quiet_hours(settings: Settings, now: datetime) -> bool:
    start, end = settings.push_quiet_start, settings.push_quiet_end
    if start == end:
        return False
    hour = now.astimezone(ZoneInfo(settings.timezone)).hour
    return start <= hour or hour < end if start > end else start <= hour < end


def _header(value: str) -> str:
    """RFC 2047 for non-ASCII header values (ntfy docs: not every client sends UTF-8)."""
    try:
        value.encode("ascii")
        return value
    except UnicodeEncodeError:
        return "=?UTF-8?B?" + base64.b64encode(value.encode()).decode() + "?="


def send_push(
    settings: Settings,
    title: str,
    body: str,
    level: NotificationLevel,
    click: str | None = None,
    client: httpx.Client | None = None,
) -> str:
    """Send one push; returns ``sent`` or ``mock``. Raises ``httpx.HTTPError``."""
    if settings.push_mode != "live" or not configured(settings):
        return "mock"
    headers = {
        "Title": _header(title[:200]),
        "Priority": _PRIORITY[level],
        "Tags": _TAGS[level],
    }
    if click and settings.push_click_base_url:
        headers["Click"] = settings.push_click_base_url.rstrip("/") + click
    token = settings.push_ntfy_token.get_secret_value()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    own = client is None
    http = client or httpx.Client(timeout=settings.http_timeout_s, transport=TRANSPORT)
    try:
        resp = http.post(
            settings.push_ntfy_url.get_secret_value().strip(),
            content=(body or title)[:MAX_BODY].encode(),
            headers=headers,
        )
        resp.raise_for_status()
    finally:
        if own:
            http.close()
    return "sent"


def _pending(session: Session, now: datetime) -> list[Notification]:
    return list(
        session.scalars(
            select(Notification)
            .where(Notification.push_state.is_(None), Notification.created_at >= now - MAX_AGE)
            .order_by(Notification.id)
        )
    )


def _mark(session: Session, rows: Iterable[Notification], state: str, now: datetime) -> int:
    ids = [r.id for r in rows]
    if ids:
        session.execute(
            update(Notification)
            .where(Notification.id.in_(ids))
            .values(push_state=state, pushed_at=now if state in ("sent", "mock") else None)
        )
    return len(ids)


def _pushed_title_recently(session: Session, title: str, hours: int, now: datetime) -> bool:
    since = now - timedelta(hours=hours)
    return (
        session.scalar(
            select(func.count(Notification.id)).where(
                Notification.title == title,
                Notification.push_state.in_(("sent", "mock")),
                Notification.pushed_at >= since,
            )
        )
        or 0
    ) > 0


def deliver(
    session: Session,
    settings: Settings,
    now: datetime | None = None,
    client: httpx.Client | None = None,
) -> PushResult:
    """Push what is due; commits. Safe to call every minute."""
    now = now or datetime.now(UTC)
    minimum = ORDER[NotificationLevel(settings.push_min_level)]
    stale = session.scalars(
        select(Notification).where(
            Notification.push_state.is_(None), Notification.created_at < now - MAX_AGE
        )
    ).all()
    skipped = _mark(session, stale, "skipped", now)

    due: list[Notification] = []
    for row in _pending(session, now):
        if ORDER[row.level] < minimum or _pushed_title_recently(
            session, row.title, settings.watchdog_repeat_hours, now
        ):
            skipped += _mark(session, [row], "skipped", now)
        else:
            due.append(row)

    quiet = in_quiet_hours(settings, now)
    waiting = [r for r in due if quiet and r.level != NotificationLevel.CRITICAL]
    due = [r for r in due if r not in waiting]

    sent = failed = combined = 0
    batches: list[tuple[str, str, NotificationLevel, str | None, list[Notification]]] = []
    if len(due) >= COMBINE_FROM:
        worst = max(due, key=lambda r: ORDER[r.level])
        lines = [f"• {r.title}" for r in due[:12]]
        if len(due) > 12:
            lines.append(f"… und {len(due) - 12} weitere")
        batches.append((f"{len(due)} neue Hinweise", "\n".join(lines), worst.level, "/", list(due)))
        combined = len(due)
    else:
        for r in due:
            batches.append((r.title, r.body or r.title, r.level, r.link, [r]))

    for title, body, level, link, rows in batches:
        try:
            state = send_push(settings, title, body, level, link, client)
        except httpx.HTTPError as exc:
            # Never log the URL: the topic name is the secret.
            log.warning("push failed", extra={"error": type(exc).__name__})
            failed += _mark(session, rows, "failed", now)
            continue
        sent += _mark(session, rows, state, now)
    session.commit()
    return PushResult(
        sent=sent, combined=combined, skipped=skipped, failed=failed, waiting=len(waiting)
    )


def test_push(settings: Settings, client: httpx.Client | None = None) -> str:
    return send_push(
        settings,
        "Test von der Content Engine",
        "Wenn du das liest, kommen Warnungen auf dem Handy an.",
        NotificationLevel.WARNING,
        "/",
        client,
    )


def unread_count(session: Session) -> int:
    return int(
        session.scalar(select(func.count(Notification.id)).where(Notification.read_at.is_(None)))
        or 0
    )


def recent(session: Session, limit: int = 50, unread_only: bool = False) -> list[Notification]:
    q = select(Notification)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    return list(session.scalars(q.order_by(Notification.id.desc()).limit(limit)))


def mark_read(session: Session, ids: list[int] | None, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    q = update(Notification).where(Notification.read_at.is_(None))
    if ids is not None:
        q = q.where(Notification.id.in_(ids))
    result = session.execute(q.values(read_at=now))
    session.commit()
    return int(getattr(result, "rowcount", 0) or 0)
