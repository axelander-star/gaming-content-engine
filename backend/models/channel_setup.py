"""Channel assistant: prepared accounts the operator creates by hand at the platform.

The engine never registers platform accounts itself (terms of service of Google,
TikTok and Meta; phone and captcha checks). It prepares everything that can be
prepared: name, handle with alternatives, bio, profile picture, banner and a
forwarding e-mail address. The operator creates the account with these values,
confirms phone/captcha and then connects it via OAuth.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.enums import ChannelSetupStatus, Language, MailAliasStatus, PlatformCode
from database.base import Base, IdMixin, TimestampMixin, str_enum
from models.projects import ContentProject


class ChannelSetupTask(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_setup_tasks"
    __table_args__ = (
        # At most one open task per topic area, platform and language.
        Index(
            "uq_channel_setup_open",
            "content_project_id",
            "platform",
            "language",
            unique=True,
            postgresql_where="status = 'open'",
        ),
    )

    content_project_id: Mapped[int] = mapped_column(
        ForeignKey("content_projects.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[PlatformCode] = mapped_column(str_enum(PlatformCode, "platform_code"))
    language: Mapped[Language] = mapped_column(str_enum(Language, "language"))
    status: Mapped[ChannelSetupStatus] = mapped_column(
        str_enum(ChannelSetupStatus, "channel_setup_status"),
        default=ChannelSetupStatus.OPEN,
        server_default=ChannelSetupStatus.OPEN.value,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(120))
    handle: Mapped[str] = mapped_column(String(40))
    #: Further handles in case the first one is taken.
    alt_handles: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    #: Result of the availability check per handle: "free", "taken" or "unknown".
    handle_check: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    bio: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(254))
    email_status: Mapped[MailAliasStatus] = mapped_column(
        str_enum(MailAliasStatus, "mail_alias_status"),
        default=MailAliasStatus.NOT_NEEDED,
        server_default=MailAliasStatus.NOT_NEEDED.value,
    )
    email_rule_id: Mapped[str | None] = mapped_column(String(64))
    email_error: Mapped[str | None] = mapped_column(Text)
    #: ``local://`` URIs of the generated images.
    avatar_uri: Mapped[str | None] = mapped_column(String(500))
    banner_uri: Mapped[str | None] = mapped_column(String(500))
    #: Further name ideas with a short reason: ``[{"name": ..., "reason": ...}]``.
    name_options: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    #: Data the names are based on (``services/name_research.py``): facts for the
    #: dashboard, whether live YouTube data was used, when it was collected.
    research: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    #: Who wrote name and bio: "mock", "claude" or "template" (fallback without AI).
    text_source: Mapped[str] = mapped_column(String(32), default="template")
    #: Channel added to the engine once the operator created the account.
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)

    content_project: Mapped[ContentProject] = relationship()
