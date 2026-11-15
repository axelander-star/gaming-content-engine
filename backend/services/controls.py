"""Operator controls and settings stored in ``system_settings``.

Two layers decide whether something may happen:

1. Environment (``core.config.Settings``) is the hard ceiling set by whoever
   deploys the server. If ``AUTO_PUBLISH_ENABLED=false`` in the environment, the
   dashboard can never switch publishing on.
2. Runtime controls in the database, changed from the dashboard (and audited).

The emergency stop is active if *either* layer activates it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import Language, PlatformCode
from models.access import SystemSetting
from services import audit

CONTROLS_KEY = "controls"
OPERATIONS_KEY = "operations"


class RuntimeControls(BaseModel):
    emergency_stop: bool = False
    auto_publish_enabled: bool = False


class OperationsSettings(BaseModel):
    """Operator settings from PROJECT_SPEC section 8 ("Seite: Einstellungen").

    Per-channel publishing bounds live on the channel itself.
    """

    monthly_budget_eur: float = Field(default=50.0, ge=0, le=100_000)
    #: One material in DE and EN needs about 16 production jobs; 50 leaves room for
    #: about three materials per day (acceptance test, 15.11.2026).
    max_daily_production_jobs: int = Field(default=50, ge=0, le=10_000)
    max_parallel_render_jobs: int = Field(default=1, ge=1, le=64)
    min_quality_score: float = Field(default=0.7, ge=0, le=1)
    min_publish_interval_minutes: int = Field(default=60, ge=0, le=7 * 24 * 60)
    languages: list[Language] = Field(default_factory=lambda: [Language.DE, Language.EN])
    platforms: list[PlatformCode] = Field(default_factory=lambda: list(PlatformCode))
    ai_provider: str = Field(default="mock", max_length=64)
    #: Creative variants (A–D) per clip and channel; each one differs in hook or format.
    creative_variants: int = Field(default=2, ge=1, le=4)
    tts_provider: str = Field(default="mock", max_length=64)
    notifications_enabled: bool = True


class EffectiveControls(BaseModel):
    """What actually applies right now, combining environment and database."""

    emergency_stop: bool
    auto_publish_enabled: bool
    publishing_mode: str
    publishing_allowed: bool
    paid_api_calls_enabled: bool
    env_auto_publish_enabled: bool
    env_emergency_stop: bool


def _load(session: Session, key: str) -> SystemSetting | None:
    return session.scalar(select(SystemSetting).where(SystemSetting.key == key))


def get_runtime_controls(session: Session) -> RuntimeControls:
    row = _load(session, CONTROLS_KEY)
    return RuntimeControls.model_validate(row.value) if row else RuntimeControls()


def get_operations(session: Session) -> OperationsSettings:
    row = _load(session, OPERATIONS_KEY)
    return OperationsSettings.model_validate(row.value) if row else OperationsSettings()


def effective_controls(session: Session, settings: Settings) -> EffectiveControls:
    rt = get_runtime_controls(session)
    stop = settings.emergency_stop or rt.emergency_stop
    auto = settings.auto_publish_enabled and rt.auto_publish_enabled
    return EffectiveControls(
        emergency_stop=stop,
        auto_publish_enabled=auto,
        publishing_mode=settings.publishing_mode,
        publishing_allowed=auto and settings.publishing_mode == "live" and not stop,
        paid_api_calls_enabled=settings.paid_api_calls_enabled and not stop,
        env_auto_publish_enabled=settings.auto_publish_enabled,
        env_emergency_stop=settings.emergency_stop,
    )


def _save(
    session: Session,
    key: str,
    new: BaseModel,
    old: BaseModel,
    user_id: int | None,
    description: str,
) -> None:
    row = _load(session, key)
    value: dict[str, Any] = new.model_dump(mode="json")
    if row is None:
        session.add(
            SystemSetting(key=key, value=value, description=description, updated_by_user_id=user_id)
        )
    else:
        row.value = value
        row.updated_by_user_id = user_id
    audit.record(
        session,
        f"settings.{key}.update",
        user_id=user_id,
        entity_type="system_settings",
        before=old.model_dump(mode="json"),
        after=value,
    )


def update_runtime_controls(
    session: Session, user_id: int | None, **changes: bool
) -> RuntimeControls:
    old = get_runtime_controls(session)
    new = old.model_copy(update=changes)
    _save(session, CONTROLS_KEY, new, old, user_id, "Emergency stop and auto-publish switch")
    return new


def update_operations(
    session: Session, user_id: int | None, changes: dict[str, Any]
) -> OperationsSettings:
    old = get_operations(session)
    new = OperationsSettings.model_validate({**old.model_dump(), **changes})
    _save(session, OPERATIONS_KEY, new, old, user_id, "Operator settings")
    return new
