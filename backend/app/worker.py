"""Queue worker entry point. Run with ``python -m app.worker``.

Refuses to start while the emergency stop is active.
"""

from __future__ import annotations

import logging
import sys

from rq import Worker

from core.config import get_settings
from core.logging import configure_logging
from services.queue import QUEUE_NAMES, get_queue, get_redis

log = logging.getLogger("worker")


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.emergency_stop:
        log.error("EMERGENCY_STOP is active - worker not started")
        return 1
    redis = get_redis()
    queues = [get_queue(name, redis) for name in QUEUE_NAMES]
    log.info("worker starting", extra={"queues": list(QUEUE_NAMES)})
    Worker(queues, connection=redis).work(with_scheduler=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
