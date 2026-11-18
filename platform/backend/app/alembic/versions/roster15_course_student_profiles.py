"""Teacher-confirmed course roster, separate from login and learning records."""
from alembic import op

revision = "roster15"
down_revision = "roster14"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE course_student_profile (
        course_id UUID NOT NULL REFERENCES course(id) ON DELETE CASCADE,
        student_number VARCHAR(64) NOT NULL,
        name VARCHAR(255) NOT NULL,
        major VARCHAR(255) NOT NULL DEFAULT '',
        grade VARCHAR(64) NOT NULL DEFAULT '',
        gender VARCHAR(32) NOT NULL DEFAULT '',
        user_id UUID REFERENCES "user"(id) ON DELETE SET NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (course_id, student_number),
        UNIQUE (course_id, user_id)
    )''')


def downgrade():
    op.execute("DROP TABLE course_student_profile")
