"""Versioned after-class reports with teacher summary.

student.after_class_reports grows a version axis and a teacher-facing
summary: PK becomes (session_key, report_kind, version). Legacy rows
default to kind='lesson', version=1 and keep their upsert semantics;
tutoring feedback appends kind='tutoring' versions 1..n (one per
explicit end), latest wins for display, history kept for growth
analysis.

Revision ID: final08
Revises: final07
"""

from alembic import op

revision = "final08"
down_revision = "final07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE student.after_class_reports "
               "ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE student.after_class_reports "
               "ADD COLUMN IF NOT EXISTS report_kind TEXT NOT NULL DEFAULT 'lesson'")
    op.execute("ALTER TABLE student.after_class_reports "
               "ADD COLUMN IF NOT EXISTS teacher_summary TEXT")
    op.execute("ALTER TABLE student.after_class_reports "
               "DROP CONSTRAINT IF EXISTS after_class_reports_pkey")
    op.execute("ALTER TABLE student.after_class_reports "
               "ADD PRIMARY KEY (session_key, report_kind, version)")


def downgrade() -> None:
    op.execute("ALTER TABLE student.after_class_reports "
               "DROP CONSTRAINT IF EXISTS after_class_reports_pkey")
    op.execute("ALTER TABLE student.after_class_reports "
               "ADD PRIMARY KEY (session_key)")
    op.execute("ALTER TABLE student.after_class_reports "
               "DROP COLUMN IF EXISTS teacher_summary")
    op.execute("ALTER TABLE student.after_class_reports "
               "DROP COLUMN IF EXISTS report_kind")
    op.execute("ALTER TABLE student.after_class_reports "
               "DROP COLUMN IF EXISTS version")
