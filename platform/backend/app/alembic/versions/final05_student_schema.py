"""student schema for the student agent's learning data

Phase S4: the platform migration owns the DDL of the student agent's seven
learning-data tables in the ``student`` schema. The student service connects
as the limited ``student`` role and only performs DML. All rows carry
user_id / course_id / publication_id; session-scoped rows carry session_key
and classroom_id so a teacher (or admin) can always trace a record back to a
lesson held under one published version.

Revision ID: final05
Revises: final04
"""

from alembic import op

revision = "final05"
down_revision = "final04"
branch_labels = None
depends_on = None

STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS student.student_sessions (
    session_key TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    publication_id TEXT NOT NULL,
    publication_version INTEGER NOT NULL,
    classroom_id TEXT,
    student_name TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ
    )""",
    """CREATE INDEX IF NOT EXISTS student_sessions_user_idx
    ON student.student_sessions (user_id, started_at DESC)""",
    """CREATE INDEX IF NOT EXISTS student_sessions_course_idx
    ON student.student_sessions (course_id, started_at DESC)""",
    """CREATE TABLE IF NOT EXISTS student.student_messages (
    id BIGSERIAL PRIMARY KEY,
    session_key TEXT NOT NULL,
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    publication_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    phase TEXT,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_key, seq)
    )""",
    """CREATE INDEX IF NOT EXISTS student_messages_session_idx
    ON student.student_messages (session_key, seq)""",
    """CREATE TABLE IF NOT EXISTS student.learning_events (
    id BIGSERIAL PRIMARY KEY,
    session_key TEXT NOT NULL,
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    publication_id TEXT NOT NULL,
    classroom_id TEXT,
    event_type TEXT NOT NULL,
    event_id TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_key, event_type, event_id)
    )""",
    """CREATE INDEX IF NOT EXISTS learning_events_user_idx
    ON student.learning_events (user_id, created_at DESC)""",
    """CREATE INDEX IF NOT EXISTS learning_events_session_idx
    ON student.learning_events (session_key, created_at)""",
    """CREATE TABLE IF NOT EXISTS student.playback_progress (
    session_key TEXT NOT NULL,
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    publication_id TEXT NOT NULL,
    classroom_id TEXT NOT NULL,
    scene_id TEXT NOT NULL,
    segment_id TEXT,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_key, scene_id)
    )""",
    """CREATE TABLE IF NOT EXISTS student.knowledge_mastery (
    id BIGSERIAL PRIMARY KEY,
    session_key TEXT NOT NULL,
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    publication_id TEXT NOT NULL,
    knowledge_point_id TEXT NOT NULL,
    stars INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT '未检测',
    evidence TEXT,
    source TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, course_id, publication_id, knowledge_point_id)
    )""",
    """CREATE INDEX IF NOT EXISTS knowledge_mastery_user_idx
    ON student.knowledge_mastery (user_id, course_id)""",
    """CREATE TABLE IF NOT EXISTS student.task_submissions (
    id BIGSERIAL PRIMARY KEY,
    session_key TEXT NOT NULL,
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    publication_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    content TEXT NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_key, task_id)
    )""",
    """CREATE TABLE IF NOT EXISTS student.after_class_reports (
    session_key TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    publication_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE INDEX IF NOT EXISTS after_class_reports_user_idx
    ON student.after_class_reports (user_id, created_at DESC)""",
]

STUDENT_TABLES = [
    "after_class_reports",
    "task_submissions",
    "knowledge_mastery",
    "playback_progress",
    "learning_events",
    "student_messages",
    "student_sessions",
]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS student")
    for statement in STATEMENTS:
        op.execute(statement)
    # The limited student role gets DML only (same model as the teacher role).
    # Local dev password comes from the environment at migration time; production
    # provisioning should create the role beforehand with a managed password.
    import os
    dev_password = os.environ.get("STUDENT_DB_PASSWORD", "student_local_dev")
    password_literal = dev_password.replace("'", "''")
    op.execute(
        f"""
        DO $student_role$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'student') THEN
            EXECUTE 'CREATE ROLE student LOGIN PASSWORD ''{password_literal}''';
          END IF;
        END $student_role$;
        """
    )
    op.execute(
        """
        DO $grant_student$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'student') THEN
            EXECUTE 'GRANT USAGE ON SCHEMA student TO student';
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA student TO student';
            EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA student TO student';
            EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA student GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO student';
            EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA student GRANT USAGE, SELECT ON SEQUENCES TO student';
          END IF;
        END
        $grant_student$
        """
    )


def downgrade() -> None:
    # Learning data is irreplaceable; rollback drops the schema definition only
    # via an explicit operator decision, not as a side effect of a downgrade.
    pass
