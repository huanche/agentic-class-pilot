"""drop frozen chatsession table (legacy chat routes removed)

Revision ID: c41db8a7f5e3
Revises: a9c3e7f10d24
Create Date: 2026-09-18 00:00:00.000000

The legacy /chat and /ask routes and the ChatSession model were removed
after the frontend fully migrated to the unified /agent-sessions API
(commit 667ac59); this is the "later revision" a9c3e7f10d24 anticipated
(decision 12.9). Sessions now live in the agentsession table.
"""
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c41db8a7f5e3'
down_revision = 'a9c3e7f10d24'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table('chatsession')


def downgrade():
    # Rebuild the legacy schema (data is NOT recovered — only structure),
    # matching a7e3f92c1d64_add_chatsession.
    op.create_table('chatsession',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('chapter_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['chapter_id'], ['chapter.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
