"""Delete a content project (topic area) together with everything that hangs on it.

The rows to delete are found by walking the foreign keys of ``Base.metadata``
from ``content_projects``: every row that points at a doomed row with
``CASCADE``, ``RESTRICT`` or ``NO ACTION`` is doomed too (``SET NULL`` rows
stay and only lose the link, e.g. sponsor inquiries). New tables are covered
automatically, as long as they declare their foreign keys.

Safety rules:

* the default project is never deleted (it is recreated on demand and holds
  old data); it can only be archived;
* nothing is deleted while a publishing job of the project is running;
* if the walk would reach a row that belongs to *another* topic area, the
  delete is refused instead of touching that area.

Files on disk are not removed here; they become orphans and the regular
``python -m app.housekeeping cleanup`` removes them later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Column, ForeignKeyConstraint, Table, and_, delete, func, select
from sqlalchemy.orm import Session

import models  # noqa: F401  registers every table on Base.metadata
from core.enums import PublishingJobStatus
from database.base import Base
from models.projects import DEFAULT_PROJECT_SLUG, ContentProject
from models.publishing import PublishingJob

#: Plain-language names for the summary shown before deleting.
TABLE_LABELS: dict[str, str] = {
    "channels": "Kanäle",
    "channel_credentials": "Kanal-Verbindungen (Logins)",
    "channel_setup_tasks": "Aufgaben im Kanal-Assistenten",
    "gameplay_files": "Material (hochgeladene Videos)",
    "scenes": "Szenen",
    "clips": "Clips",
    "variants": "Videos",
    "scripts": "Skripte",
    "voiceovers": "Sprachaufnahmen",
    "subtitles": "Untertitel",
    "quality_checks": "Qualitätsprüfungen",
    "rights_checks": "Rechteprüfungen",
    "publishing_jobs": "Veröffentlichungsaufträge",
    "posts": "Beiträge",
    "metrics": "Statistikwerte",
    "analytics_snapshots": "Statistik-Stände",
    "strategy_versions": "Strategie-Stände",
    "comments": "Kommentare",
    "revenue_entries": "Umsatzeinträge",
    "ideas": "Ideen",
    "research_items": "Recherche-Funde",
    "research_sources": "Recherche-Quellen",
    "competitors": "Konkurrenzkanäle",
    "competitor_videos": "Konkurrenzvideos",
    "trend_alarms": "Trend-Alarme",
    "editorial_days": "Einträge im Redaktionsplan",
    "plan_rules": "Wochenplan-Regeln",
    "calendar_events": "Kalender-Ereignisse",
    "content_focus": "Themenschwerpunkte",
    "library_items": "Mediathek-Einträge",
    "own_productions": "Eigenproduktionen",
    "production_series": "Videoserien",
    "campaigns": "Kampagnen",
    "campaign_submissions": "Kampagnen-Einreichungen",
    "affiliate_links": "Affiliate-Links",
    "newsletter_subscribers": "Newsletter-Abonnenten",
    "bio_pages": "Link-Seiten",
}
#: Labels for rows that stay but lose their link to the project.
KEPT_LABELS: dict[str, str] = {
    "sponsor_inquiries": "Sponsorenanfragen",
    "ai_calls": "KI-Protokolleinträge",
}
#: Order of the summary: most important first.
SUMMARY_ORDER = list(TABLE_LABELS)


class ProjectDeleteError(ValueError):
    """The project cannot be deleted (reason in German for the dashboard)."""


@dataclass
class DeletionPlan:
    project_id: int
    project_name: str
    #: table name -> primary keys to delete (includes ``content_projects``)
    rows: dict[str, set[int]] = field(default_factory=dict)
    #: table name -> number of rows that stay and only lose the link
    kept: dict[str, int] = field(default_factory=dict)
    #: reasons why deleting is not possible right now
    blockers: list[str] = field(default_factory=list)
    published: int = 0

    def summary(self) -> list[tuple[str, str, int]]:
        """(table, label, count) for every non-empty table, most important first."""
        out: list[tuple[str, str, int]] = []
        order = SUMMARY_ORDER + sorted(t for t in self.rows if t not in TABLE_LABELS)
        for table in order:
            if table == "content_projects":
                continue
            n = len(self.rows.get(table, ()))
            if n:
                out.append((table, TABLE_LABELS.get(table, "Weitere Einträge"), n))
        return out

    def kept_summary(self) -> list[tuple[str, str, int]]:
        return [
            (t, KEPT_LABELS.get(t, "Weitere Einträge"), n)
            for t, n in sorted(self.kept.items())
            if n
        ]


def _pk(table: Table) -> Column[Any]:
    (col,) = table.primary_key.columns
    return col


def _referrers(table: Table) -> list[tuple[Table, ForeignKeyConstraint]]:
    found: list[tuple[Table, ForeignKeyConstraint]] = []
    for other in Base.metadata.tables.values():
        for fk in other.foreign_key_constraints:
            if fk.referred_table is table:
                found.append((other, fk))
    return found


def plan(session: Session, project_id: int) -> DeletionPlan:
    project = session.get(ContentProject, project_id)
    if project is None:
        raise LookupError(project_id)
    result = DeletionPlan(project_id=project.id, project_name=project.name)
    tables = Base.metadata.tables
    rows: dict[str, set[int]] = {"content_projects": {project.id}}
    todo = ["content_projects"]
    kept_ids: dict[str, set[int]] = {}
    while todo:
        name = todo.pop()
        parent = tables[name]
        parent_ids = rows[name]
        for child, fk in _referrers(parent):
            pairs = [(el.parent, el.column) for el in fk.elements]
            join = child.join(parent, and_(*[c == p for c, p in pairs]))
            ids: set[int] = set(
                session.execute(
                    select(_pk(child)).select_from(join).where(_pk(parent).in_(parent_ids))
                ).scalars()
            )
            if not ids:
                continue
            if (fk.ondelete or "").upper() in ("SET NULL", "SET DEFAULT"):
                kept_ids.setdefault(child.name, set()).update(ids)
                continue
            new = ids - rows.get(child.name, set())
            if new:
                rows.setdefault(child.name, set()).update(new)
                if child.name not in todo:
                    todo.append(child.name)
    result.rows = rows
    result.kept = {
        t: len(ids - rows.get(t, set())) for t, ids in kept_ids.items() if ids - rows.get(t, set())
    }
    result.published = _count_published(session, rows.get("posts", set()))

    if project.slug == DEFAULT_PROJECT_SLUG:
        result.blockers.append(
            "Der Standardbereich kann nicht gelöscht werden, nur archiviert. "
            "Ältere Daten ohne eigenen Themenbereich landen dort."
        )
    running = session.scalar(
        select(func.count(PublishingJob.id)).where(
            PublishingJob.content_project_id == project.id,
            PublishingJob.status == PublishingJobStatus.RUNNING,
        )
    )
    if running:
        result.blockers.append(
            "Gerade läuft eine Veröffentlichung in diesem Themenbereich. "
            "Bitte warten, bis sie fertig ist."
        )
    foreign = _foreign_rows(session, rows, project.id)
    if foreign:
        result.blockers.append(
            "Andere Themenbereiche nutzen Inhalte aus diesem Bereich ("
            + ", ".join(foreign)
            + "). Damit dort nichts verloren geht, wird nicht gelöscht."
        )
    return result


def _count_published(session: Session, post_ids: set[int]) -> int:
    if not post_ids:
        return 0
    posts = Base.metadata.tables["posts"]
    return int(
        session.scalar(
            select(func.count())
            .select_from(posts)
            .where(_pk(posts).in_(post_ids), posts.c.published_at.is_not(None))
        )
        or 0
    )


def _foreign_rows(session: Session, rows: dict[str, set[int]], project_id: int) -> list[str]:
    """Labels of tables where the walk reached rows of another topic area."""
    found = []
    for name, ids in rows.items():
        table = Base.metadata.tables[name]
        col = table.c.get("content_project_id")
        if col is None or not ids:
            continue
        n = session.scalar(
            select(func.count())
            .select_from(table)
            .where(_pk(table).in_(ids), col.is_not(None), col != project_id)
        )
        if n:
            found.append(TABLE_LABELS.get(name, name))
    return found


def execute(session: Session, deletion: DeletionPlan) -> None:
    """Delete every row of the plan, children first. The caller commits."""
    if deletion.blockers:
        raise ProjectDeleteError(deletion.blockers[0])
    session.flush()
    for table in reversed(Base.metadata.sorted_tables):
        ids = deletion.rows.get(table.name)
        if ids:
            session.execute(delete(table).where(_pk(table).in_(ids)))
    # forget the deleted rows, so the session does not try to refresh them later
    for key in list(session.identity_map.keys()):
        mapped = getattr(key[0], "__table__", None)
        obj = session.identity_map.get(key)
        if (
            mapped is not None
            and obj is not None
            and key[1][0] in deletion.rows.get(mapped.name, ())
        ):
            session.expunge(obj)
    session.expire_all()
