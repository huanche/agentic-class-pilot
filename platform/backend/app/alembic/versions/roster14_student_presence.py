"""Record recent activity in the student workspace."""
from alembic import op

revision = "roster14"
down_revision = "obs13"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE browser_session ADD COLUMN student_seen_at TIMESTAMPTZ, "
               "ADD COLUMN student_session_key TEXT")


def downgrade():
    op.execute("ALTER TABLE browser_session DROP COLUMN student_session_key, DROP COLUMN student_seen_at")
