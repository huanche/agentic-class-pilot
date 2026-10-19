"""Self rating for knowledge mastery.

student.knowledge_mastery.self_rating: the student's own 1-5 rating,
stored separately from the system-assessed stars and never used as
assessment evidence (spec: self rating expresses willingness only).

Revision ID: final07
Revises: final06
"""

from alembic import op

revision = "final07"
down_revision = "final06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE student.knowledge_mastery
        ADD COLUMN IF NOT EXISTS self_rating INTEGER
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE student.knowledge_mastery
        DROP COLUMN IF EXISTS self_rating
        """
    )
