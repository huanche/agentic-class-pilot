"""Prepare shared lesson knowledge when a video is published.

Revision ID: pub10
Revises: final09
"""
from alembic import op

revision = "pub10"
down_revision = "final09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS student.published_lesson_knowledge (
            course_id TEXT NOT NULL,
            lesson_id TEXT NOT NULL,
            video_revision TEXT NOT NULL,
            classroom_id TEXT NOT NULL,
            extractor_hash TEXT NOT NULL DEFAULT '',
            scenes JSONB NOT NULL,
            points JSONB,
            coverage JSONB,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            next_retry_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            lease_until TIMESTAMPTZ,
            claim_token TEXT,
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (course_id, lesson_id, video_revision),
            CONSTRAINT published_lesson_knowledge_status_check
                CHECK (status IN ('pending', 'running', 'ready', 'failed'))
        )
    """)
    op.execute("ALTER TABLE student.published_lesson_knowledge "
               "ADD COLUMN IF NOT EXISTS claim_token TEXT")
    op.execute("GRANT SELECT, INSERT, UPDATE ON student.published_lesson_knowledge TO student")


def downgrade() -> None:
    # A downgrade must not silently discard generated teaching content.
    pass
