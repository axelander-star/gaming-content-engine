"""System checks, alerts and scaling criteria (PROJECT_SPEC sections 9, 14 and 15, Phase 15).

:func:`collect` checks every component (database, Redis, worker, scheduler,
queues, agent errors, API errors, backups, disk, load, memory) and returns a
report with one status per check: ``ok``, ``warn``, ``critical`` or ``unknown``.

:func:`run` is called by the scheduler every ``MONITOR_SECONDS``. It

* raises a dashboard notification when a check gets worse and when it recovers
  (only on a change, so a lasting problem is reported once),
* stores a sample of the load figures for the scaling criteria,
* pushes the overall state to an Uptime Kuma push monitor if one is configured.
  Uptime Kuma then alerts through its own channels (e-mail, Telegram, ...) and
  also notices when the pushes stop, i.e. when the scheduler itself is down.

Scaling (section 14, stage 8) is only recommended when the samples of the last
hours show a lasting bottleneck, never because of a single peak.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
from redis import Redis
from redis.exceptions import RedisError
from rq import Worker
from rq.job import Job
from rq.registry import FailedJobRegistry
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import AgentRunStatus, NotificationLevel
from models.access import Notification
from models.control import AgentRun
from services import backup
from services.health import check_database, check_redis
from services.queue import QUEUE_NAMES, get_queue

log = logging.getLogger(__name__)

Status = Literal["ok", "warn", "critical", "unknown"]
_RANK: dict[str, int] = {"unknown": 0, "ok": 1, "warn": 2, "critical": 3}

HEARTBEAT_KEY = "gce:heartbeat:{}"
STATE_KEY = "gce:monitor:state"
SAMPLES_KEY = "gce:monitor:samples"
HTTP_ERRORS_KEY = "gce:http5xx:{}"
HEARTBEAT_STALE_S = 180
WORKER_STALE_S = 120
SAMPLE_KEEP = timedelta(hours=24)
SCALING_WINDOW = timedelta(hours=6)
SCALING_MIN_SPAN = timedelta(hours=3)
SCALING_SHARE = 0.75  # share of samples that must show the bottleneck
LOAD_BUSY = 0.9  # 1-minute load per CPU core
MEMORY_TIGHT_PCT = 15.0
HTTP_ERRORS_WARN = 10  # server errors in 24 h


@dataclass
class Check:
    key: str
    label: str
    status: Status
    detail: str
    value: float | None = None


@dataclass
class Advice:
    key: str
    text: str
    evidence: str


@dataclass
class Report:
    checked_at: str
    status: Status
    checks: list[Check]
    scaling: list[Advice] = field(default_factory=list)
    samples: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def worst(statuses: list[Status]) -> Status:
    return max(statuses, key=lambda s: _RANK[s], default="unknown")


# --- heartbeats and error counters ----------------------------------------------


def beat(redis: Redis, component: str, now: datetime | None = None) -> None:
    """Record that ``component`` (scheduler, backup) is alive."""
    now = now or datetime.now(UTC)
    redis.set(HEARTBEAT_KEY.format(component), now.timestamp(), ex=7 * 24 * 3600)


def heartbeat_age(redis: Redis, component: str, now: datetime) -> float | None:
    raw = redis.get(HEARTBEAT_KEY.format(component))
    if raw is None:
        return None
    return max(0.0, now.timestamp() - float(raw))


def count_http_error(redis: Redis, now: datetime | None = None) -> None:
    """Count one server error (5xx) in the current hour bucket."""
    now = now or datetime.now(UTC)
    key = HTTP_ERRORS_KEY.format(now.strftime("%Y%m%d%H"))
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, 48 * 3600)
    pipe.execute()


def http_errors_24h(redis: Redis, now: datetime) -> int:
    keys = [
        HTTP_ERRORS_KEY.format((now - timedelta(hours=h)).strftime("%Y%m%d%H")) for h in range(24)
    ]
    return sum(int(v) for v in redis.mget(keys) if v is not None)


# --- single checks ------------------------------------------------------------------


def _age_text(seconds: float) -> str:
    if seconds < 120:
        return f"{int(seconds)} s"
    if seconds < 7200:
        return f"{int(seconds // 60)} min"
    return f"{seconds / 3600:.1f} h"


def check_worker(redis: Redis, now: datetime) -> Check:
    workers = Worker.all(connection=redis)
    alive = [
        w
        for w in workers
        if w.last_heartbeat
        and (now - w.last_heartbeat.replace(tzinfo=w.last_heartbeat.tzinfo or UTC)).total_seconds()
        < WORKER_STALE_S
    ]
    if not alive:
        return Check(
            "worker", "Worker", "critical", "Kein Worker aktiv – Aufträge bleiben liegen", 0
        )
    busy = sum(1 for w in alive if w.get_state() == "busy")
    return Check("worker", "Worker", "ok", f"{len(alive)} aktiv, {busy} beschäftigt", len(alive))


def check_scheduler(redis: Redis, now: datetime) -> Check:
    age = heartbeat_age(redis, "scheduler", now)
    if age is None:
        return Check("scheduler", "Zeitsteuerung", "critical", "Noch kein Lebenszeichen")
    if age > HEARTBEAT_STALE_S:
        return Check(
            "scheduler",
            "Zeitsteuerung",
            "critical",
            f"Letztes Lebenszeichen vor {_age_text(age)}",
            age,
        )
    return Check("scheduler", "Zeitsteuerung", "ok", f"Lebenszeichen vor {_age_text(age)}", age)


def queue_figures(redis: Redis, now: datetime) -> tuple[int, float, int]:
    """Waiting jobs over all queues, longest wait in seconds, failed jobs."""
    backlog, longest, failed = 0, 0.0, 0
    for name in QUEUE_NAMES:
        q = get_queue(name, redis)
        backlog += q.count
        failed += FailedJobRegistry(queue=q).count
        ids = q.get_job_ids(0, 1)
        if ids:
            job = Job.fetch(ids[0], connection=redis)
            if job.enqueued_at:
                enq = job.enqueued_at.replace(tzinfo=job.enqueued_at.tzinfo or UTC)
                longest = max(longest, (now - enq).total_seconds())
    return backlog, longest, failed


def check_queues(redis: Redis, settings: Settings, now: datetime) -> Check:
    backlog, longest, failed = queue_figures(redis, now)
    detail = f"{backlog} wartend, längste Wartezeit {_age_text(longest)}, {failed} fehlgeschlagen"
    status: Status = "ok"
    if longest > 4 * settings.queue_wait_warn_s:
        status = "critical"
    elif longest > settings.queue_wait_warn_s:
        status = "warn"
    return Check("queues", "Warteschlangen", status, detail, longest)


def check_agents(session: Session, settings: Settings, now: datetime) -> Check:
    since = now - timedelta(hours=24)
    rows = dict(
        session.execute(
            select(AgentRun.status, func.count())
            .where(AgentRun.started_at >= since)
            .group_by(AgentRun.status)
        ).all()
    )
    failed = int(rows.get(AgentRunStatus.FAILED, 0))
    total = int(sum(rows.values()))
    ratio = failed / total if total else 0.0
    status: Status = "warn" if failed >= 3 and ratio >= settings.agent_error_warn_ratio else "ok"
    detail = f"{failed} von {total} Agentenläufen in 24 h fehlgeschlagen"
    if failed:
        last = session.execute(
            select(AgentRun.agent_name, AgentRun.error)
            .where(AgentRun.started_at >= since, AgentRun.status == AgentRunStatus.FAILED)
            .order_by(AgentRun.started_at.desc())
            .limit(1)
        ).first()
        if last:
            detail += f"; zuletzt {last[0]}: {(last[1] or '')[:160]}"
    return Check("agents", "Agentenfehler", status, detail, round(ratio, 3))


def check_http_errors(redis: Redis, now: datetime) -> Check:
    n = http_errors_24h(redis, now)
    status: Status = "warn" if n >= HTTP_ERRORS_WARN else "ok"
    return Check("api_errors", "Serverfehler der API", status, f"{n} in 24 h", n)


def check_backups(settings: Settings, now: datetime) -> Check:
    st = backup.status(settings, now)
    label = "Datensicherung"
    if not st.configured:
        return Check("backups", label, "warn", "BACKUP_PASSPHRASE fehlt – es wird nichts gesichert")
    if st.latest is None or st.age_hours is None:
        return Check("backups", label, "warn", "Noch keine Sicherung vorhanden")
    rc = st.restore_check
    detail = f"Letzte Sicherung vor {_age_text(st.age_hours * 3600)}, {st.count} vorhanden"
    if st.age_hours > settings.backup_max_age_hours:
        return Check("backups", label, "critical", detail + " – zu alt", st.age_hours)
    if rc is None:
        return Check(
            "backups", label, "warn", detail + "; Wiederherstellung nie getestet", st.age_hours
        )
    if not rc.ok:
        problem = rc.problems[0] if rc.problems else "unbekannt"
        return Check(
            "backups",
            label,
            "critical",
            f"{detail}; Wiederherstellungstest fehlgeschlagen: {problem}",
            st.age_hours,
        )
    return Check("backups", label, "ok", detail + "; Wiederherstellung getestet", st.age_hours)


def disk_usage(settings: Settings) -> list[tuple[str, float, int]]:
    """(label, used %, free bytes) per file system holding media or backups."""
    seen: set[int] = set()
    result = []
    for label, raw in (("Medien", settings.media_root), ("Sicherungen", settings.backup_dir)):
        path = Path(raw)
        while not path.exists() and path != path.parent:
            path = path.parent
        try:
            dev = path.stat().st_dev
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        if dev in seen:
            continue
        seen.add(dev)
        result.append((label, usage.used / usage.total * 100 if usage.total else 0.0, usage.free))
    return result


def check_disk(settings: Settings) -> Check:
    rows = disk_usage(settings)
    if not rows:
        return Check("disk", "Speicherplatz", "unknown", "Nicht messbar")
    pct = max(p for _, p, _ in rows)
    status: Status = "ok"
    if pct >= settings.disk_critical_pct:
        status = "critical"
    elif pct >= settings.disk_warn_pct:
        status = "warn"
    detail = ", ".join(
        f"{label} {p:.0f} % belegt ({free / 1024**3:.1f} GB frei)" for label, p, free in rows
    )
    return Check("disk", "Speicherplatz", status, detail, round(pct, 1))


def load_ratio() -> float | None:
    try:
        return os.getloadavg()[0] / (os.cpu_count() or 1)
    except OSError:
        return None


def memory_available_pct() -> float | None:
    try:
        info = Path("/proc/meminfo").read_text(encoding="ascii").splitlines()
    except OSError:
        return None
    values = {}
    for line in info:
        name, _, rest = line.partition(":")
        parts = rest.split()
        if parts:
            values[name] = int(parts[0])
    total, avail = values.get("MemTotal"), values.get("MemAvailable")
    if not total or avail is None:
        return None
    return avail / total * 100


def check_load() -> Check:
    ratio = load_ratio()
    mem = memory_available_pct()
    if ratio is None and mem is None:
        return Check("load", "Auslastung", "unknown", "Nicht messbar")
    parts = []
    status: Status = "ok"
    if ratio is not None:
        parts.append(f"CPU-Last {ratio * 100:.0f} % je Kern ({os.cpu_count()} Kerne)")
    if mem is not None:
        parts.append(f"{mem:.0f} % Arbeitsspeicher frei")
        if mem < MEMORY_TIGHT_PCT / 2:
            status = "warn"
    return Check("load", "Auslastung", status, ", ".join(parts), ratio)


# --- report -------------------------------------------------------------------------


def _safe(key: str, label: str, fn: Any, *args: Any) -> Check:
    try:
        result: Check = fn(*args)
        return result
    except Exception as exc:  # a failing check must not hide the others
        log.warning("monitor check failed", extra={"check": key}, exc_info=True)
        return Check(key, label, "unknown", f"Prüfung fehlgeschlagen: {type(exc).__name__}")


def collect(
    session: Session, settings: Settings, redis: Redis, now: datetime | None = None
) -> Report:
    now = now or datetime.now(UTC)
    db_ok = check_database(session)
    redis_ok = check_redis(redis)
    checks = [
        Check(
            "database",
            "Datenbank",
            "ok" if db_ok else "critical",
            "erreichbar" if db_ok else "nicht erreichbar",
        ),
        Check(
            "redis",
            "Redis",
            "ok" if redis_ok else "critical",
            "erreichbar" if redis_ok else "nicht erreichbar",
        ),
    ]
    if redis_ok:
        checks += [
            _safe("worker", "Worker", check_worker, redis, now),
            _safe("scheduler", "Zeitsteuerung", check_scheduler, redis, now),
            _safe("queues", "Warteschlangen", check_queues, redis, settings, now),
            _safe("api_errors", "Serverfehler der API", check_http_errors, redis, now),
        ]
    if db_ok:
        checks.append(_safe("agents", "Agentenfehler", check_agents, session, settings, now))
    checks += [
        _safe("backups", "Datensicherung", check_backups, settings, now),
        _safe("disk", "Speicherplatz", check_disk, settings),
        _safe("load", "Auslastung", check_load),
    ]
    samples = load_samples(redis, now) if redis_ok else []
    return Report(
        checked_at=now.isoformat(),
        status=worst([c.status for c in checks]),
        checks=checks,
        scaling=scaling_advice(samples, settings, now),
        samples=samples,
    )


# --- samples and scaling criteria ---------------------------------------------------------


def take_sample(redis: Redis, settings: Settings, now: datetime) -> dict[str, Any]:
    backlog, longest, _ = queue_figures(redis, now)
    disks = disk_usage(settings)
    return {
        "ts": now.isoformat(),
        "backlog": backlog,
        "wait_s": round(longest, 1),
        "load": None if (r := load_ratio()) is None else round(r, 3),
        "mem_free_pct": None if (m := memory_available_pct()) is None else round(m, 1),
        "disk_pct": round(max((p for _, p, _ in disks), default=0.0), 1),
    }


def store_sample(redis: Redis, sample: dict[str, Any]) -> None:
    pipe = redis.pipeline()
    pipe.rpush(SAMPLES_KEY, json.dumps(sample))
    pipe.ltrim(SAMPLES_KEY, -3000, -1)
    pipe.execute()


def load_samples(redis: Redis, now: datetime) -> list[dict[str, Any]]:
    cutoff = now - SAMPLE_KEEP
    result = []
    for raw in redis.lrange(SAMPLES_KEY, 0, -1):
        try:
            sample = json.loads(raw)
            if datetime.fromisoformat(sample["ts"]) >= cutoff:
                result.append(sample)
        except (ValueError, KeyError, TypeError):
            continue
    return result


def _share(samples: list[dict[str, Any]], pred: Any) -> float:
    usable = [s for s in samples if pred(s) is not None]
    if not usable:
        return 0.0
    return sum(1 for s in usable if pred(s)) / len(usable)


def scaling_advice(
    samples: list[dict[str, Any]], settings: Settings, now: datetime
) -> list[Advice]:
    """Scale only when the last hours show a lasting bottleneck (section 14, stage 8)."""
    window = [s for s in samples if datetime.fromisoformat(s["ts"]) >= now - SCALING_WINDOW]
    if len(window) < 2:
        return [Advice("no_data", "Noch zu wenige Messwerte für eine Skalierungsempfehlung", "")]
    span = datetime.fromisoformat(window[-1]["ts"]) - datetime.fromisoformat(window[0]["ts"])
    if span < SCALING_MIN_SPAN:
        hours = span.total_seconds() / 3600
        return [
            Advice(
                "no_data",
                "Noch zu wenige Messwerte für eine Skalierungsempfehlung",
                f"{len(window)} Messwerte über {f'{hours:.1f}'.replace('.', ',')} h, "
                f"nötig sind mindestens {SCALING_MIN_SPAN.total_seconds() / 3600:.0f} h",
            )
        ]
    hours = SCALING_WINDOW.total_seconds() / 3600
    queue_share = _share(window, lambda s: s["wait_s"] > settings.queue_wait_warn_s)
    cpu_share = _share(window, lambda s: None if s.get("load") is None else s["load"] > LOAD_BUSY)
    mem_share = _share(
        window,
        lambda s: None if s.get("mem_free_pct") is None else s["mem_free_pct"] < MEMORY_TIGHT_PCT,
    )
    disk_now = window[-1].get("disk_pct") or 0.0
    advice = []
    if queue_share >= SCALING_SHARE and cpu_share >= SCALING_SHARE:
        advice.append(
            Advice(
                "render_capacity",
                "Mehr Renderkapazität: größerer Server oder ein zweiter Render-Server",
                f"Aufträge warteten in {queue_share:.0%} und die CPU war in {cpu_share:.0%} "
                f"der Messungen der letzten {hours:.0f} h ausgelastet",
            )
        )
    elif queue_share >= SCALING_SHARE:
        advice.append(
            Advice(
                "more_workers",
                "Einen weiteren Worker starten (docker compose up -d --scale worker=2) "
                "und ggf. „Parallele Render-Jobs“ erhöhen – die CPU hat noch Reserven",
                f"Aufträge warteten in {queue_share:.0%} der Messungen der letzten {hours:.0f} h, "
                f"CPU nur in {cpu_share:.0%} ausgelastet",
            )
        )
    if mem_share >= SCALING_SHARE:
        advice.append(
            Advice(
                "memory",
                "Mehr Arbeitsspeicher",
                f"Weniger als {MEMORY_TIGHT_PCT:.0f} % frei in {mem_share:.0%} der Messungen",
            )
        )
    if disk_now >= settings.disk_warn_pct:
        advice.append(
            Advice(
                "storage",
                "Speicher erweitern oder fertige Medien nach Cloudflare R2 auslagern",
                f"{disk_now:.0f} % belegt",
            )
        )
    if not advice:
        advice.append(
            Advice(
                "none",
                "Keine Skalierung nötig",
                f"Kein dauerhafter Engpass in {len(window)} Messungen der letzten {hours:.0f} h",
            )
        )
    return advice


# --- the periodic run --------------------------------------------------------------------------


_LEVEL = {"warn": NotificationLevel.WARNING, "critical": NotificationLevel.CRITICAL}
_WORD = {"warn": "Warnung", "critical": "kritisch"}


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


def alert_changes(session: Session, redis: Redis, report: Report) -> list[str]:
    """Notify on every check that got worse or recovered since the last run."""
    try:
        raw: dict[Any, Any] = redis.hgetall(STATE_KEY)
        previous = {_text(k): _text(v) for k, v in raw.items()}
    except RedisError:
        previous = {}
    changed = []
    for c in report.checks:
        before = previous.get(c.key)
        if c.status in _LEVEL and before != c.status:
            session.add(
                Notification(
                    level=_LEVEL[c.status],
                    title=f"Systemprüfung: {c.label} – {_WORD[c.status]}"[:200],
                    body=c.detail[:2000],
                )
            )
            changed.append(c.key)
        elif c.status == "ok" and before in _LEVEL:
            session.add(
                Notification(
                    level=NotificationLevel.INFO,
                    title=f"Systemprüfung: {c.label} wieder in Ordnung"[:200],
                    body=c.detail[:2000],
                )
            )
            changed.append(c.key)
    try:
        pipe = redis.pipeline()
        for c in report.checks:
            if c.status != "unknown":
                pipe.hset(STATE_KEY, c.key, c.status)
        pipe.execute()
    except RedisError:
        log.warning("could not store monitor state", exc_info=True)
    return changed


def push_uptime_kuma(
    settings: Settings, report: Report, client: httpx.Client | None = None
) -> bool:
    """Report the overall state to an Uptime Kuma push monitor (if configured)."""
    url = settings.uptime_kuma_push_url.get_secret_value()
    if not url:
        return False
    problems = [f"{c.label}: {c.detail}" for c in report.checks if c.status == "critical"]
    params = {
        "status": "down" if problems else "up",
        "msg": ("; ".join(problems) if problems else "OK")[:250],
        "ping": "",
    }
    own = client is None
    http = client or httpx.Client(timeout=settings.http_timeout_s)
    try:
        http.get(url, params=params).raise_for_status()
        return True
    except httpx.HTTPError as exc:
        # Never log the URL: it contains the push token.
        log.warning("uptime kuma push failed", extra={"error": type(exc).__name__})
        return False
    finally:
        if own:
            http.close()


def run(
    session: Session,
    settings: Settings,
    redis: Redis,
    now: datetime | None = None,
    client: httpx.Client | None = None,
) -> Report:
    now = now or datetime.now(UTC)
    try:
        store_sample(redis, take_sample(redis, settings, now))
    except RedisError:
        log.warning("could not store monitor sample", exc_info=True)
    report = collect(session, settings, redis, now)
    changed = alert_changes(session, redis, report)
    session.commit()
    push_uptime_kuma(settings, report, client)
    log.log(
        logging.WARNING if report.status in ("warn", "critical") else logging.INFO,
        "system check",
        extra={
            "status": report.status,
            "changed": changed,
            "problems": [c.key for c in report.checks if c.status in ("warn", "critical")],
        },
    )
    return report
