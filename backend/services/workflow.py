"""Status changes for material and variants, with audit logging and retry.

This is the only place that may change ``GameplayFile.status`` or
``Variant.status``. Callers commit the session.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy.orm import Session

from core.enums import MaterialStatus, VideoStatus
from core.states import InvalidTransitionError, assert_transition
from models.access import AuditLog
from models.production import GameplayFile, Variant

WorkflowEntity = GameplayFile | Variant


def _status_enum(entity: WorkflowEntity) -> type[StrEnum]:
    return MaterialStatus if isinstance(entity, GameplayFile) else VideoStatus


def _audit(
    session: Session,
    entity: WorkflowEntity,
    action: str,
    before: str,
    after: str,
    actor: str,
    message: str | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_agent=actor,
            action=action,
            entity_type=entity.__tablename__,
            entity_id=entity.id,
            before={"status": before},
            after={"status": after},
            message=message,
        )
    )


def transition(session: Session, entity: WorkflowEntity, target: StrEnum, actor: str) -> None:
    """Move ``entity`` to ``target`` if the workflow allows it; log the change."""
    current = entity.status
    if not isinstance(target, _status_enum(entity)):
        raise TypeError(f"{target!r} is not a valid status for {entity.__tablename__}")
    if target.value == "FAILED":
        raise InvalidTransitionError(current, target)  # use mark_failed()
    assert_transition(current, target)
    entity.status = target  # type: ignore[assignment]
    _audit(session, entity, "status_change", current.value, target.value, actor)


def record_entry(session: Session, entity: WorkflowEntity, actor: str) -> None:
    """Log the first status of a new entity (it enters the workflow with it)."""
    _audit(session, entity, "status_change", "NEW", entity.status.value, actor)


def mark_failed(
    session: Session, entity: WorkflowEntity, step: str, error: str, actor: str
) -> None:
    """Record an error and move the entity to FAILED, remembering where it failed."""
    current = entity.status
    failed = _status_enum(entity)("FAILED")
    assert_transition(current, failed)
    entity.last_good_status = current.value
    entity.failed_step = step
    entity.error_message = error[:4000]
    entity.status = failed  # type: ignore[assignment]
    _audit(session, entity, "failed", current.value, failed.value, actor, message=error[:500])


def retry(session: Session, entity: WorkflowEntity, actor: str, max_retries: int = 3) -> None:
    """Return a FAILED entity to the status it failed in so it can be reprocessed."""
    if entity.status.value != "FAILED" or not entity.last_good_status:
        raise InvalidTransitionError(entity.status, entity.status)
    if entity.retry_count >= max_retries:
        raise RuntimeError(
            f"{entity.__tablename__}#{entity.id} reached max retries ({max_retries})"
        )
    target = _status_enum(entity)(entity.last_good_status)
    entity.retry_count += 1
    entity.status = target  # type: ignore[assignment]
    entity.error_message = None
    entity.failed_step = None
    _audit(session, entity, "retry", "FAILED", target.value, actor)
