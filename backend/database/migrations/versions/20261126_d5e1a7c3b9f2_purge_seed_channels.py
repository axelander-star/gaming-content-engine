"""purge the old seed channels together with their test data

Revision ID: d5e1a7c3b9f2
Revises: b7f2c4d91e30
Create Date: 2026-11-26 09:30:00

Data only. ``b7d2e4c91f05`` deleted the eight old seed channels ("YouTube Shorts
DE" ... "Facebook Reels EN") only when *no* row referred to them. On the live
server test-mode runs had already written strategy versions, mock posts and
similar rows for them, so all eight stayed and still showed up under Topic
areas, Accounts and the channel assistant. The operator creates every channel
himself, so they go now together with what the test mode wrote for them.

A seed channel is purged only when all of this holds:

* it is a seed channel: placeholder flag, or one of the eight seed names in the
  "gaming" area without a handle or setup task;
* never connected (``not_connected``) and no platform id;
* no real post: every post that refers to it is a test-mode post (``is_mock``).

Rows that refer to such a channel (and rows that refer to those, and so on)
are deleted first; the referencing tables are read from the database catalogue.
Foreign keys with ``ON DELETE SET NULL`` are left to the database.

Finally, with ``APP_ENV=production``, the default area "Gaming" is archived when
no channel, material, video, campaign, production or post belongs to it any more.
Archived areas can be activated again with one click; nothing of the area itself
is deleted.
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e1a7c3b9f2"
down_revision: str | None = "b7f2c4d91e30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_NAMES = [
    f"{platform} {lang}"
    for platform in ("YouTube Shorts", "TikTok", "Instagram Reels", "Facebook Reels")
    for lang in ("DE", "EN")
]

# (child table, child column, parent column, on-delete action) for every foreign
# key that points at :parent
_CHILDREN = """
    SELECT rel.relname, att.attname, ref.attname, con.confdeltype
      FROM pg_constraint con
      JOIN pg_class rel ON rel.oid = con.conrelid
      JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
      JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
      JOIN pg_attribute ref ON ref.attrelid = con.confrelid AND ref.attnum = con.confkey[1]
     WHERE con.contype = 'f'
       AND con.confrelid = CAST(:parent AS regclass)
       AND nsp.nspname = current_schema()
"""

# content that keeps the Gaming area active (planning rows and sample data do not)
_CONTENT_TABLES = (
    "channels",
    "gameplay_files",
    "variants",
    "publishing_jobs",
    "posts",
    "library_items",
    "campaigns",
    "own_productions",
    "production_series",
)

_MAX_DEPTH = 8


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _purge(bind: sa.Connection, table: str, where: str, depth: int = 0) -> None:
    """Delete rows of ``table`` matching ``where`` after everything that refers to them."""
    if depth > _MAX_DEPTH:
        raise RuntimeError(f"reference chain too deep at {table}")
    for child, col, parent_col, action in bind.execute(
        sa.text(_CHILDREN), {"parent": _q(table)}
    ).all():
        if action == "n" or child == table:
            continue  # SET NULL is done by the database; self references go with the row
        child_where = f"{_q(col)} IN (SELECT {_q(parent_col)} FROM {_q(table)} WHERE {where})"
        _purge(bind, child, child_where, depth + 1)
    bind.execute(sa.text(f"DELETE FROM {_q(table)} WHERE {where}"))


def upgrade() -> None:
    bind = op.get_bind()
    names = ", ".join("'" + n.replace("'", "''") + "'" for n in SEED_NAMES)
    seed = f"""
        id IN (
            SELECT c.id
              FROM channels c
              JOIN content_projects p ON p.id = c.content_project_id
             WHERE c.auth_status = 'not_connected'
               AND c.external_channel_id IS NULL
               AND NOT (COALESCE(c.strategy, '{{}}'::jsonb) ? 'setup_task_id')
               AND (
                    (c.strategy ->> 'placeholder') = 'true'
                    OR (p.slug = 'gaming'
                        AND c.name IN ({names})
                        AND NOT (COALESCE(c.strategy, '{{}}'::jsonb) ? 'handle'))
               )
               AND NOT EXISTS (
                    SELECT 1 FROM posts po WHERE po.channel_id = c.id AND po.is_mock IS NOT TRUE
               )
        )
    """
    ids = [r[0] for r in bind.execute(sa.text(f"SELECT id FROM channels WHERE {seed}")).all()]
    if ids:
        id_list = ", ".join(str(int(i)) for i in ids)
        _purge(bind, "channels", f"id IN ({id_list})")

    if os.environ.get("APP_ENV", "development") != "production":
        return
    unused = " ".join(
        f"AND NOT EXISTS (SELECT 1 FROM {_q(t)} r WHERE r.content_project_id = p.id)"
        for t in _CONTENT_TABLES
    )
    bind.execute(
        sa.text(
            f"""
            UPDATE content_projects p
               SET status = 'archived'
             WHERE p.slug = 'gaming'
               AND p.status <> 'archived'
               {unused}
            """
        )
    )


def downgrade() -> None:
    # test-mode data is not restored; `python -m app.seed --demo-channels` creates
    # demo channels again where they are wanted (tests, smoke test)
    pass
