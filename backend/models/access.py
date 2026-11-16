"""Users, audit log, notifications and system settings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import NotificationLevel, UserRole
from database.base import Base, IdMixin, TimestampMixin, str_enum


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole, "user_role"), default=UserRole.VIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Incremented on logout-all, password change or deactivation -> invalidates sessions.
    session_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class AuditLog(IdMixin, Base):
    """Append-only log of every relevant action (who, what, before/after)."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_entity", "entity_type", "entity_id"),)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_agent: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    before: Mapped[dict[str, Any] | None]
    after: Mapped[dict[str, Any] | None]
    message: Mapped[str | None] = mapped_column(Text)


class Notification(IdMixin, TimestampMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    level: Mapped[NotificationLevel] = mapped_column(
        str_enum(NotificationLevel, "notification_level"), default=NotificationLevel.INFO
    )
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Area for the bell: system, rights, campaign, publishing, channel, reach, done.
    kind: Mapped[str | None] = mapped_column(String(32))
    #: Dashboard path that opens the matching page, e.g. ``/kanaele``.
    link: Mapped[str | None] = mapped_column(String(300))
    #: Warnings from the watchdog repeat at most once per window for the same key.
    dedup_key: Mapped[str | None] = mapped_column(String(200), index=True)
    #: Push to the phone: ``sent``, ``mock``, ``skipped``, ``failed`` (None = not yet decided).
    push_state: Mapped[str | None] = mapped_column(String(16), index=True)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SystemSetting(IdMixin, TimestampMixin, Base):
    """Operator-editable settings (budget, limits, switches) as JSON values."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), unique=True)
    value: Mapped[dict[str, Any]]
    description: Mapped[str | None] = mapped_column(Text)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
