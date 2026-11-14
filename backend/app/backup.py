"""Backups from the command line. Run with ``python -m app.backup <command>``.

Commands:

* ``run``           back up now, test the restore, prune old backups
* ``list``          show the backups and their restore tests
* ``restore-test``  restore the newest backup into a scratch database and compare
* ``restore FILE --into NEW_DB --yes``  restore into a new database (disaster recovery)
* ``loop``          stay running and do ``run`` once a day at ``BACKUP_HOUR`` (TZ)
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import UTC, datetime, timedelta
from types import FrameType
from zoneinfo import ZoneInfo

from core.config import Settings, get_settings
from core.enums import NotificationLevel
from core.logging import configure_logging
from database.session import get_sessionmaker
from models.access import Notification
from services import backup, monitoring
from services.queue import get_redis

log = logging.getLogger("backup")


def _notify(level: NotificationLevel, title: str, body: str) -> None:
    try:
        with get_sessionmaker()() as session:
            session.add(Notification(level=level, title=title[:200], body=body[:2000]))
            session.commit()
    except Exception:  # the notification is a bonus; the log line is the record
        log.exception("could not store notification")


def run_once(settings: Settings) -> bool:
    """Backup, restore test and pruning. Returns True if everything worked."""
    try:
        manifest = backup.create_backup(settings)
        check = backup.restore_test(settings, manifest)
        removed = backup.prune(settings)
    except backup.BackupError as exc:
        log.error("backup failed", extra={"error": str(exc)})
        _notify(NotificationLevel.CRITICAL, "Datensicherung fehlgeschlagen", str(exc))
        return False
    if not check.ok:
        _notify(
            NotificationLevel.CRITICAL,
            "Wiederherstellungstest fehlgeschlagen",
            f"{manifest.file}: " + "; ".join(check.problems),
        )
        return False
    log.info(
        "backup cycle done",
        extra={"file": manifest.file, "rows": check.rows, "pruned": removed},
    )
    return True


def next_run(now: datetime, hour: int, tz: ZoneInfo) -> datetime:
    """The next ``hour``:00 in local time, as UTC."""
    local = now.astimezone(tz)
    target = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= local:
        target = (target + timedelta(days=1)).replace(hour=hour)
    return target.astimezone(UTC)


def loop(settings: Settings) -> int:
    running = True

    def _stop(signum: int, frame: FrameType | None) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    tz = ZoneInfo(settings.timezone)
    due = next_run(datetime.now(UTC), settings.backup_hour, tz)
    # Start-up: if the newest backup is already older than a day, do not wait for the night.
    st = backup.status(settings)
    if st.configured and (st.age_hours is None or st.age_hours > 24):
        due = datetime.now(UTC)
    log.info("backup loop starting", extra={"next_run": due.isoformat()})
    while running:
        now = datetime.now(UTC)
        try:
            monitoring.beat(get_redis(), "backup", now)
        except Exception:
            log.warning("heartbeat failed", exc_info=True)
        if now >= due:
            run_once(settings)
            due = next_run(datetime.now(UTC), settings.backup_hour, tz)
            log.info("next backup", extra={"next_run": due.isoformat()})
        time.sleep(30)
    return 0


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    parser = argparse.ArgumentParser(prog="python -m app.backup")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    sub.add_parser("list")
    sub.add_parser("restore-test")
    sub.add_parser("loop")
    rp = sub.add_parser("restore")
    rp.add_argument("file")
    rp.add_argument("--into", required=True, dest="target")
    rp.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "run":
        return 0 if run_once(settings) else 1
    if args.command == "loop":
        return loop(settings)
    if args.command == "list":
        for m in backup.list_backups(settings):
            rc = m.restore_check or {}
            test = "nicht getestet" if not rc else ("ok" if rc.get("ok") else "FEHLER")
            size, rows = m.size_bytes / 1024**2, sum(m.tables.values())
            print(f"{m.file}  {size:8.1f} MB  {rows:8d} Zeilen  {test}")
        return 0
    if args.command == "restore-test":
        try:
            check = backup.restore_test(settings)
        except backup.BackupError as exc:
            print(f"Fehler: {exc}", file=sys.stderr)
            return 1
        verdict = "ok" if check.ok else "FEHLER"
        print(f"{check.file}: {verdict} ({check.tables} Tabellen, {check.rows} Zeilen)")
        for p in check.problems:
            print(f"  - {p}")
        return 0 if check.ok else 1
    if args.command == "restore":
        if not args.yes:
            print("Zur Bestätigung --yes angeben.", file=sys.stderr)
            return 2
        try:
            tables = backup.restore(settings, args.file, args.target)
        except backup.BackupError as exc:
            print(f"Fehler: {exc}", file=sys.stderr)
            return 1
        rows = sum(tables.values())
        print(f"Wiederhergestellt in {args.target}: {len(tables)} Tabellen, {rows} Zeilen")
        return 0
    return 2  # pragma: no cover - argparse rejects unknown commands


if __name__ == "__main__":
    sys.exit(main())
