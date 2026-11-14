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
from services.controls import effective_controls
from services.orchestrator import submit

log = logging.getLogger("scheduler")


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
        submit(name, {})
        schedule.last_run[name] = now
    log.info("scheduled", extra={"agents": due})
    return due


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    schedule = Schedule.from_settings(settings)
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
        time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
