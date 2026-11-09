"""Online-presence tracking for browser sessions.

Revision ID: obs13
Revises: rec12
"""
from alembic import op

revision = "obs13"
down_revision = "rec12"
branch_labels = None
depends_on = None

STATEMENTS = [
    # last-seen stamps on every (throttled) cookie-authenticated request;
    # "online" = unexpired session seen within the last few minutes
    "ALTER TABLE browser_session ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()",
    # backfill pre-existing sessions as long offline — only requests after
    # this migration make a session "online" (DEFAULT now() would mark every
    # stale token as online right after migrating)
    "UPDATE browser_session SET last_seen_at = to_timestamp(0)",
    "CREATE INDEX IF NOT EXISTS ix_browser_session_last_seen ON browser_session(last_seen_at)",
]


def upgrade():
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_browser_session_last_seen")
    op.execute("ALTER TABLE browser_session DROP COLUMN IF EXISTS last_seen_at")
