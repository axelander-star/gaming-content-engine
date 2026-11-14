"""System status for the dashboard (Phase 15): checks, backups, scaling criteria."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from redis import Redis

from api.deps import AppSettings, DbSession, Viewer
from services import backup, monitoring
from services.queue import get_redis

router = APIRouter(prefix="/system", tags=["system"])


class CheckOut(BaseModel):
    key: str
    label: str
    status: str
    detail: str
    value: float | None


class AdviceOut(BaseModel):
    key: str
    text: str
    evidence: str


class BackupOut(BaseModel):
    file: str
    created_at: str
    size_bytes: int
    rows: int


class BackupStatusOut(BaseModel):
    configured: bool
    count: int
    total_bytes: int
    age_hours: float | None
    latest: BackupOut | None
    restore_check: dict[str, Any] | None
    backups: list[BackupOut]


class SystemStatusOut(BaseModel):
    checked_at: str
    status: str
    checks: list[CheckOut]
    scaling: list[AdviceOut]
    samples: list[dict[str, Any]]
    backup: BackupStatusOut


def _backup_out(m: backup.Manifest) -> BackupOut:
    return BackupOut(
        file=m.file, created_at=m.created_at, size_bytes=m.size_bytes, rows=sum(m.tables.values())
    )


@router.get("/status", response_model=SystemStatusOut)
def system_status(
    _: Viewer,
    db: DbSession,
    settings: AppSettings,
    redis_client: Annotated[Redis, Depends(get_redis)],
) -> SystemStatusOut:
    report = monitoring.collect(db, settings, redis_client)
    st = backup.status(settings)
    backups = backup.list_backups(settings)
    return SystemStatusOut(
        checked_at=report.checked_at,
        status=report.status,
        checks=[CheckOut(**vars(c)) for c in report.checks],
        scaling=[AdviceOut(**vars(a)) for a in report.scaling],
        samples=report.samples[:: max(1, len(report.samples) // 288)],
        backup=BackupStatusOut(
            configured=st.configured,
            count=st.count,
            total_bytes=st.total_bytes,
            age_hours=st.age_hours,
            latest=_backup_out(st.latest) if st.latest else None,
            restore_check=vars(st.restore_check) if st.restore_check else None,
            backups=[_backup_out(m) for m in backups[:14]],
        ),
    )
