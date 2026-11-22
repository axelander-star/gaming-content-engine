"""mark seed channels as placeholders

Revision ID: 3c9e1f2a7b44
Revises: 6f1f7f4b3930
Create Date: 2026-11-22 10:45:00

Data only: the channels created by the seed ("YouTube Shorts DE" etc. in the default
topic area) have no real account behind them. They get ``strategy.placeholder = true``
as long as they are not connected, have no platform id and were not created by the
channel assistant. The overview does not count them; the channel assistant prepares
them like missing channels.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '3c9e1f2a7b44'
down_revision: str | None = '6f1f7f4b3930'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_NAMES = [
    f"{platform} {lang}"
    for platform in ("YouTube Shorts", "TikTok", "Instagram Reels", "Facebook Reels")
    for lang in ("DE", "EN")
]


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE channels c
               SET strategy = COALESCE(c.strategy, '{}'::jsonb) || '{"placeholder": true}'::jsonb
              FROM content_projects p
             WHERE p.id = c.content_project_id
               AND p.slug = 'gaming'
               AND c.name = ANY(:names)
               AND c.auth_status = 'not_connected'
               AND c.external_channel_id IS NULL
               AND NOT (COALESCE(c.strategy, '{}'::jsonb) ? 'setup_task_id')
            """
        ).bindparams(sa.bindparam("names", SEED_NAMES, type_=sa.ARRAY(sa.String())))
    )


def downgrade() -> None:
    op.execute("UPDATE channels SET strategy = strategy - 'placeholder' WHERE strategy ? 'placeholder'")
