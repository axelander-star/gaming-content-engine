"""remove unused placeholder channels

Revision ID: b7d2e4c91f05
Revises: 7433e2700ebb
Create Date: 2026-11-25 14:00:00

Data only: the eight channels the old seed created ("YouTube Shorts DE" etc.,
marked ``strategy.placeholder`` by 3c9e1f2a7b44) are deleted, because the
operator creates every channel himself through the channel assistant.

A channel is only deleted when it is still a pure placeholder (flag set, not
connected, no platform id, no setup task) *and* no row in any table refers to
it. The referencing tables are read from the database catalogue, so a table
added later is covered as well. Everything else stays untouched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b7d2e4c91f05'
down_revision: str | None = '7433e2700ebb'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# every (table, column) whose foreign key points at channels.id
_REFERENCES = """
    SELECT rel.relname AS table_name, att.attname AS column_name
      FROM pg_constraint con
      JOIN pg_class rel ON rel.oid = con.conrelid
      JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
      JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
      JOIN pg_attribute ref ON ref.attrelid = con.confrelid AND ref.attnum = con.confkey[1]
     WHERE con.contype = 'f'
       AND con.confrelid = 'channels'::regclass
       AND ref.attname = 'id'
       AND nsp.nspname = current_schema()
"""


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def upgrade() -> None:
    bind = op.get_bind()
    refs = bind.execute(sa.text(_REFERENCES)).all()
    unused = " ".join(
        f"AND NOT EXISTS (SELECT 1 FROM {_quote(t)} r WHERE r.{_quote(col)} = c.id)"
        for t, col in sorted(set(refs))
    )
    bind.execute(
        sa.text(
            f"""
            DELETE FROM channels c
             WHERE (c.strategy ->> 'placeholder') = 'true'
               AND c.auth_status = 'not_connected'
               AND c.external_channel_id IS NULL
               AND NOT (c.strategy ? 'setup_task_id')
               {unused}
            """
        )
    )


def downgrade() -> None:
    # deleted placeholders carried no data; `python -m app.seed --demo-channels`
    # recreates them if they are ever needed again
    pass
