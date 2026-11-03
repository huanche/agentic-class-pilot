"""Stable learning records and immutable lesson content versions.

Revision ID: rec12
Revises: cmd11
"""
from alembic import op

revision = "rec12"
down_revision = "cmd11"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE student.student_messages ADD COLUMN IF NOT EXISTS message_id TEXT",
    "ALTER TABLE student.student_messages ADD COLUMN IF NOT EXISTS task_id TEXT",
    "ALTER TABLE student.student_messages ADD COLUMN IF NOT EXISTS episode_id TEXT",
    """CREATE UNIQUE INDEX IF NOT EXISTS student_message_identity_idx
       ON student.student_messages(session_key,message_id) WHERE message_id IS NOT NULL""",
    "ALTER TABLE student.student_commands ADD COLUMN IF NOT EXISTS task_id TEXT",
    "ALTER TABLE student.student_commands ADD COLUMN IF NOT EXISTS student_message_id TEXT",
    "ALTER TABLE student.student_commands ADD COLUMN IF NOT EXISTS content_id TEXT",
    "ALTER TABLE student.student_sessions ADD COLUMN IF NOT EXISTS content_id TEXT",
    """CREATE TABLE IF NOT EXISTS student.lesson_content_versions (
        content_id TEXT PRIMARY KEY, course_id TEXT NOT NULL, lesson_id TEXT NOT NULL,
        video_revision TEXT NOT NULL, compiler_version TEXT NOT NULL,
        source_manifest_hash TEXT NOT NULL, payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE(course_id,lesson_id,video_revision,compiler_version,source_manifest_hash))""",
    """DO $grant_records$ BEGIN
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='student') THEN
            GRANT SELECT,INSERT ON student.lesson_content_versions TO student;
            REVOKE UPDATE,DELETE ON student.lesson_content_versions FROM student;
        END IF;
        END $grant_records$""",
]


def upgrade():
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade():
    # Content revisions and learning evidence must survive application rollback.
    pass
