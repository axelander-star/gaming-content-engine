"""Content projects: default project, lookups and the project guard.

The guard runs before every flush of every ORM session:

* channels and materials without a project get the default project (Gaming),
  so existing code paths keep working;
* variants, publishing jobs and posts inherit the project of their channel,
  variant or job;
* a variant whose source material belongs to another project than its channel
  is refused with :class:`ProjectMismatchError`.

The database enforces the same rule a second time through composite foreign
keys (channel id + project id), so even raw SQL cannot put content of one
topic area on a channel of another.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.enums import ContentProjectStatus, Language
from models.channels import Channel
from models.library import LibraryItem
from models.production import Clip, GameplayFile, Scene, Variant
from models.projects import DEFAULT_PROJECT_NAME, DEFAULT_PROJECT_SLUG, ContentProject
from models.publishing import Post, PublishingJob


class ProjectMismatchError(ValueError):
    """Content would end up on a channel of another content project."""


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name.replace("ß", "ss"))
    text = text.encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return slug[:64] or "bereich"


def default_project_id(session: Session) -> int:
    """Id of the default project, created on first use (idempotent, race-safe)."""
    conn = session.connection()
    found = conn.execute(
        select(ContentProject.id).where(ContentProject.slug == DEFAULT_PROJECT_SLUG)
    ).scalar()
    if found is not None:
        return int(found)
    conn.execute(
        pg_insert(ContentProject)
        .values(
            slug=DEFAULT_PROJECT_SLUG,
            name=DEFAULT_PROJECT_NAME,
            description="Gaming-Trends, Gameplay, Highlights und Clips",
            languages=[lang.value for lang in Language],
            subtopics=[],
            priority=100,
            status=ContentProjectStatus.ACTIVE.value,
        )
        .on_conflict_do_nothing()
    )
    return int(
        conn.execute(
            select(ContentProject.id).where(ContentProject.slug == DEFAULT_PROJECT_SLUG)
        ).scalar_one()
    )


def ensure_default_project(session: Session) -> ContentProject:
    project = session.get(ContentProject, default_project_id(session))
    assert project is not None
    return project


def material_project_id(session: Session, variant: Variant) -> int | None:
    """Project of the material a variant was cut from (via clip and scene)."""
    clip = session.get(Clip, variant.clip_id)
    scene = session.get(Scene, clip.scene_id) if clip is not None else None
    material = session.get(GameplayFile, scene.gameplay_file_id) if scene is not None else None
    if material is None:
        return None
    if material.content_project_id is None:  # pending in the same flush
        material.content_project_id = default_project_id(session)
    return int(material.content_project_id)


def _channel_project_id(session: Session, channel_id: int) -> int | None:
    channel = session.get(Channel, channel_id)
    if channel is None:
        return None
    if channel.content_project_id is None:  # pending in the same flush
        channel.content_project_id = default_project_id(session)
    return int(channel.content_project_id)


def _fill_or_check(obj: Any, expected: int | None, what: str) -> None:
    if expected is None:
        return  # the foreign keys report the missing row
    if obj.content_project_id is None:
        obj.content_project_id = expected
    elif obj.content_project_id != expected:
        raise ProjectMismatchError(
            f"{type(obj).__name__} #{obj.id or 'neu'} gehört zu Themenbereich "
            f"{obj.content_project_id}, {what} zu Themenbereich {expected}"
        )


def guard(session: Session) -> None:
    """Fill and check content projects of pending objects (called before each flush)."""
    pending = list(session.new) + list(session.dirty)
    if not pending:
        return
    with session.no_autoflush:
        # Order matters: channels and materials first, then what depends on them.
        for obj in pending:
            if isinstance(obj, Channel | GameplayFile) and obj.content_project_id is None:
                obj.content_project_id = default_project_id(session)
        for obj in pending:
            if isinstance(obj, Variant) and obj.channel_id is not None:
                channel_project = _channel_project_id(session, obj.channel_id)
                _fill_or_check(obj, channel_project, "der Kanal")
                if obj.clip_id is not None:
                    _fill_or_check(obj, material_project_id(session, obj), "das Ausgangsmaterial")
                if obj.library_item_id is not None:
                    item = session.get(LibraryItem, obj.library_item_id)
                    _fill_or_check(obj, item.content_project_id if item else None, "das Video")
        for obj in pending:
            if isinstance(obj, PublishingJob) and obj.variant_id is not None:
                variant = session.get(Variant, obj.variant_id)
                _fill_or_check(obj, variant.content_project_id if variant else None, "das Video")
                if obj.channel_id is not None:
                    _fill_or_check(obj, _channel_project_id(session, obj.channel_id), "der Kanal")
        for obj in pending:
            if isinstance(obj, Post) and obj.variant_id is not None:
                variant = session.get(Variant, obj.variant_id)
                _fill_or_check(obj, variant.content_project_id if variant else None, "das Video")
                if obj.channel_id is not None:
                    _fill_or_check(obj, _channel_project_id(session, obj.channel_id), "der Kanal")


@event.listens_for(Session, "before_flush")
def _before_flush(session: Session, _ctx: Any, _instances: Any) -> None:
    guard(session)


def project_problem(session: Session, project_id: int | None) -> str | None:
    """Reason why content of this project may not be produced or published, if any."""
    if project_id is None:
        return "no content project"
    project = session.get(ContentProject, project_id)
    if project is None:
        return f"content project {project_id} missing"
    if project.status != ContentProjectStatus.ACTIVE:
        return f"content project '{project.name}' is {project.status.value}"
    return None


__all__ = [
    "ProjectMismatchError",
    "default_project_id",
    "ensure_default_project",
    "guard",
    "material_project_id",
    "project_problem",
    "slugify",
]
