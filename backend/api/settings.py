"""Operator settings, emergency stop and auto-publish switch."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.deps import Admin, AppSettings, DbSession, Operator, Viewer, csrf_protect
from core.enums import UserRole
from services.controls import (
    EffectiveControls,
    OperationsSettings,
    effective_controls,
    get_operations,
    update_operations,
    update_runtime_controls,
)

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(csrf_protect)])


class SettingsOut(BaseModel):
    controls: EffectiveControls
    operations: OperationsSettings


class ControlsUpdate(BaseModel):
    emergency_stop: bool | None = None
    auto_publish_enabled: bool | None = None


@router.get("", response_model=SettingsOut)
def read_settings(_: Viewer, db: DbSession, settings: AppSettings) -> SettingsOut:
    return SettingsOut(controls=effective_controls(db, settings), operations=get_operations(db))


@router.patch("/controls", response_model=EffectiveControls)
def change_controls(
    body: ControlsUpdate, user: Operator, db: DbSession, settings: AppSettings
) -> EffectiveControls:
    """Operators may *activate* the emergency stop. Everything else needs an admin:
    releasing the stop and switching auto-publish."""
    changes: dict[str, bool] = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Nothing to change")
    is_admin = user.role == UserRole.ADMIN
    if not is_admin and changes != {"emergency_stop": True}:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Only admins may release the emergency stop or change auto-publish",
        )
    if changes.get("auto_publish_enabled") and not settings.auto_publish_enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Auto-publish is disabled by server configuration (AUTO_PUBLISH_ENABLED)",
        )
    update_runtime_controls(db, user.id, **changes)
    db.commit()
    return effective_controls(db, settings)


@router.patch("/operations", response_model=OperationsSettings)
def change_operations(body: dict[str, Any], admin: Admin, db: DbSession) -> OperationsSettings:
    unknown = set(body) - set(OperationsSettings.model_fields)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Unknown settings: {sorted(unknown)}"
        )
    try:
        result = update_operations(db, admin.id, body)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    db.commit()
    return result
