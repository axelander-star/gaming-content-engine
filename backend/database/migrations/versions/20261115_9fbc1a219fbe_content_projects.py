"""content projects

Revision ID: 9fbc1a219fbe
Revises: 10196c7e684b
Create Date: 2026-11-15 12:24:58.295390
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '9fbc1a219fbe'
down_revision: str | None = '10196c7e684b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLES = ("channels", "gameplay_files", "variants", "publishing_jobs", "posts")


def upgrade() -> None:
    op.create_table('content_projects',
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('languages', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('audience', sa.Text(), nullable=True),
    sa.Column('tone', sa.Text(), nullable=True),
    sa.Column('subtopics', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('priority', sa.Integer(), server_default='100', nullable=False),
    sa.Column('status', sa.Enum('active', 'paused', 'archived', name='content_project_status', native_enum=False, create_constraint=True, length=32), server_default='active', nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_content_projects')),
    sa.UniqueConstraint('name', name=op.f('uq_content_projects_name')),
    sa.UniqueConstraint('slug', name=op.f('uq_content_projects_slug'))
    )
    op.create_index(op.f('ix_content_projects_status'), 'content_projects', ['status'], unique=False)

    # Gaming becomes the first project; all existing data belongs to it.
    op.execute(
        "INSERT INTO content_projects (slug, name, description, languages, subtopics) "
        "VALUES ('gaming', 'Gaming', 'Gaming-Trends, Gameplay, Highlights und Clips', "
        "'[\"de\", \"en\"]', '[]')"
    )
    for table in TABLES:
        op.add_column(table, sa.Column('content_project_id', sa.BigInteger(), nullable=True))
        op.execute(
            f"UPDATE {table} SET content_project_id = "
            "(SELECT id FROM content_projects WHERE slug = 'gaming')"
        )
        op.alter_column(table, 'content_project_id', nullable=False)
        op.create_index(op.f(f'ix_{table}_content_project_id'), table, ['content_project_id'], unique=False)
        op.create_foreign_key(op.f(f'fk_{table}_content_project_id_content_projects'), table, 'content_projects', ['content_project_id'], ['id'], ondelete='RESTRICT')

    op.create_unique_constraint('uq_channels_id_project', 'channels', ['id', 'content_project_id'])
    op.create_unique_constraint('uq_variants_id_project', 'variants', ['id', 'content_project_id'])
    op.create_foreign_key('fk_variants_channel_project', 'variants', 'channels', ['channel_id', 'content_project_id'], ['id', 'content_project_id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_publishing_jobs_channel_project', 'publishing_jobs', 'channels', ['channel_id', 'content_project_id'], ['id', 'content_project_id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_publishing_jobs_variant_project', 'publishing_jobs', 'variants', ['variant_id', 'content_project_id'], ['id', 'content_project_id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_posts_variant_project', 'posts', 'variants', ['variant_id', 'content_project_id'], ['id', 'content_project_id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_posts_channel_project', 'posts', 'channels', ['channel_id', 'content_project_id'], ['id', 'content_project_id'], ondelete='RESTRICT')


def downgrade() -> None:
    for name, table in (
        ('fk_posts_channel_project', 'posts'),
        ('fk_posts_variant_project', 'posts'),
        ('fk_publishing_jobs_variant_project', 'publishing_jobs'),
        ('fk_publishing_jobs_channel_project', 'publishing_jobs'),
        ('fk_variants_channel_project', 'variants'),
    ):
        op.drop_constraint(name, table, type_='foreignkey')
    op.drop_constraint('uq_variants_id_project', 'variants', type_='unique')
    op.drop_constraint('uq_channels_id_project', 'channels', type_='unique')
    for table in reversed(TABLES):
        op.drop_constraint(op.f(f'fk_{table}_content_project_id_content_projects'), table, type_='foreignkey')
        op.drop_index(op.f(f'ix_{table}_content_project_id'), table_name=table)
        op.drop_column(table, 'content_project_id')
    op.drop_index(op.f('ix_content_projects_status'), table_name='content_projects')
    op.drop_table('content_projects')
