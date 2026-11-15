"""Content projects (topic areas such as Gaming or Nutrition).

Every channel belongs to exactly one content project, and so does every piece
of content (material, video variant, publishing job, post). Composite foreign
keys guarantee in the database that a variant, its publishing job and its post
always share the project of their channel, so content of one topic area can
never be published on a channel of another (see ``services/projects.py``).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import ContentProjectStatus
from database.base import Base, IdMixin, TimestampMixin, str_enum

#: Slug of the project that existing (pre-project) data belongs to.
DEFAULT_PROJECT_SLUG = "gaming"
DEFAULT_PROJECT_NAME = "Gaming"


class ContentProject(IdMixin, TimestampMixin, Base):
    __tablename__ = "content_projects"

    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    #: Language codes the project produces in (subset of ``core.enums.Language``).
    languages: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    audience: Mapped[str | None] = mapped_column(Text)
    tone: Mapped[str | None] = mapped_column(Text)
    #: Sub-topics, e.g. ["GTA", "Gaming-News"] or ["Rezepte", "Lebensmittelwissen"].
    subtopics: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    #: Lower number wins when content fits several projects.
    priority: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    status: Mapped[ContentProjectStatus] = mapped_column(
        str_enum(ContentProjectStatus, "content_project_status"),
        default=ContentProjectStatus.ACTIVE,
        server_default=ContentProjectStatus.ACTIVE.value,
        index=True,
    )
