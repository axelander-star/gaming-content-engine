"""Bio-link pages, affiliate links, newsletter sign-ups and outgoing mail (Ausbau A8).

* :class:`BioPage`: one public link page per channel (``links.<domain>/<slug>``)
  with the other profiles of the topic area, the latest videos, the affiliate
  links (each marked as an ad) and the newsletter form. Off until switched on.
* :class:`AffiliateLink`: a partner link of a topic area. It shows on the bio
  pages with the label "Anzeige"/"Ad"; a short hint in the post text is opt in.
* :class:`NewsletterSubscriber`: double opt-in. Only the address, the language,
  the consent text and the times are stored (no IP address, no name).
* :class:`OutgoingMail`: every e-mail the engine writes. In ``MAIL_MODE=mock``
  (default) nothing leaves the server; the mail only shows in the dashboard.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import Language
from database.base import Base, IdMixin, TimestampMixin, str_enum


class BioPage(IdMixin, TimestampMixin, Base):
    __tablename__ = "bio_pages"

    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), unique=True
    )
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    headline: Mapped[str] = mapped_column(String(120))
    intro: Mapped[str | None] = mapped_column(Text)
    #: Extra links of the operator: [{"title": ..., "url": ...}]
    links: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    show_videos: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    newsletter_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    views: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class AffiliateLink(IdMixin, TimestampMixin, Base):
    __tablename__ = "affiliate_links"

    content_project_id: Mapped[int] = mapped_column(
        ForeignKey("content_projects.id", ondelete="CASCADE"), index=True
    )
    #: Shown text, e.g. "Mein Headset".
    title: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(1000))
    #: Partner program, e.g. "Amazon PartnerNet" (for the operator).
    program: Mapped[str | None] = mapped_column(String(80))
    #: Only for channels of this language; None = all.
    language: Mapped[Language | None] = mapped_column(str_enum(Language, "language"))
    #: Words in title/game that make a post fit the link (for the hint in posts).
    keywords: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    #: Mention it in post texts ("Anzeige: … Link in der Bio"); off by default.
    in_posts: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    clicks: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    note: Mapped[str | None] = mapped_column(Text)


class NewsletterSubscriber(IdMixin, TimestampMixin, Base):
    __tablename__ = "newsletter_subscribers"
    __table_args__ = (UniqueConstraint("content_project_id", "email"),)

    content_project_id: Mapped[int] = mapped_column(
        ForeignKey("content_projects.id", ondelete="CASCADE"), index=True
    )
    #: Bio page channel the sign-up came from.
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"))
    email: Mapped[str] = mapped_column(String(254))
    language: Mapped[Language] = mapped_column(str_enum(Language, "language"))
    #: pending | confirmed | unsubscribed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    consent_text: Mapped[str] = mapped_column(Text)
    confirm_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    unsubscribe_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutgoingMail(IdMixin, TimestampMixin, Base):
    __tablename__ = "outgoing_mails"

    to_address: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(300))
    body_text: Mapped[str] = mapped_column(Text)
    #: newsletter_confirm | weekly_report | ...
    kind: Mapped[str] = mapped_column(String(32), index=True)
    #: mock (kept, not sent) | sent | failed
    status: Mapped[str] = mapped_column(String(16), index=True)
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
