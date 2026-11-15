"""Resumable upload sessions (chunked uploads that survive connection drops)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import UploadStatus
from database.base import Base, TimestampMixin, str_enum


class UploadSession(TimestampMixin, Base):
    """One file being uploaded in parts.

    ``purpose`` names the consumer that takes the finished file (e.g. ``material``);
    ``params`` holds the consumer's fields, ``result`` what it returned.
    """

    __tablename__ = "upload_sessions"
    __table_args__ = (
        CheckConstraint("received_bytes >= 0", name="received_non_negative"),
        CheckConstraint("received_bytes <= size_bytes", name="received_within_size"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(32))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    received_bytes: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    chunk_bytes: Mapped[int] = mapped_column(Integer)
    #: Optional SHA-256 of the whole file declared by the client, checked on completion.
    expected_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[UploadStatus] = mapped_column(
        str_enum(UploadStatus, "upload_status"), default=UploadStatus.UPLOADING, index=True
    )
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result: Mapped[dict[str, Any] | None]
    error_message: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
