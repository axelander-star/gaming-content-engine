"""Phase 15: encrypted backups with restore test, system checks, alerts, scaling criteria."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis import Redis
from rq import Queue, Worker
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import backup as backup_cli
from app.scheduler import Monitor
from core.config import Settings, get_settings
from core.enums import AgentRunStatus, NotificationLevel, UserRole
from models.access import Notification, User
from models.control import AgentRun
from services import backup, monitoring
from tests.conftest import login

PASS = "a-long-test-passphrase-123"
NOW = datetime.now(UTC)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(
        update={
            "backup_dir": str(tmp_path / "backups"),
            "media_root": str(tmp_path / "media"),
            "backup_passphrase": SecretStr(PASS),
        }
    )


@pytest.fixture
def dumped(engine: Any, settings: Settings) -> Iterator[backup.Manifest]:
    """One real backup of the (migrated) test database."""
    yield backup.create_backup(settings, NOW)


def _drop(settings: Settings, name: str) -> None:
    conn = backup.connection(settings)
    with conn.connect(database="postgres", autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}"')


# --- backups ------------------------------------------------------------------------


def test_backup_is_encrypted_and_restore_test_passes(
    settings: Settings, dumped: backup.Manifest
) -> None:
    path = Path(settings.backup_dir) / dumped.file
    raw = path.read_bytes()
    assert not raw.startswith(b"PGDMP")  # pg_dump's magic would mean plaintext
    assert b"alembic_version" not in raw and b"CREATE TABLE" not in raw
    assert path.stat().st_mode & 0o777 == 0o600
    assert "alembic_version" in dumped.tables and dumped.tables["alembic_version"] == 1
    assert dumped.alembic_version and len(dumped.tables) > 20

    check = backup.restore_test(settings, dumped)
    assert check.ok, check.problems
    assert check.tables == len(dumped.tables)
    assert backup.last_restore_check(settings) == check
    listed = backup.list_backups(settings)
    assert listed[0].file == dumped.file and listed[0].restore_check["ok"] is True  # type: ignore[index]
    # the scratch database is gone again
    conn = backup.connection(settings)
    with conn.connect(database="postgres") as admin:
        row = admin.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (backup._scratch_name(conn),)
        ).fetchone()
    assert row is None


def test_restore_test_detects_wrong_key_tampering_and_count_mismatch(
    settings: Settings, dumped: backup.Manifest
) -> None:
    wrong = settings.model_copy(update={"backup_passphrase": SecretStr("another-passphrase-xyz")})
    check = backup.restore_test(wrong, dumped)
    assert not check.ok and "Entschlüsselung" in check.problems[0]

    altered = backup.Manifest(**{**vars(dumped), "tables": {**dumped.tables, "users": 99}})
    check = backup.restore_test(settings, altered)
    assert not check.ok and any("users: 0 statt 99" in p for p in check.problems)

    path = Path(settings.backup_dir) / dumped.file
    path.write_bytes(path.read_bytes()[:-10] + b"x" * 10)
    check = backup.restore_test(settings, dumped)
    assert not check.ok and "Prüfsumme" in check.problems[0]


def test_backup_needs_a_passphrase(settings: Settings) -> None:
    short = settings.model_copy(update={"backup_passphrase": SecretStr("short")})
    with pytest.raises(backup.BackupError, match="BACKUP_PASSPHRASE"):
        backup.create_backup(short)
    assert not backup.status(short).configured
    assert not list(Path(settings.backup_dir).glob("*.gpg"))


def test_restore_goes_into_a_new_database_only(settings: Settings, dumped: backup.Manifest) -> None:
    live = backup.connection(settings).database
    with pytest.raises(backup.BackupError, match="neue Datenbank"):
        backup.restore(settings, dumped.file, live)
    with pytest.raises(backup.BackupError, match="Kleinbuchstaben"):
        backup.restore(settings, dumped.file, "x; DROP DATABASE gce")
    with pytest.raises(backup.BackupError, match="nicht gefunden"):
        backup.restore(settings, "gce-19990101-000000.dump.gpg", "gce_recovered_test")
    target = "gce_recovered_test"
    _drop(settings, target)
    try:
        tables = backup.restore(settings, dumped.file, target)
        assert tables == dumped.tables
        with pytest.raises(backup.BackupError, match="existiert bereits"):
            backup.restore(settings, dumped.file, target)
    finally:
        _drop(settings, target)


def _fake_backup(settings: Settings, created: datetime) -> str:
    name = f"gce-{created.strftime('%Y%m%d-%H%M%S')}.dump.gpg"
    directory = backup.backup_dir(settings)
    (directory / name).write_bytes(b"x")
    manifest = backup.Manifest(
        file=name,
        created_at=created.isoformat(),
        size_bytes=1,
        sha256="0",
        database="gce",
        alembic_version="v",
        tables={"users": 1},
    )
    backup._write_manifest(directory, manifest)
    return name


def test_prune_keeps_recent_and_minimum(settings: Settings) -> None:
    s = settings.model_copy(update={"backup_keep_days": 7, "backup_keep_min": 3})
    names = [_fake_backup(s, NOW - timedelta(days=d)) for d in (1, 20, 30, 40, 50)]
    removed = backup.prune(s, NOW)
    assert sorted(removed) == sorted(names[3:])  # 2 old ones go; 20 and 30 days stay as minimum
    assert [m.file for m in backup.list_backups(s)] == names[:3]
    (Path(s.backup_dir) / "broken.json").write_text("{", encoding="utf-8")
    (Path(s.backup_dir) / "gce-20200101-000000.dump.gpg").write_bytes(b"")  # no manifest
    assert len(backup.list_backups(s)) == 3


def test_backup_cli_and_schedule(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from zoneinfo import ZoneInfo

    berlin = ZoneInfo("Europe/Berlin")
    # 01:30 UTC = 02:30 Berlin in winter -> today 03:00 Berlin = 02:00 UTC
    assert backup_cli.next_run(datetime(2026, 11, 14, 1, 30, tzinfo=UTC), 3, berlin) == datetime(
        2026, 11, 14, 2, 0, tzinfo=UTC
    )
    # after 03:00 Berlin -> tomorrow
    assert backup_cli.next_run(datetime(2026, 11, 14, 5, 0, tzinfo=UTC), 3, berlin) == datetime(
        2026, 11, 15, 2, 0, tzinfo=UTC
    )

    notes: list[tuple[NotificationLevel, str, str]] = []
    monkeypatch.setattr(backup_cli, "_notify", lambda *a: notes.append(a))
    monkeypatch.setattr(backup_cli, "get_settings", lambda: settings)
    monkeypatch.setattr(backup_cli, "configure_logging", lambda level: None)
    assert backup_cli.main(["run"]) == 0
    assert notes == []
    assert backup_cli.main(["list"]) == 0
    assert "ok" in capsys.readouterr().out
    assert backup_cli.main(["restore-test"]) == 0
    assert backup_cli.main(["restore", "x.dump.gpg", "--into", "gce_x"]) == 2  # no --yes
    assert backup_cli.main(["restore", "x.dump.gpg", "--into", "gce_x", "--yes"]) == 1

    broken = settings.model_copy(update={"backup_passphrase": SecretStr("")})
    monkeypatch.setattr(backup_cli, "get_settings", lambda: broken)
    assert backup_cli.main(["run"]) == 1
    assert notes and notes[0][0] == NotificationLevel.CRITICAL


# --- system checks --------------------------------------------------------------------


def _by_key(report: monitoring.Report) -> dict[str, monitoring.Check]:
    return {c.key: c for c in report.checks}


def test_collect_reports_missing_worker_scheduler_and_backup(
    db: Session, redis_client: Redis, settings: Settings
) -> None:
    s = settings.model_copy(update={"backup_passphrase": SecretStr("")})
    checks = _by_key(monitoring.collect(db, s, redis_client, NOW))
    assert checks["database"].status == "ok" and checks["redis"].status == "ok"
    assert checks["worker"].status == "critical"
    assert checks["scheduler"].status == "critical"
    assert checks["backups"].status == "warn" and "BACKUP_PASSPHRASE" in checks["backups"].detail

    monitoring.beat(redis_client, "scheduler", NOW - timedelta(seconds=30))
    report = monitoring.collect(db, settings, redis_client, NOW)
    checks = _by_key(report)
    assert checks["scheduler"].status == "ok"
    assert checks["backups"].detail == "Noch keine Sicherung vorhanden"
    assert report.status == "critical"  # still no worker

    monitoring.beat(redis_client, "scheduler", NOW - timedelta(minutes=10))
    assert _by_key(monitoring.collect(db, settings, redis_client, NOW))["scheduler"].status == (
        "critical"
    )


def test_backup_check_states(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_backup(settings, NOW - timedelta(hours=2))
    assert monitoring.check_backups(settings, NOW).status == "warn"  # never tested
    rc = backup.RestoreCheck("f", NOW.isoformat(), True, 1.0)
    monkeypatch.setattr(backup, "last_restore_check", lambda s: rc)
    assert monitoring.check_backups(settings, NOW).status == "ok"
    rc.ok, rc.problems = False, ["users: 0 statt 1 Zeilen"]
    check = monitoring.check_backups(settings, NOW)
    assert check.status == "critical" and "users" in check.detail
    assert monitoring.check_backups(settings, NOW + timedelta(hours=40)).status == "critical"


def test_queue_wait_and_failed_agents(db: Session, redis_client: Redis, settings: Settings) -> None:
    Queue("low", connection=redis_client).enqueue("builtins.print", "x")
    assert monitoring.check_queues(redis_client, settings, datetime.now(UTC)).status == "ok"
    later = datetime.now(UTC) + timedelta(seconds=settings.queue_wait_warn_s + 60)
    check = monitoring.check_queues(redis_client, settings, later)
    assert check.status == "warn" and "1 wartend" in check.detail
    much_later = datetime.now(UTC) + timedelta(seconds=5 * settings.queue_wait_warn_s)
    assert monitoring.check_queues(redis_client, settings, much_later).status == "critical"

    now = datetime.now(UTC)
    for i in range(5):
        db.add(
            AgentRun(
                agent_name="clip_production",
                status=AgentRunStatus.FAILED if i < 3 else AgentRunStatus.SUCCEEDED,
                started_at=now - timedelta(hours=1),
                error="ffmpeg kaputt",
            )
        )
    db.add(
        AgentRun(agent_name="x", status=AgentRunStatus.FAILED, started_at=now - timedelta(days=3))
    )
    db.flush()
    check = monitoring.check_agents(db, settings, now)
    assert check.status == "warn"
    assert check.detail.startswith("3 von 5") and "ffmpeg kaputt" in check.detail


def test_http_errors_are_counted_by_the_api(
    api: TestClient, redis_client: Redis, settings: Settings
) -> None:
    app = api.app

    def boom() -> None:
        raise RuntimeError("kaputt")

    app.add_api_route("/api/test-boom", boom)  # type: ignore[attr-defined]
    client = TestClient(app, raise_server_exceptions=False)
    for _ in range(monitoring.HTTP_ERRORS_WARN):
        assert client.get("/api/test-boom").status_code == 500
    assert client.get("/api/health").status_code == 200
    check = monitoring.check_http_errors(redis_client, datetime.now(UTC))
    assert check.status == "warn" and check.value == monitoring.HTTP_ERRORS_WARN


def test_disk_and_load(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    assert monitoring.check_disk(settings).status in ("ok", "warn", "critical")
    monkeypatch.setattr(monitoring, "disk_usage", lambda s: [("Medien", 85.0, 10 * 1024**3)])
    check = monitoring.check_disk(settings)
    assert check.status == "warn" and "85 % belegt" in check.detail
    monkeypatch.setattr(monitoring, "disk_usage", lambda s: [("Medien", 95.0, 1024**3)])
    assert monitoring.check_disk(settings).status == "critical"
    monkeypatch.setattr(monitoring, "disk_usage", lambda s: [])
    assert monitoring.check_disk(settings).status == "unknown"
    monkeypatch.setattr(monitoring, "memory_available_pct", lambda: 5.0)
    assert monitoring.check_load().status == "warn"
    monkeypatch.setattr(monitoring, "memory_available_pct", lambda: None)
    monkeypatch.setattr(monitoring, "load_ratio", lambda: None)
    assert monitoring.check_load().status == "unknown"


def test_failing_check_does_not_hide_the_others(
    db: Session, redis_client: Redis, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*a: Any) -> None:
        raise ValueError("x")

    monkeypatch.setattr(monitoring, "check_worker", broken)
    checks = _by_key(monitoring.collect(db, settings, redis_client, NOW))
    assert checks["worker"].status == "unknown" and "ValueError" in checks["worker"].detail
    assert checks["database"].status == "ok"


# --- scaling criteria -------------------------------------------------------------------


def _samples(n: int, every: timedelta, **values: Any) -> list[dict[str, Any]]:
    base = {"backlog": 0, "wait_s": 0.0, "load": 0.2, "mem_free_pct": 60.0, "disk_pct": 40.0}
    return [{**base, **values, "ts": (NOW - every * (n - 1 - i)).isoformat()} for i in range(n)]


def test_scaling_needs_enough_data(settings: Settings) -> None:
    assert monitoring.scaling_advice([], settings, NOW)[0].key == "no_data"
    short = _samples(30, timedelta(minutes=1), wait_s=99999, load=2.0)
    advice = monitoring.scaling_advice(short, settings, NOW)
    assert advice[0].key == "no_data" and "0,5 h" in advice[0].evidence


def test_scaling_advice_follows_lasting_bottlenecks(settings: Settings) -> None:
    every = timedelta(minutes=5)
    quiet = monitoring.scaling_advice(_samples(60, every), settings, NOW)
    assert [a.key for a in quiet] == ["none"]

    # a single peak is no reason to scale
    peak = _samples(60, every)
    peak[-1].update(wait_s=99999, load=3.0)
    assert [a.key for a in monitoring.scaling_advice(peak, settings, NOW)] == ["none"]

    busy = _samples(60, every, wait_s=settings.queue_wait_warn_s + 1, load=1.5)
    assert [a.key for a in monitoring.scaling_advice(busy, settings, NOW)] == ["render_capacity"]

    waiting = _samples(60, every, wait_s=settings.queue_wait_warn_s + 1, load=0.3)
    advice = monitoring.scaling_advice(waiting, settings, NOW)
    assert [a.key for a in advice] == ["more_workers"] and "--scale worker=2" in advice[0].text

    tight = _samples(60, every, mem_free_pct=5.0, disk_pct=85.0)
    assert [a.key for a in monitoring.scaling_advice(tight, settings, NOW)] == ["memory", "storage"]


# --- alerts and the periodic run ----------------------------------------------------------


def _notes(db: Session) -> list[Notification]:
    return list(db.scalars(select(Notification).order_by(Notification.id)))


def test_alerts_only_on_change(db: Session, redis_client: Redis) -> None:
    def report(status: monitoring.Status) -> monitoring.Report:
        return monitoring.Report(
            NOW.isoformat(), status, [monitoring.Check("disk", "Speicherplatz", status, "85 %")]
        )

    before = len(_notes(db))
    assert monitoring.alert_changes(db, redis_client, report("warn")) == ["disk"]
    assert monitoring.alert_changes(db, redis_client, report("warn")) == []
    assert monitoring.alert_changes(db, redis_client, report("critical")) == ["disk"]
    assert monitoring.alert_changes(db, redis_client, report("unknown")) == []
    assert monitoring.alert_changes(db, redis_client, report("ok")) == ["disk"]
    db.flush()
    new = _notes(db)[before:]
    assert [n.level for n in new] == [
        NotificationLevel.WARNING,
        NotificationLevel.CRITICAL,
        NotificationLevel.INFO,
    ]
    assert new[0].title == "Systemprüfung: Speicherplatz – Warnung"
    assert new[2].title == "Systemprüfung: Speicherplatz wieder in Ordnung"


def test_uptime_kuma_push(settings: Settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ok = monitoring.Report(NOW.isoformat(), "ok", [monitoring.Check("redis", "Redis", "ok", "")])
    assert not monitoring.push_uptime_kuma(settings, ok, client)  # not configured
    s = settings.model_copy(
        update={"uptime_kuma_push_url": SecretStr("https://kuma.example/api/push/tok")}
    )
    assert monitoring.push_uptime_kuma(s, ok, client)
    assert seen[-1].url.params["status"] == "up" and seen[-1].url.params["msg"] == "OK"
    bad = monitoring.Report(
        NOW.isoformat(),
        "critical",
        [monitoring.Check("worker", "Worker", "critical", "Kein Worker")],
    )
    assert monitoring.push_uptime_kuma(s, bad, client)
    assert seen[-1].url.params["status"] == "down"
    assert seen[-1].url.params["msg"] == "Worker: Kein Worker"

    failing = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert not monitoring.push_uptime_kuma(s, ok, failing)


def test_run_stores_samples_and_notifies(
    db: Session, redis_client: Redis, settings: Settings
) -> None:
    before = len(_notes(db))
    report = monitoring.run(db, settings, redis_client, NOW)
    assert report.status == "critical"
    assert len(monitoring.load_samples(redis_client, NOW)) == 1
    titles = [n.title for n in _notes(db)[before:]]
    assert "Systemprüfung: Worker – kritisch" in titles
    monitoring.run(db, settings, redis_client, NOW + timedelta(minutes=1))
    assert len(_notes(db)) == before + len(titles)  # nothing new: same state
    assert len(monitoring.load_samples(redis_client, NOW + timedelta(minutes=1))) == 2


def test_scheduler_monitor_beats_and_checks(
    redis_client: Redis, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.scheduler as sched

    runs: list[int] = []
    monkeypatch.setattr(monitoring, "run", lambda *a, **k: runs.append(1))
    monkeypatch.setattr(sched, "get_redis", lambda: redis_client)
    reports: list[int] = []  # the weekly report would commit a real mail row
    monkeypatch.setattr("services.weekly_report.maybe_send", lambda *a, **k: reports.append(1))
    m = Monitor(interval_s=60)
    assert m.tick(1000.0, settings) is True
    assert m.tick(1030.0, settings) is False
    assert m.tick(1061.0, settings) is True
    assert runs == [1, 1]
    assert reports == [1]  # watchdog block (15 min) ran once
    assert monitoring.heartbeat_age(redis_client, "scheduler", datetime.now(UTC)) is not None


def test_system_status_api(
    api: TestClient,
    make_user: Callable[..., User],
    settings: Settings,
    dumped: backup.Manifest,
) -> None:
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    assert api.get("/api/system/status").status_code == 401
    make_user("viewer@example.com", UserRole.VIEWER)
    login(api, "viewer@example.com")
    r = api.get("/api/system/status")
    assert r.status_code == 200, r.text
    body = r.json()
    keys = {c["key"] for c in body["checks"]}
    assert {"database", "redis", "worker", "scheduler", "queues", "backups", "disk"} <= keys
    assert body["backup"]["configured"] is True
    assert body["backup"]["latest"]["file"] == dumped.file
    assert body["backup"]["restore_check"] is None
    assert body["scaling"][0]["key"] == "no_data"
    assert PASS not in json.dumps(body)


def test_backup_counts_match_the_dump_snapshot(engine: Any, settings: Settings) -> None:
    """Counts are taken in the dump's snapshot; later writes do not leak into either."""
    conn = backup.connection(settings)
    with conn.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS backup_probe (id int)")
        db.execute("INSERT INTO backup_probe VALUES (1)")
        db.commit()
    try:
        manifest = backup.create_backup(settings, NOW)
        with conn.connect() as db:
            db.execute("INSERT INTO backup_probe VALUES (2)")
            db.commit()
        assert manifest.tables["backup_probe"] == 1
        assert backup.restore_test(settings, manifest).ok
    finally:
        with psycopg.connect(
            host=conn.host,
            port=conn.port,
            user=conn.user,
            dbname=conn.database,
            password=conn.password or None,
            autocommit=True,
        ) as db:
            db.execute("DROP TABLE IF EXISTS backup_probe")


# --- key rotation for stored platform tokens -------------------------------------------


def test_credential_key_rotation(db: Session) -> None:
    from app.rotate_credentials import rotate_all
    from core import crypto
    from models import ChannelCredential
    from tests.factories import build_chain

    base = get_settings()
    old = base.model_copy(update={"credentials_encryption_key": SecretStr("old-key-" + "x" * 32)})
    new = base.model_copy(
        update={
            "credentials_encryption_key": SecretStr("new-key-" + "y" * 32),
            "credentials_encryption_key_old": SecretStr("unused-key, old-key-" + "x" * 32),
        }
    )
    new_only = base.model_copy(
        update={"credentials_encryption_key": SecretStr("new-key-" + "y" * 32)}
    )
    channel = build_chain(db).channel
    cred = ChannelCredential(
        channel_id=channel.id,
        provider="youtube",
        access_token_enc=crypto.encrypt(old, "access-a"),
        refresh_token_enc=crypto.encrypt(old, "refresh-a"),
    )
    db.add(cred)
    db.flush()
    assert crypto.decrypt(new, cred.access_token_enc or "") == "access-a"  # old key still accepted
    with pytest.raises(crypto.CredentialError):
        crypto.decrypt(new_only, cred.access_token_enc or "")

    assert rotate_all(db, new) == (2, 0)
    assert crypto.decrypt(new_only, cred.access_token_enc or "") == "access-a"
    assert crypto.decrypt(new_only, cred.refresh_token_enc or "") == "refresh-a"

    stranger = base.model_copy(update={"credentials_encryption_key": SecretStr("z" * 40)})
    cred.access_token_enc = crypto.encrypt(stranger, "lost")
    assert rotate_all(db, new)[1] == 1


def test_idle_worker_between_heartbeats_counts_as_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    """An idle RQ worker renews its heartbeat only every ~405 s; that is not an outage."""

    class FakeWorker:
        def __init__(self, age_s: float) -> None:
            self.last_heartbeat = datetime.now(UTC) - timedelta(seconds=age_s)

        def get_state(self) -> str:
            return "idle"

    now = datetime.now(UTC)
    monkeypatch.setattr(Worker, "all", staticmethod(lambda **_: [FakeWorker(300)]))
    assert monitoring.check_worker(None, now).status == "ok"  # type: ignore[arg-type]

    monkeypatch.setattr(Worker, "all", staticmethod(lambda **_: [FakeWorker(900)]))
    assert monitoring.check_worker(None, now).status == "critical"  # type: ignore[arg-type]
