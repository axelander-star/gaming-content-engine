"""Workflow service: transitions, audit log, failure and retry."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import MaterialStatus, VideoStatus
from core.states import InvalidTransitionError
from models import AuditLog
from services import workflow
from tests.factories import build_chain

pytestmark = pytest.mark.integration


def test_transition_writes_audit_log(db: Session) -> None:
    chain = build_chain(db)
    workflow.transition(db, chain.variant, VideoStatus.EDITING, actor="test")
    db.flush()
    log = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_type == "variants", AuditLog.entity_id == chain.variant.id
        )
    ).one()
    assert log.before == {"status": "SCENE_SELECTED"}
    assert log.after == {"status": "EDITING"}
    assert log.actor_agent == "test"


def test_invalid_transition_leaves_status_unchanged(db: Session) -> None:
    chain = build_chain(db)
    with pytest.raises(InvalidTransitionError):
        workflow.transition(db, chain.variant, VideoStatus.PUBLISHED, actor="test")
    assert chain.variant.status == VideoStatus.SCENE_SELECTED


def test_wrong_status_type_rejected(db: Session) -> None:
    chain = build_chain(db)
    with pytest.raises(TypeError):
        workflow.transition(db, chain.variant, MaterialStatus.ANALYZED, actor="test")


def test_material_cannot_skip_rights(db: Session) -> None:
    chain = build_chain(db)
    gf = chain.gameplay_file
    with pytest.raises(InvalidTransitionError):
        workflow.transition(db, gf, MaterialStatus.ANALYZED, actor="test")
    workflow.transition(db, gf, MaterialStatus.RIGHTS_PENDING, actor="rights")
    workflow.transition(db, gf, MaterialStatus.RIGHTS_APPROVED, actor="rights")
    workflow.transition(db, gf, MaterialStatus.ANALYZED, actor="analysis")
    assert gf.status == MaterialStatus.ANALYZED


def test_fail_and_retry_returns_to_failed_step(db: Session) -> None:
    chain = build_chain(db)
    v = chain.variant
    workflow.transition(db, v, VideoStatus.EDITING, actor="clip")
    workflow.mark_failed(db, v, step="render", error="ffmpeg exit 1", actor="clip")
    assert v.status == VideoStatus.FAILED
    assert v.last_good_status == "EDITING"
    assert v.failed_step == "render"

    workflow.retry(db, v, actor="master")
    assert v.status == VideoStatus.EDITING
    assert v.retry_count == 1
    assert v.error_message is None


def test_retry_limit(db: Session) -> None:
    chain = build_chain(db)
    v = chain.variant
    for _ in range(2):
        workflow.mark_failed(db, v, step="x", error="e", actor="t")
        workflow.retry(db, v, actor="t", max_retries=2)
    workflow.mark_failed(db, v, step="x", error="e", actor="t")
    with pytest.raises(RuntimeError, match="max retries"):
        workflow.retry(db, v, actor="t", max_retries=2)


def test_retry_requires_failed_status(db: Session) -> None:
    chain = build_chain(db)
    with pytest.raises(InvalidTransitionError):
        workflow.retry(db, chain.variant, actor="t")
