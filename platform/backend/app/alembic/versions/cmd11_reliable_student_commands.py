"""Reliable student commands, snapshots, versions and progress outbox.

Revision ID: cmd11
Revises: pub10
"""
from alembic import op

revision = "cmd11"
down_revision = "pub10"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE student.student_sessions ADD COLUMN IF NOT EXISTS state_version BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE student.student_sessions ADD COLUMN IF NOT EXISTS content_generation BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE student.student_sessions ADD COLUMN IF NOT EXISTS snapshot JSONB",
    "ALTER TABLE student.student_sessions ADD COLUMN IF NOT EXISTS lesson_id TEXT",
    "ALTER TABLE student.student_sessions ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ",
    """UPDATE student.student_sessions s SET snapshot=e.payload,
        lesson_id=e.payload->>'lessonId',
        state_version=COALESCE((e.payload->>'stateVersion')::bigint,0),
        content_generation=COALESCE((e.payload->>'contentGeneration')::bigint,0)
        FROM (SELECT DISTINCT ON (session_key) session_key,payload
              FROM student.learning_events WHERE event_type='agent_state'
              ORDER BY session_key,id DESC) e
        WHERE s.session_key=e.session_key AND s.snapshot IS NULL AND s.revoked_at IS NULL""",
    """CREATE TABLE IF NOT EXISTS student.student_commands (
        session_key TEXT NOT NULL, command_id TEXT NOT NULL,
        payload_hash TEXT NOT NULL, kind TEXT NOT NULL, payload JSONB NOT NULL,
        base_state JSONB NOT NULL, accepted_version BIGINT NOT NULL,
        content_generation BIGINT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','processing','completed','failed','cancelled')),
        claim_token TEXT, lease_until TIMESTAMPTZ, result JSONB, failure JSONB,
        attempts INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY(session_key,command_id))""",
    """CREATE UNIQUE INDEX IF NOT EXISTS student_commands_active_idx
        ON student.student_commands(session_key) WHERE status IN ('pending','processing')""",
    """CREATE INDEX IF NOT EXISTS student_commands_recovery_idx
        ON student.student_commands(status,lease_until,created_at)""",
    """CREATE TABLE IF NOT EXISTS student.pending_progress_sync (
        event_id TEXT PRIMARY KEY, session_key TEXT NOT NULL, user_id TEXT NOT NULL,
        course_id TEXT NOT NULL, classroom_id TEXT NOT NULL, event TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', claim_token TEXT, lease_until TIMESTAMPTZ,
        attempts INTEGER NOT NULL DEFAULT 0, next_retry_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE INDEX IF NOT EXISTS pending_progress_sync_ready_idx
        ON student.pending_progress_sync(status,next_retry_at)""",
    """DO $grant_commands$ BEGIN
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='student') THEN
            GRANT SELECT,INSERT,UPDATE,DELETE ON student.student_commands,student.pending_progress_sync TO student;
        END IF;
        END $grant_commands$""",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    # Keep received answers and version fences intact on application rollback.
    pass
