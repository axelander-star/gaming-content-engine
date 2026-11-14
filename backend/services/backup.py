"""Encrypted PostgreSQL backups with a restore test (PROJECT_SPEC section 15, Phase 15).

A backup is a ``pg_dump`` custom-format archive, encrypted with GnuPG (symmetric,
AES-256) using ``BACKUP_PASSPHRASE``. Next to each ``*.dump.gpg`` lies a JSON
manifest with size, SHA-256, schema version and the row count of every table.

The counts are taken in the same snapshot that ``pg_dump`` uses
(``pg_export_snapshot``), so the restore test can demand exact equality: it
decrypts the newest dump into a scratch database, compares schema version,
table set and every row count, and drops the scratch database again.

Restoring for real (:func:`restore`) always goes into a *new* database; the
live database is never dropped or overwritten by this module.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from core.config import Settings

log = logging.getLogger(__name__)

SUFFIX = ".dump.gpg"
MANIFEST_SUFFIX = ".json"
RESTORE_CHECK_FILE = "restore-check.json"
RESTORE_CMD = ("pg_restore", "--no-owner", "--no-acl", "--exit-on-error")
_NAME = re.compile(r"^gce-(\d{8}-\d{6})\.dump\.gpg$")
_DB_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class BackupError(RuntimeError):
    """A backup, restore test or restore could not be completed."""


@dataclass
class Manifest:
    file: str
    created_at: str
    size_bytes: int
    sha256: str
    database: str
    alembic_version: str | None
    tables: dict[str, int]
    restore_check: dict[str, Any] | None = None

    @property
    def created(self) -> datetime:
        return datetime.fromisoformat(self.created_at)


@dataclass
class RestoreCheck:
    file: str
    checked_at: str
    ok: bool
    duration_s: float
    tables: int = 0
    rows: int = 0
    problems: list[str] = field(default_factory=list)


# --- connection helpers ---------------------------------------------------------


@dataclass(frozen=True)
class Conn:
    host: str
    port: int
    user: str
    password: str
    database: str

    def env(self, database: str | None = None) -> dict[str, str]:
        """Environment for the libpq tools; the password never appears on a command line."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
        env.update(
            PGHOST=self.host,
            PGPORT=str(self.port),
            PGUSER=self.user,
            PGDATABASE=database or self.database,
            PGCONNECT_TIMEOUT="10",
        )
        if self.password:
            env["PGPASSWORD"] = self.password
        return env

    def connect(self, database: str | None = None, autocommit: bool = False) -> psycopg.Connection:
        return psycopg.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password or None,
            dbname=database or self.database,
            autocommit=autocommit,
            connect_timeout=10,
        )


def connection(settings: Settings) -> Conn:
    url = make_url(settings.database_url)
    return Conn(
        host=url.host or "localhost",
        port=url.port or 5432,
        user=url.username or "",
        password=url.password or "",
        database=url.database or "",
    )


def backup_dir(settings: Settings) -> Path:
    path = Path(settings.backup_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _passphrase(settings: Settings) -> bytes:
    value = settings.backup_passphrase.get_secret_value()
    if len(value) < 16:
        raise BackupError("BACKUP_PASSPHRASE fehlt oder ist kürzer als 16 Zeichen")
    return value.encode()


@contextlib.contextmanager
def _gpg(settings: Settings, *args: str) -> Iterator[tuple[list[str], int]]:
    """GnuPG command line with its own empty home and the passphrase on a pipe."""
    home = tempfile.mkdtemp(prefix="gce-gnupg-")
    os.chmod(home, 0o700)
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, _passphrase(settings))
        os.close(write_fd)
        write_fd = -1
        cmd = [
            "gpg",
            "--homedir",
            home,
            "--batch",
            "--yes",
            "--quiet",
            "--no-tty",
            "--pinentry-mode",
            "loopback",
            "--passphrase-fd",
            str(read_fd),
            *args,
        ]
        yield cmd, read_fd
    finally:
        if write_fd >= 0:
            os.close(write_fd)
        os.close(read_fd)
        shutil.rmtree(home, ignore_errors=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tables(cur: psycopg.Cursor[Any]) -> dict[str, int]:
    """Exact row count of every table in the public schema."""
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
    names = [row[0] for row in cur.fetchall()]
    counts: dict[str, int] = {}
    for name in names:
        cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("public", name)))
        row = cur.fetchone()
        counts[name] = int(row[0]) if row else 0
    return counts


def _alembic_version(cur: psycopg.Cursor[Any], tables: dict[str, int]) -> str | None:
    if "alembic_version" not in tables:
        return None
    cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
    row = cur.fetchone()
    return str(row[0]) if row else None


def _stderr(proc: subprocess.CompletedProcess[bytes] | subprocess.Popen[bytes]) -> str:
    raw = proc.stderr if isinstance(proc, subprocess.CompletedProcess) else b""
    return (raw or b"").decode(errors="replace").strip()[-500:]


# --- backup ---------------------------------------------------------------------


def create_backup(settings: Settings, now: datetime | None = None) -> Manifest:
    """Dump, encrypt and describe the database. Returns the manifest."""
    now = now or datetime.now(UTC)
    conn = connection(settings)
    target_dir = backup_dir(settings)
    name = f"gce-{now.strftime('%Y%m%d-%H%M%S')}{SUFFIX}"
    final = target_dir / name
    part = target_dir / f".{name}.part"
    with conn.connect() as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        with db.cursor() as cur:
            cur.execute("SELECT pg_export_snapshot()")
            row = cur.fetchone()
            assert row is not None
            snapshot = str(row[0])
            tables = _tables(cur)
            version = _alembic_version(cur, tables)
        dump_cmd = [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-acl",
            f"--snapshot={snapshot}",
        ]
        with _gpg(
            settings,
            "--symmetric",
            "--cipher-algo",
            "AES256",
            "--compress-algo",
            "none",
            "--output",
            str(part),
        ) as (gpg_cmd, fd):
            dump = subprocess.Popen(  # noqa: S603 - fixed argument list
                dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=conn.env()
            )
            assert dump.stdout is not None
            try:
                enc = subprocess.run(  # noqa: S603
                    gpg_cmd,
                    stdin=dump.stdout,
                    capture_output=True,
                    pass_fds=(fd,),
                    timeout=settings.backup_timeout_s,
                    check=False,
                )
            finally:
                dump.stdout.close()
                dump_err = dump.stderr.read().decode(errors="replace") if dump.stderr else ""
                dump_rc = dump.wait(timeout=60)
        db.rollback()
    if dump_rc != 0 or enc.returncode != 0:
        part.unlink(missing_ok=True)
        detail = dump_err.strip()[-500:] if dump_rc else _stderr(enc)
        raise BackupError(f"Sicherung fehlgeschlagen: {detail or 'unbekannter Fehler'}")
    part.rename(final)
    os.chmod(final, 0o600)
    manifest = Manifest(
        file=name,
        created_at=now.isoformat(),
        size_bytes=final.stat().st_size,
        sha256=_sha256(final),
        database=conn.database,
        alembic_version=version,
        tables=tables,
    )
    _write_manifest(target_dir, manifest)
    log.info(
        "backup written",
        extra={"file": name, "bytes": manifest.size_bytes, "tables": len(tables)},
    )
    return manifest


def _manifest_path(directory: Path, file: str) -> Path:
    return directory / (file.removesuffix(SUFFIX) + MANIFEST_SUFFIX)


def _write_manifest(directory: Path, manifest: Manifest) -> None:
    path = _manifest_path(directory, manifest.file)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(manifest), indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def list_backups(settings: Settings) -> list[Manifest]:
    """Every backup with a readable manifest, newest first."""
    directory = backup_dir(settings)
    result = []
    for path in directory.glob(f"gce-*{SUFFIX}"):
        if not _NAME.match(path.name):
            continue
        meta = _manifest_path(directory, path.name)
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            result.append(Manifest(**data))
        except (OSError, ValueError, TypeError):
            log.warning("backup without readable manifest", extra={"file": path.name})
    return sorted(result, key=lambda m: m.created_at, reverse=True)


# --- restore test ----------------------------------------------------------------


def _scratch_name(conn: Conn) -> str:
    name = f"{conn.database}_restore_check"[:63]
    if not _DB_NAME.match(name):
        raise BackupError(f"Ungültiger Datenbankname für den Wiederherstellungstest: {name}")
    return name


def _recreate(conn: Conn, name: str, drop_first: bool) -> None:
    with conn.connect(database="postgres", autocommit=True) as admin:
        if drop_first:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def _drop(conn: Conn, name: str) -> None:
    with conn.connect(database="postgres", autocommit=True) as admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))


def _decrypt_into(settings: Settings, path: Path, conn: Conn, database: str) -> None:
    with _gpg(settings, "--decrypt", str(path)) as (gpg_cmd, fd):
        dec = subprocess.Popen(  # noqa: S603
            gpg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(fd,)
        )
        assert dec.stdout is not None
        try:
            res = subprocess.run(  # noqa: S603
                [*RESTORE_CMD, "--dbname", database],
                stdin=dec.stdout,
                capture_output=True,
                env=conn.env(database),
                timeout=settings.backup_timeout_s,
                check=False,
            )
        finally:
            dec.stdout.close()
            dec_err = dec.stderr.read().decode(errors="replace") if dec.stderr else ""
            dec_rc = dec.wait(timeout=60)
    if dec_rc != 0:
        raise BackupError(f"Entschlüsselung fehlgeschlagen: {dec_err.strip()[-300:]}")
    if res.returncode != 0:
        raise BackupError(f"pg_restore fehlgeschlagen: {_stderr(res)}")


def restore_test(settings: Settings, manifest: Manifest | None = None) -> RestoreCheck:
    """Restore a backup into a scratch database and compare it with its manifest."""
    started = datetime.now(UTC)
    if manifest is None:
        backups = list_backups(settings)
        if not backups:
            raise BackupError("Keine Sicherung vorhanden")
        manifest = backups[0]
    directory = backup_dir(settings)
    path = directory / manifest.file
    conn = connection(settings)
    scratch = _scratch_name(conn)
    problems: list[str] = []
    restored: dict[str, int] = {}
    try:
        if _sha256(path) != manifest.sha256:
            raise BackupError("Prüfsumme stimmt nicht: Datei beschädigt oder verändert")
        _recreate(conn, scratch, drop_first=True)
        _decrypt_into(settings, path, conn, scratch)
        with conn.connect(database=scratch) as db, db.cursor() as cur:
            restored = _tables(cur)
            version = _alembic_version(cur, restored)
        if version != manifest.alembic_version:
            problems.append(f"Schema-Version {version} statt {manifest.alembic_version}")
        missing = sorted(set(manifest.tables) - set(restored))
        if missing:
            problems.append(f"Tabellen fehlen: {', '.join(missing)}")
        for table, expected in sorted(manifest.tables.items()):
            got = restored.get(table)
            if got is not None and got != expected:
                problems.append(f"{table}: {got} statt {expected} Zeilen")
    except (BackupError, OSError, psycopg.Error, subprocess.SubprocessError) as exc:
        problems.append(str(exc)[:500])
    finally:
        with contextlib.suppress(psycopg.Error):
            _drop(conn, scratch)
    check = RestoreCheck(
        file=manifest.file,
        checked_at=datetime.now(UTC).isoformat(),
        ok=not problems,
        duration_s=round((datetime.now(UTC) - started).total_seconds(), 2),
        tables=len(restored),
        rows=sum(restored.values()),
        problems=problems,
    )
    manifest.restore_check = asdict(check)
    with contextlib.suppress(OSError):
        _write_manifest(directory, manifest)
    (directory / RESTORE_CHECK_FILE).write_text(
        json.dumps(asdict(check), indent=2), encoding="utf-8"
    )
    log.log(
        logging.INFO if check.ok else logging.ERROR,
        "restore test finished",
        extra={"file": manifest.file, "ok": check.ok, "problems": problems[:5]},
    )
    return check


def last_restore_check(settings: Settings) -> RestoreCheck | None:
    path = backup_dir(settings) / RESTORE_CHECK_FILE
    try:
        return RestoreCheck(**json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


# --- retention and real restore ------------------------------------------------------


def prune(settings: Settings, now: datetime | None = None) -> list[str]:
    """Delete backups older than ``BACKUP_KEEP_DAYS``; the newest ``BACKUP_KEEP_MIN`` stay."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=settings.backup_keep_days)
    directory = backup_dir(settings)
    removed = []
    for manifest in list_backups(settings)[settings.backup_keep_min :]:
        if manifest.created < cutoff:
            (directory / manifest.file).unlink(missing_ok=True)
            _manifest_path(directory, manifest.file).unlink(missing_ok=True)
            removed.append(manifest.file)
    for stale in directory.glob(".gce-*.part"):  # left over from an interrupted run
        if datetime.fromtimestamp(stale.stat().st_mtime, UTC) < now - timedelta(days=1):
            stale.unlink(missing_ok=True)
    return removed


def restore(settings: Settings, file: str, target_db: str) -> dict[str, int]:
    """Restore ``file`` into the new database ``target_db`` (which must not exist yet)."""
    conn = connection(settings)
    if not _DB_NAME.match(target_db):
        raise BackupError("Zieldatenbank: nur Kleinbuchstaben, Ziffern und _ erlaubt")
    if target_db in (conn.database, "postgres", "template0", "template1"):
        raise BackupError("Die Wiederherstellung geht immer in eine neue Datenbank")
    manifest = next((m for m in list_backups(settings) if m.file == file), None)
    if manifest is None:
        raise BackupError(f"Sicherung {file} nicht gefunden")
    path = backup_dir(settings) / file
    if _sha256(path) != manifest.sha256:
        raise BackupError("Prüfsumme stimmt nicht: Datei beschädigt oder verändert")
    try:
        _recreate(conn, target_db, drop_first=False)
    except psycopg.errors.DuplicateDatabase as exc:
        raise BackupError(f"Datenbank {target_db} existiert bereits") from exc
    _decrypt_into(settings, path, conn, target_db)
    with conn.connect(database=target_db) as db, db.cursor() as cur:
        return _tables(cur)


# --- status for monitoring ------------------------------------------------------------


@dataclass
class BackupStatus:
    configured: bool
    count: int
    latest: Manifest | None
    age_hours: float | None
    restore_check: RestoreCheck | None
    total_bytes: int


def status(settings: Settings, now: datetime | None = None) -> BackupStatus:
    now = now or datetime.now(UTC)
    backups = list_backups(settings)
    latest = backups[0] if backups else None
    age = (now - latest.created).total_seconds() / 3600 if latest else None
    return BackupStatus(
        configured=len(settings.backup_passphrase.get_secret_value()) >= 16,
        count=len(backups),
        latest=latest,
        age_hours=round(age, 1) if age is not None else None,
        restore_check=last_restore_check(settings),
        total_bytes=sum(m.size_bytes for m in backups),
    )
