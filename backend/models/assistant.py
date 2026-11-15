"""Chat assistant history and the actions it took (extension phase E4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import ChatActionStatus
from database.base import Base, IdMixin, str_enum


class ChatMessage(IdMixin, Base):
    __tablename__ = "chat_messages"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    #: ``user`` or ``assistant``.
    role: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    #: ``mock`` or ``claude`` for assistant messages.
    provider: Mapped[str | None] = mapped_column(String(32))
    #: Ids of the ``ai_calls`` rows behind this answer.
    ai_call_ids: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")


class ChatAction(IdMixin, Base):
    """One tool call of the assistant, with what is needed to undo it."""

    __tablename__ = "chat_actions"

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    message_id: Mapped[int] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    tool: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    #: One German sentence for the action card.
    summary: Mapped[str] = mapped_column(String(500))
    status: Mapped[ChatActionStatus] = mapped_column(
        str_enum(ChatActionStatus, "chat_action_status"), default=ChatActionStatus.DONE
    )
    undoable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    #: State before the action (enough to restore it).
    undo: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    undone_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
