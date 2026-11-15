"""Time-based triggers. Run with ``python -m app.scheduler``.

Enqueues a master orchestrator tick every ``MASTER_TICK_SECONDS`` and a budget
check every ``BUDGET_CHECK_SECONDS``. While the emergency stop is active it
enqueues nothing. The jobs themselves re-check all gates before running.
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from dataclasses import dataclass, field
from types import FrameType

from core.config import Settings, get_settings
from core.logging import configure_logging
from database.session import get_sessionmaker
from services import monitoring, uploads
from services.controls import effective_controls
from services.orchestrator import submit
from services.queue import get_redis

log = logging.getLogger("scheduler")

SWEEP_AGENTS = {"rights_license", "material_scout", "analytics"}


@dataclass
class Schedule:
    """Agent name -> interval in seconds, plus when each one last fired."""

    intervals: dict[str, int]
    last_run: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, settings: Settings) -> Schedule:
        return cls(
            {
                "master": settings.master_tick_seconds,
                "budget_cost": settings.budget_check_seconds,
                "trend_research": settings.trend_research_seconds,
                "game_intelligence": settings.game_intelligence_seconds,
                "rights_license": settings.rights_sweep_seconds,
                "material_scout": settings.material_needs_seconds,
                "analytics": settings.analytics_seconds,
                "learning": settings.learning_seconds,
                "research": settings.research_seconds,
                "idea_lab": settings.ideas_seconds,
            }
        )

    def due(self, now: float) -> list[str]:
        return [
            name
            for name, interval in self.intervals.items()
            if now - self.last_run.get(name, float("-inf")) >= interval
        ]


def tick(schedule: Schedule, now: float, settings: Settings) -> list[str]:
    """Enqueue every due agent; returns the names that were enqueued."""
    due = schedule.due(now)
    if not due:
        return []
    with get_sessionmaker()() as session:
        if effective_controls(session, settings).emergency_stop:
            log.warning("emergency stop active - nothing scheduled")
            return []
    for name in due:
        # Stage agents run here only as sweeps; per-entity jobs come from the master.
        submit(name, {"sweep": True} if name in SWEEP_AGENTS else {})
        schedule.last_run[name] = now
    log.info("scheduled", extra={"agents": due})
    return due


@dataclass
class Monitor:
    """Heartbeat for the monitoring plus the periodic system check (Phase 15).

    Runs in the scheduler process itself, not through the queue: a stuck worker
    or a full queue is exactly what it has to notice.
    """

    interval_s: int
    beat_every_s: float = 15.0
    last_check: float = float("-inf")
    last_beat: float = float("-inf")

    def tick(self, now: float, settings: Settings) -> bool:
        redis = get_redis()
        if now - self.last_beat >= self.beat_every_s:
            monitoring.beat(redis, "scheduler")
            self.last_beat = now
        if now - self.last_check < self.interval_s:
            return False
        self.last_check = now
        with get_sessionmaker()() as session:
            monitoring.run(session, settings, redis)
        with get_sessionmaker()() as session, session.begin():
            uploads.purge_expired(session, settings)
        return True


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    schedule = Schedule.from_settings(settings)
    monitor = Monitor(settings.monitor_seconds)
    running = True

    def _stop(signum: int, frame: FrameType | None) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("scheduler starting", extra={"intervals": schedule.intervals})
    while running:
        try:
            tick(schedule, time.monotonic(), settings)
        except Exception:  # keep the scheduler alive, retry next loop
            log.exception("scheduler tick failed")
        try:
            monitor.tick(time.monotonic(), settings)
        except Exception:  # monitoring must never stop the scheduler
            log.exception("system check failed")
        time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
