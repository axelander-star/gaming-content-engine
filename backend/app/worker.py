"""Queue worker entry point. Run with ``python -m app.worker``.

Refuses to start while the emergency stop is active (environment or dashboard).
Each agent job re-checks all gates itself (see ``services.gates``).
"""

from __future__ import annotations

import logging
import sys

from rq import Worker

from core.config import get_settings
from core.logging import configure_logging
from database.session import get_engine, get_sessionmaker
from services.controls import effective_controls
from services.queue import QUEUE_NAMES, get_queue, get_redis

log = logging.getLogger("worker")


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    with get_sessionmaker()() as session:
        stop = effective_controls(session, settings).emergency_stop
    if stop:
        log.error("Emergency stop is active - worker not started")
        return 1
    # Jobs run in forked children; they must not share pooled DB connections.
    get_engine().dispose()
    redis = get_redis()
    queues = [get_queue(name, redis) for name in QUEUE_NAMES]
    log.info("worker starting", extra={"queues": list(QUEUE_NAMES)})
    Worker(queues, connection=redis).work(with_scheduler=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
