"""add chatsession table (langgraph migration step 3)

Revision ID: a7e3f92c1d64
Revises: 24f411eb18ca
Create Date: 2026-09-16 20:31:00.000000

"""
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a7e3f92c1d64'
down_revision = '24f411eb18ca'
branch_labels = None
depends_on = None


def upgrade():
    # Identity row only — messages live in the langgraph checkpoint tables
    # (thread_id = str(chatsession.id)); no business-side message table.
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


def downgrade():
    op.drop_table('chatsession')
