"""Warning system (Ausbau A4): turns problems into notifications.

Runs every ``WATCHDOG_SECONDS`` in the scheduler. Each finding has a key, so the
same warning appears at most once per ``WATCHDOG_REPEAT_HOURS``. What is important
enough goes to the phone through :mod:`services.notify`.

Findings:

* **Copyright or block notice** on a publishing attempt (critical): the platform's
  error text mentions copyright, a claim, a strike, a policy or a block.
* **Publishing failed** (warning): other errors, once per channel and day.
* **Connection expired** (warning): the channel must be connected again.
* **Reach drops** (warning): views −30 % against the 30 days before
  (rule from :mod:`services.accounts`).
* **Pause suggested** (info, bell only): see the account overview.
* **Comments waiting** (info, bell only): criticism and sensitive comments.
* **Done** (info, bell only): research the chat started has finished.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import (
    AgentRunStatus,
    ChannelAuthStatus,
    CommentStatus,
    NotificationLevel,
    PublishingJobStatus,
)
from models.assistant import ChatAction
from models.channels import Channel
from models.comments import Comment
from models.control import AgentRun
from models.publishing import PublishingJob
from services import accounts, notify

#: Error texts of the platforms that point at rights or account trouble.
STRIKE = re.compile(
    r"copyright|urheberrecht|content ?id|claim|strike|takedown|dmca|"
    r"community guidelines|policy|richtlinie|blocked|gesperrt|suspend|banned|removed",
    re.IGNORECASE,
)
DONE_WINDOW = timedelta(days=2)


@dataclass
class ScanResult:
    created: list[str] = field(default_factory=list)


def _once(
    session: Session,
    settings: Settings,
    now: datetime,
    result: ScanResult,
    key: str,
    title: str,
    body: str,
    level: NotificationLevel,
    kind: str,
    link: str,
    hours: int | None = None,
) -> None:
    if notify.recently(session, key, hours or settings.watchdog_repeat_hours, now):
        return
    notify.add(session, title, body, level=level, kind=kind, link=link, dedup_key=key)
    result.created.append(key)


def _publishing(session: Session, settings: Settings, now: datetime, result: ScanResult) -> None:
    since = now - timedelta(days=1)
    jobs = session.scalars(
        select(PublishingJob).where(
            PublishingJob.status.in_((PublishingJobStatus.FAILED, PublishingJobStatus.BLOCKED)),
            PublishingJob.updated_at >= since,
            PublishingJob.last_error.is_not(None),
        )
    ).all()
    names = {c.id: c.name for c in session.scalars(select(Channel))}
    failed_by_channel: dict[int, list[PublishingJob]] = {}
    for job in jobs:
        error = job.last_error or ""
        channel = names.get(job.channel_id, f"Kanal {job.channel_id}")
        if STRIKE.search(error):
            _once(
                session, settings, now, result,
                key=f"strike:{job.id}",
                title=f"Rechte- oder Sperrhinweis bei {channel}",
                body=f"Veröffentlichung #{job.id}: {error[:600]}\n"
                "Bitte prüfen, bevor weitere Clips aus diesem Material laufen.",
                level=NotificationLevel.CRITICAL, kind="rights", link="/publishing",
                hours=24 * 30,
            )  # fmt: skip
        else:
            failed_by_channel.setdefault(job.channel_id, []).append(job)
    for channel_id, rows in failed_by_channel.items():
        channel = names.get(channel_id, f"Kanal {channel_id}")
        _once(
            session, settings, now, result,
            key=f"publish_failed:{channel_id}:{now:%Y-%m-%d}",
            title=f"Veröffentlichen fehlgeschlagen: {channel}",
            body=f"{len(rows)} Versuch(e) in den letzten 24 Stunden. Letzter Fehler: "
            f"{(rows[-1].last_error or '')[:400]}",
            level=NotificationLevel.WARNING, kind="publishing", link="/publishing",
        )  # fmt: skip


def _connections(session: Session, settings: Settings, now: datetime, result: ScanResult) -> None:
    expired = session.scalars(
        select(Channel).where(
            Channel.auth_status == ChannelAuthStatus.EXPIRED, Channel.is_paused.is_(False)
        )
    ).all()
    for ch in expired:
        _once(
            session, settings, now, result,
            key=f"auth:{ch.id}",
            title=f"{ch.name}: Verbindung abgelaufen",
            body="Der Kanal kann nichts veröffentlichen, bis er neu verbunden ist "
            "(Themenbereiche → Kanal → Verbinden).",
            level=NotificationLevel.WARNING, kind="channel", link="/themenbereiche",
        )  # fmt: skip


def _reach(session: Session, settings: Settings, now: datetime, result: ScanResult) -> None:
    for acc in accounts.overview(session, settings, now):
        if acc.status == "declining":
            _once(
                session, settings, now, result,
                key=f"reach:{acc.channel_id}",
                title=f"Reichweite bricht ein: {acc.name}",
                body=" ".join(acc.reasons),
                level=NotificationLevel.WARNING, kind="reach", link="/konten",
                hours=24 * 7,
            )  # fmt: skip
        elif acc.status == "pause_suggested":
            _once(
                session, settings, now, result,
                key=f"pause:{acc.channel_id}",
                title=f"Pausieren erwägen: {acc.name}",
                body=" ".join(acc.reasons),
                level=NotificationLevel.INFO, kind="reach", link="/konten",
                hours=24 * 14,
            )  # fmt: skip


def _comments(session: Session, settings: Settings, now: datetime, result: ScanResult) -> None:
    waiting = int(
        session.scalar(select(func.count(Comment.id)).where(Comment.status == CommentStatus.REVIEW))
        or 0
    )
    if waiting:
        _once(
            session, settings, now, result,
            key=f"comments:{now:%Y-%m-%d}",
            title=f"{waiting} Kommentar{'e' if waiting != 1 else ''} warten auf dich",
            body="Kritik, heikle Themen und TikTok-Kommentare brauchen deine Freigabe.",
            level=NotificationLevel.INFO, kind="comments", link="/kommentare",
        )  # fmt: skip


def _chat_jobs(session: Session, settings: Settings, now: datetime, result: ScanResult) -> None:
    """Tell the user when work the chat started has finished."""
    actions = session.scalars(
        select(ChatAction).where(
            ChatAction.tool == "start_research", ChatAction.created_at >= now - DONE_WINDOW
        )
    ).all()
    for action in actions:
        args: dict[str, Any] = dict(action.args or {})
        jobs = args.get("jobs") or {}
        if args.get("notified") or not jobs:
            continue
        runs = session.scalars(
            select(AgentRun).where(AgentRun.queue_job_id.in_([str(j) for j in jobs.values()]))
        ).all()
        finished = [r for r in runs if r.status != AgentRunStatus.RUNNING]
        if len(finished) < len(jobs):
            continue
        failed = [r.agent_name for r in finished if r.status == AgentRunStatus.FAILED]
        project = str(args.get("project") or "").strip()
        title = (
            f"Fertig: Recherche {project}".strip()
            if not failed
            else (f"Recherche {project} mit Fehlern beendet".replace("  ", " "))
        )
        body = (
            "Neue Ideen stehen im Ideenlabor."
            if not failed
            else f"Fehlgeschlagen: {', '.join(failed)}. Details unter Agenten."
        )
        notify.add(
            session, title, body,
            level=NotificationLevel.INFO if not failed else NotificationLevel.WARNING,
            kind="done", link="/ideen" if not failed else "/agenten",
            dedup_key=f"done:{action.id}", user_id=action.user_id,
        )  # fmt: skip
        args["notified"] = True
        action.args = args
        result.created.append(f"done:{action.id}")


CHECKS = (_publishing, _connections, _reach, _comments, _chat_jobs)


def scan(session: Session, settings: Settings, now: datetime | None = None) -> ScanResult:
    """Run every check; commits."""
    now = now or datetime.now(UTC)
    result = ScanResult()
    for check in CHECKS:
        check(session, settings, now, result)
        session.flush()
    session.commit()
    return result
