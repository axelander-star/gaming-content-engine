"""Storage report and clean-up. Run with ``python -m app.housekeeping <command>``.

Commands:

* ``report [--json] [--minutes-per-week N]``  what lies where, plus a one-year
  projection for N minutes of new video per week (default 30)
* ``cleanup [--apply] [--tmp-hours H] [--orphan-days D]``  list (or, with
  ``--apply``, delete) old scratch files and files no database row references

Without ``--apply`` nothing is deleted. Rules: docs/HETZNER_VORBEREITUNG.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from core.config import get_settings
from core.logging import configure_logging
from database.session import get_sessionmaker
from services import housekeeping

log = logging.getLogger("housekeeping")


def _mb(n: float) -> str:
    return f"{n / 1e6:,.1f} MB".replace(",", ".")


def _report(args: argparse.Namespace) -> int:
    settings = get_settings()
    with get_sessionmaker()() as session:
        rep = housekeeping.storage_report(session, settings)
    rate = rep.mb_per_video_minute
    # Original plus 9:16 version plus preview: roughly twice the original.
    year_mb = rate * 2 * args.minutes_per_week * 52 if rate else None
    if args.json:
        out = rep.as_dict() | {"projected_year_mb": year_mb}
        print(json.dumps(out, indent=2))
        return 0
    print("Medien (MEDIA_ROOT):")
    for f in rep.media:
        print(f"  {f.folder:<24} {f.files:>6} Dateien  {_mb(f.bytes):>14}")
    print(f"  {'gesamt':<24} {'':>6}          {_mb(rep.media_bytes):>14}")
    print(f"Sicherungen: {rep.backup_files} Dateien, {_mb(rep.backup_bytes)}")
    if rep.database_bytes is not None:
        print(f"Datenbank: {_mb(rep.database_bytes)}")
    print(f"Archivierte Mediathek-Dateien (Originale): {_mb(rep.archived_bytes)}")
    if rate:
        print(f"Mediathek-Videos: {rep.library_videos}, im Schnitt {rate:.1f} MB je Minute")
        print(
            f"Hochrechnung 1 Jahr bei {args.minutes_per_week} min neuem Video je Woche: "
            f"ca. {_mb(year_mb * 1e6 if year_mb else 0)} (Original + 9:16-Fassung)"
        )
    else:
        print("Noch keine Mediathek-Videos: keine Hochrechnung möglich.")
    return 0


def _cleanup(args: argparse.Namespace) -> int:
    settings = get_settings()
    with get_sessionmaker()() as session:
        res = housekeeping.cleanup(
            session,
            settings,
            apply=args.apply,
            tmp_hours=args.tmp_hours,
            orphan_days=args.orphan_days,
        )
    verb = "gelöscht" if res.applied else "würde gelöscht (Probelauf, nichts geändert)"
    for path in res.tmp:
        print(f"tmp      {path}")
    for path in res.orphans:
        print(f"verwaist {path}")
    if res.refused:
        print(f"Hinweis: {res.refused}")
    print(f"{len(res.candidates)} Dateien, {_mb(res.freed_bytes)} {verb}")
    log.info(
        "housekeeping cleanup",
        extra={
            "applied": res.applied,
            "tmp": len(res.tmp),
            "orphans": len(res.orphans),
            "bytes": res.freed_bytes,
        },
    )
    return 2 if res.refused else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.housekeeping")
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report", help="Speicherbelegung und Hochrechnung")
    rep.add_argument("--json", action="store_true")
    rep.add_argument("--minutes-per-week", type=float, default=30)
    cln = sub.add_parser("cleanup", help="alte Arbeitsdateien und verwaiste Dateien")
    cln.add_argument("--apply", action="store_true", help="wirklich löschen")
    cln.add_argument("--tmp-hours", type=float, default=6)
    cln.add_argument("--orphan-days", type=float, default=7)
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    return _report(args) if args.command == "report" else _cleanup(args)


if __name__ == "__main__":
    sys.exit(main())
