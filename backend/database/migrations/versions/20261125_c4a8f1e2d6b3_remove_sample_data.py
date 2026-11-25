"""remove invented sample data from the live dashboard

Revision ID: c4a8f1e2d6b3
Revises: b7d2e4c91f05
Create Date: 2026-11-25 15:00:00

Data only. While the trend, research and radar sources ran in mock mode they
filled the dashboard with invented data (fictional games, example articles,
test competitor videos, test alarms) and the idea lab drafted ideas from it.
Production no longer creates such data (``Settings.sample_data_enabled``);
this removes what is already there:

* ideas that are still *new*, not used by a production or series, and built
  only from mock research items;
* mock research items, mock competitor videos, mock trend reports and trends;
* undecided mock trend alarms;
* fictional test games (``is_test_data``) nothing else refers to.

Finally the default topic area "Gaming" is archived when nothing at all refers
to it any more (no channels, material, ideas, campaigns, plans ...; cost
history does not count), so the
operator starts with his own topics. It can be activated again with one click.
This step runs only with ``APP_ENV=production``; development and test databases
keep their Gaming area.
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c4a8f1e2d6b3'
down_revision: str | None = 'b7d2e4c91f05'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATEMENTS = (
    # ideas drafted only from mock research items (must run before those go)
    """
    DELETE FROM ideas i
     WHERE i.status = 'new'
       AND jsonb_typeof(i.sources) = 'array'
       AND jsonb_array_length(i.sources) > 0
       AND NOT EXISTS (SELECT 1 FROM own_productions o WHERE o.idea_id = i.id)
       AND NOT EXISTS (SELECT 1 FROM production_series s WHERE s.idea_id = i.id)
       AND NOT EXISTS (
            SELECT 1
              FROM jsonb_array_elements(i.sources) src
              LEFT JOIN research_items r ON r.id = (src ->> 'item_id')::bigint
             WHERE r.id IS NULL OR r.is_mock IS NOT TRUE
       )
    """,
    "DELETE FROM research_items WHERE is_mock",
    "DELETE FROM competitor_videos WHERE is_mock",
    "DELETE FROM trend_alarms WHERE is_mock AND approved_production_id IS NULL",
    "DELETE FROM trend_reports WHERE is_mock",
    "DELETE FROM trends WHERE is_mock",
    """
    DELETE FROM games g
     WHERE g.is_test_data
       AND NOT EXISTS (SELECT 1 FROM trends t WHERE t.game_id = g.id)
       AND NOT EXISTS (SELECT 1 FROM publisher_policies p WHERE p.game_id = g.id)
       AND NOT EXISTS (SELECT 1 FROM assets a WHERE a.game_id = g.id)
       AND NOT EXISTS (SELECT 1 FROM campaigns c WHERE c.game_id = g.id)
       AND NOT EXISTS (SELECT 1 FROM gameplay_files f WHERE f.game_id = g.id)
    """,
)

# every (table, column) whose foreign key points at content_projects.id
_REFERENCES = """
    SELECT rel.relname, att.attname
      FROM pg_constraint con
      JOIN pg_class rel ON rel.oid = con.conrelid
      JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
      JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
      JOIN pg_attribute ref ON ref.attrelid = con.confrelid AND ref.attnum = con.confkey[1]
     WHERE con.contype = 'f'
       AND con.confrelid = 'content_projects'::regclass
       AND ref.attname = 'id'
       AND nsp.nspname = current_schema()
"""


# pure history (cost accounting) does not keep the area alive
_IGNORED = {"ai_calls", "costs", "audit_logs", "agent_runs"}


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def upgrade() -> None:
    bind = op.get_bind()
    for statement in _STATEMENTS:
        bind.execute(sa.text(statement))
    if os.environ.get("APP_ENV", "development") != "production":
        return
    refs = bind.execute(sa.text(_REFERENCES)).all()
    unused = " ".join(
        f"AND NOT EXISTS (SELECT 1 FROM {_quote(t)} r WHERE r.{_quote(col)} = p.id)"
        for t, col in sorted(set(refs))
        if t not in _IGNORED
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
    # invented data is not restored; mock sources create new sample data in development
    pass
