"""System status for the dashboard (Phase 15): checks, backups, scaling criteria."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from redis import Redis

from api.deps import Admin, AppSettings, DbSession, Viewer, csrf_protect
from services import backup, deploy_hook, monitoring, platform_apps
from services.queue import get_redis

router = APIRouter(prefix="/system", tags=["system"], dependencies=[Depends(csrf_protect)])


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


class DeployHookOut(BaseModel):
    """Instant server update via GitHub webhook (27.11.2026)."""

    secret_ready: bool
    #: Only shown to admins, to copy it into the GitHub webhook form.
    secret: str | None
    watcher_active: bool
    watcher_seen_at: str | None
    pending: bool
    last_hook: dict[str, Any] | None
    last_update: dict[str, Any] | None


@router.get("/deploy-hook", response_model=DeployHookOut)
def deploy_hook_status(_: Admin, settings: AppSettings) -> DeployHookOut:
    return DeployHookOut(**vars(deploy_hook.status(settings)))


# --- platform app keys entered in the dashboard (27.11.2026) ---------------------------


class PlatformAppOut(BaseModel):
    provider: str
    configured: bool
    source: str | None
    client_key: str
    secret_set: bool
    redirect_uri: str
    redirect_uri_ok: bool
    config_id: str


class PlatformAppIn(BaseModel):
    client_key: str
    #: empty keeps the secret saved before
    client_secret: str | None = None
    redirect_uri: str = ""
    #: Meta only: configuration id of Facebook Login for Business
    config_id: str = ""


def _app_out(s: platform_apps.AppStatus) -> PlatformAppOut:
    return PlatformAppOut(**vars(s))


@router.get("/platform-apps/{provider}", response_model=PlatformAppOut)
def platform_app_status(
    provider: str, _: Admin, db: DbSession, settings: AppSettings
) -> PlatformAppOut:
    try:
        return _app_out(platform_apps.status(db, settings, provider))
    except platform_apps.PlatformAppError as exc:
        raise HTTPException(404, detail=str(exc)) from exc


@router.put("/platform-apps/{provider}", response_model=PlatformAppOut)
def save_platform_app(
    provider: str, body: PlatformAppIn, admin: Admin, db: DbSession, settings: AppSettings
) -> PlatformAppOut:
    """Save the app keys; the secret is stored encrypted and never returned."""
    try:
        result = platform_apps.save(
            db,
            settings,
            provider,
            client_key=body.client_key,
            client_secret=body.client_secret,
            redirect_uri=body.redirect_uri,
            user_id=admin.id,
            config_id=body.config_id,
        )
    except platform_apps.PlatformAppError as exc:
        db.rollback()
        raise HTTPException(422, detail=str(exc)) from exc
    db.commit()
    return _app_out(result)


@router.delete("/platform-apps/{provider}", response_model=PlatformAppOut)
def clear_platform_app(
    provider: str, admin: Admin, db: DbSession, settings: AppSettings
) -> PlatformAppOut:
    try:
        result = platform_apps.clear(db, settings, provider, admin.id)
    except platform_apps.PlatformAppError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    db.commit()
    return _app_out(result)
