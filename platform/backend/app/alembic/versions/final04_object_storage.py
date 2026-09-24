"""Allow teacher file tables to keep metadata while bytes live in object storage.

Revision ID: final04; Revises: final03.
"""
from alembic import op

revision = "final04"
down_revision = "final03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE teacher.mentra_artifact_files ALTER COLUMN bytes DROP NOT NULL")
    op.execute("ALTER TABLE teacher.mentra_course_material_files ALTER COLUMN bytes DROP NOT NULL")


def downgrade() -> None:
    # A safe downgrade requires first copying every MinIO object back into BYTEA.
    # Refuse to invent bytes for object-backed rows.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM teacher.mentra_artifact_files WHERE bytes IS NULL)
             OR EXISTS (SELECT 1 FROM teacher.mentra_course_material_files WHERE bytes IS NULL) THEN
            RAISE EXCEPTION 'copy object-backed files into BYTEA before downgrading final04';
          END IF;
        END $$
        """
    )
    op.execute("ALTER TABLE teacher.mentra_artifact_files ALTER COLUMN bytes SET NOT NULL")
    op.execute("ALTER TABLE teacher.mentra_course_material_files ALTER COLUMN bytes SET NOT NULL")
