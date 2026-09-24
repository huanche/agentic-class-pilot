"""Revocable browser sessions and explicit platform/teacher course mapping."""
from alembic import op

revision = "final01"
down_revision = "c41db8a7f5e3"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE browser_session (
        token_hash VARCHAR(64) PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
        expires_at TIMESTAMPTZ NOT NULL
    )''')
    op.execute('CREATE INDEX ix_browser_session_user ON browser_session(user_id)')
    op.execute('''CREATE TABLE teacher_course_link (
        course_id UUID PRIMARY KEY REFERENCES course(id) ON DELETE CASCADE,
        external_course_id TEXT NOT NULL UNIQUE
    )''')


def downgrade():
    op.drop_table("teacher_course_link")
    op.drop_table("browser_session")
