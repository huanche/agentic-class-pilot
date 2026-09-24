"""drop generationjob table (courseware generation pipeline removed)

Revision ID: b2d90f5e17ca
Revises: a7e3f92c1d64
Create Date: 2026-09-17 00:00:00.000000

The generation feature (OpenMAIC proxy + snapshots + MinIO media) was deleted
from the codebase on 2026-09-17; git history keeps the full pipeline
(docs/langgraph-migration-plan.md and the deletion commit) if it ever returns.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b2d90f5e17ca'
down_revision = 'a7e3f92c1d64'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index('ix_generationjob_openmaic_job_id', table_name='generationjob')
    op.drop_table('generationjob')


def downgrade():
    # Rebuild the pre-deletion schema (data is NOT recovered — only structure).
    import sqlmodel.sql.sqltypes  # noqa: F401 — AutoString below

    op.create_table('generationjob',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('chapter_id', sa.Uuid(), nullable=False),
    sa.Column('requirement', sqlmodel.sql.sqltypes.AutoString(length=5000), nullable=False),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('source_filename', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
    sa.Column('progress', sa.Integer(), nullable=False),
    sa.Column('message', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('openmaic_job_id', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    sa.Column('classroom_id', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    sa.Column('classroom_url', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('scenes_count', sa.Integer(), nullable=True),
    sa.Column('is_published', sa.Boolean(), nullable=False),
    sa.Column('classroom_snapshot', sa.JSON(), nullable=True),
    sa.Column('edited_classroom', sa.JSON(), nullable=True),
    sa.Column('error', sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['chapter_id'], ['chapter.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_generationjob_openmaic_job_id', 'generationjob', ['openmaic_job_id'], unique=False)
