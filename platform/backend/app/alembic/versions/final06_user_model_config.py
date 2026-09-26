"""Per-user BYOK model configuration.

public.user_model_config: one row per user; config JSONB stores provider
settings with credential fields encrypted via app.core.credential_crypto.

Revision ID: final06
Revises: final05
"""

from alembic import op

revision = "final06"
down_revision = "final05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.user_model_config (
            user_id UUID PRIMARY KEY REFERENCES "user"(id) ON DELETE CASCADE,
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    pass
