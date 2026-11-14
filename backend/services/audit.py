"""Helper to write audit log entries (PROJECT_SPEC section 15)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from models.access import AuditLog


def record(
    session: Session,
    action: str,
    *,
    user_id: int | None = None,
    agent: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    message: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_user_id=user_id,
        actor_agent=agent,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        message=message,
    )
    session.add(entry)
    return entry
