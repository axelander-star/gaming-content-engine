"""Queue jobs. Agent jobs live in ``services.orchestrator.run_agent_job``."""

from __future__ import annotations

from datetime import UTC, datetime

from database.session import get_sessionmaker
from services.health import check_database


def heartbeat() -> dict[str, str | bool]:
    """Verify that a worker can execute jobs and reach the database."""
    with get_sessionmaker()() as session:
        db_ok = check_database(session)
    return {"ok": db_ok, "at": datetime.now(UTC).isoformat()}
