"""Provision teacher sessions using the pinned upstream OpenMAIC schema.

Runtime services receive DML only; never run upstream ALTER TABLE at request time.
Revision ID: final03; Revises: final02.
"""
from alembic import op

revision = "final03"
down_revision = "final02"
branch_labels = None
depends_on = None

SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS mentra_teacher_agent_sessions (
  id                  TEXT PRIMARY KEY,
  owner_id            TEXT NOT NULL,
  prompt              TEXT NOT NULL,
  title               TEXT,
  title_state         TEXT NOT NULL DEFAULT 'manual',
  stage_id            TEXT NOT NULL,
  active_stage_id     TEXT,
  skill_id            TEXT,
  origin              TEXT,
  existing_course     BOOLEAN NOT NULL DEFAULT FALSE,
  status              TEXT NOT NULL DEFAULT 'queued',
  attempt             INTEGER NOT NULL DEFAULT 0,
  delivered_user_message_seq INTEGER NOT NULL DEFAULT 0,
  lease_worker_id     TEXT,
  lease_worker_pid    INTEGER,
  lease_heartbeat_at  BIGINT,
  cancel_requested_at BIGINT,
  error               TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at          TIMESTAMPTZ,
  CONSTRAINT mentra_teacher_agent_sessions_attempt_nonnegative CHECK (attempt >= 0),
  CONSTRAINT agent_sessions_title_state_known
    CHECK (title_state IN ('pending','automatic','manual')),
  CONSTRAINT mentra_teacher_agent_sessions_status_known
    CHECK (status IN ('queued','running','succeeded','failed','cancelled'))
);

ALTER TABLE mentra_teacher_agent_sessions
  ADD COLUMN IF NOT EXISTS delivered_user_message_seq INTEGER NOT NULL DEFAULT 0;

ALTER TABLE mentra_teacher_agent_sessions
  ADD COLUMN IF NOT EXISTS title TEXT;

ALTER TABLE mentra_teacher_agent_sessions
  ADD COLUMN IF NOT EXISTS title_state TEXT NOT NULL DEFAULT 'manual';

DO $agent_session_title_state_constraint$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'mentra_teacher_agent_sessions'::regclass
      AND conname = 'agent_sessions_title_state_known'
  ) THEN
    LOCK TABLE mentra_teacher_agent_sessions IN ACCESS EXCLUSIVE MODE;
    IF NOT EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conrelid = 'mentra_teacher_agent_sessions'::regclass
        AND conname = 'agent_sessions_title_state_known'
    ) THEN
      ALTER TABLE mentra_teacher_agent_sessions
        ADD CONSTRAINT agent_sessions_title_state_known
        CHECK (title_state IN ('pending','automatic','manual'))
        NOT VALID;
    END IF;
  END IF;
END
$agent_session_title_state_constraint$;

DO $agent_session_title_state_validation$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'mentra_teacher_agent_sessions'::regclass
      AND conname = 'agent_sessions_title_state_known'
      AND NOT convalidated
  ) THEN
    ALTER TABLE mentra_teacher_agent_sessions
      VALIDATE CONSTRAINT agent_sessions_title_state_known;
  END IF;
END
$agent_session_title_state_validation$;

CREATE INDEX IF NOT EXISTS mentra_teacher_agent_sessions_status_live_idx
  ON mentra_teacher_agent_sessions (status, created_at) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS mentra_teacher_agent_sessions_owner_live_idx
  ON mentra_teacher_agent_sessions (owner_id, created_at) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS mentra_teacher_agent_events (
  session_id TEXT NOT NULL REFERENCES mentra_teacher_agent_sessions(id) ON DELETE CASCADE,
  seq        INTEGER NOT NULL,
  ts         BIGINT NOT NULL,
  attempt    INTEGER NOT NULL,
  type       TEXT NOT NULL,
  data       JSONB,
  PRIMARY KEY (session_id, seq),
  CONSTRAINT mentra_teacher_agent_events_seq_positive CHECK (seq > 0)
);

CREATE TABLE IF NOT EXISTS mentra_teacher_agent_entries (
  session_id TEXT NOT NULL REFERENCES mentra_teacher_agent_sessions(id) ON DELETE CASCADE,
  seq        INTEGER NOT NULL,
  entry_id   TEXT NOT NULL,
  parent_id  TEXT,
  type       TEXT NOT NULL,
  data       JSONB NOT NULL,
  ts         TIMESTAMPTZ NOT NULL,
  attempt    INTEGER NOT NULL,
  PRIMARY KEY (session_id, seq),
  CONSTRAINT mentra_teacher_agent_entries_entry_id_unique UNIQUE (session_id, entry_id),
  CONSTRAINT mentra_teacher_agent_entries_parent_fk
    FOREIGN KEY (session_id, parent_id)
    REFERENCES mentra_teacher_agent_entries (session_id, entry_id)
);

CREATE INDEX IF NOT EXISTS mentra_teacher_agent_entries_type_idx
  ON mentra_teacher_agent_entries (session_id, type, seq);

CREATE TABLE IF NOT EXISTS mentra_teacher_agent_owner_counters (
  owner_id TEXT PRIMARY KEY,
  n        BIGINT NOT NULL DEFAULT 0,
  CONSTRAINT mentra_teacher_agent_owner_counters_nonnegative CHECK (n >= 0)
);

CREATE TABLE IF NOT EXISTS mentra_teacher_agent_owner_events (
  owner_id   TEXT NOT NULL,
  id         BIGINT NOT NULL,
  ts         BIGINT NOT NULL,
  session_id TEXT NOT NULL,
  type       TEXT NOT NULL,
  status     TEXT,
  attempt    INTEGER,
  data       JSONB NOT NULL,
  PRIMARY KEY (owner_id, id),
  CONSTRAINT agent_owner_session_events_type_known_v2 CHECK (type IN
    ('session_created','session_status','session_deleted',
     'session_active_stage','session_cancel_requested','session_title')),
  CONSTRAINT mentra_teacher_agent_owner_events_status_known CHECK (status IS NULL OR status IN
    ('queued','running','succeeded','failed','cancelled')),
  CONSTRAINT mentra_teacher_agent_owner_events_attempt_nonnegative
    CHECK (attempt IS NULL OR attempt >= 0)
);

DO $agent_session_owner_event_type_constraint$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'mentra_teacher_agent_owner_events'::regclass
      AND conname = 'mentra_teacher_agent_owner_events_type_known'::name
  ) OR NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'mentra_teacher_agent_owner_events'::regclass
      AND conname = 'agent_owner_session_events_type_known_v2'
  ) THEN
    LOCK TABLE mentra_teacher_agent_owner_events IN ACCESS EXCLUSIVE MODE;
    IF NOT EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conrelid = 'mentra_teacher_agent_owner_events'::regclass
        AND conname = 'agent_owner_session_events_type_known_v2'
    ) THEN
      ALTER TABLE mentra_teacher_agent_owner_events
        ADD CONSTRAINT agent_owner_session_events_type_known_v2 CHECK (type IN
          ('session_created','session_status','session_deleted',
           'session_active_stage','session_cancel_requested','session_title'))
        NOT VALID;
    END IF;
    IF EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conrelid = 'mentra_teacher_agent_owner_events'::regclass
        AND conname = 'mentra_teacher_agent_owner_events_type_known'::name
    ) THEN
      ALTER TABLE mentra_teacher_agent_owner_events
        DROP CONSTRAINT mentra_teacher_agent_owner_events_type_known;
    END IF;
  END IF;
END
$agent_session_owner_event_type_constraint$;

-- Installing the superset above is a catalog-only operation while the short
-- ACCESS EXCLUSIVE lock is held. Validate separately so PostgreSQL scans an
-- existing projection table under VALIDATE CONSTRAINT's weaker lock instead.
-- Once validated, later initializers avoid taking that table lock altogether.
DO $agent_session_owner_event_type_validation$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'mentra_teacher_agent_owner_events'::regclass
      AND conname = 'agent_owner_session_events_type_known_v2'
      AND NOT convalidated
  ) THEN
    ALTER TABLE mentra_teacher_agent_owner_events
      VALIDATE CONSTRAINT agent_owner_session_events_type_known_v2;
  END IF;
END
$agent_session_owner_event_type_validation$;

CREATE TABLE IF NOT EXISTS mentra_teacher_agent_urls (
  session_id TEXT NOT NULL REFERENCES mentra_teacher_agent_sessions(id) ON DELETE CASCADE,
  url        TEXT NOT NULL,
  source     TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (session_id, url),
  CONSTRAINT mentra_teacher_agent_urls_source_known CHECK (source IN ('user','web_search'))
);

CREATE INDEX IF NOT EXISTS mentra_teacher_agent_urls_session_created_idx
  ON mentra_teacher_agent_urls (session_id, created_at);
"""

def upgrade() -> None:
    connection = op.get_bind()
    previous = connection.exec_driver_sql("SHOW search_path").scalar_one()
    connection.exec_driver_sql("SET LOCAL search_path TO teacher, public")
    connection.exec_driver_sql(SCHEMA_SQL)
    connection.exec_driver_sql("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='teacher') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA teacher TO teacher;
      END IF;
    END $$""")
    from sqlalchemy import text
    connection.execute(text("SELECT set_config('search_path', :previous, true)"), {"previous": previous})

def downgrade() -> None:
    # Keep live conversation history; rollback must not destroy user data.
    pass
