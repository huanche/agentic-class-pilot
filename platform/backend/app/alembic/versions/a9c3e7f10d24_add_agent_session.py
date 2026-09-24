"""add unified agent_session table + migrate legacy chatsession rows

Revision ID: a9c3e7f10d24
Revises: b2d90f5e17ca
Create Date: 2026-09-17

Implements docs/agent-isolation-plan.md §3/§8.1 and decision 12.2: the new
identity table for every agent conversation, plus a one-shot data migration
of the legacy chat sessions (chapter-bound → chat+chapter scope, general →
chat+user scope; session_id and thread_id both keep the legacy row id, so
checkpoints are never rewritten). The legacy ``chatsession`` table is left
in place, frozen — it is dropped by a later revision after acceptance
(decision 12.9), which keeps this revision safely reversible.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = 'a9c3e7f10d24'
down_revision = 'b2d90f5e17ca'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('agentsession',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('thread_id', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('agent_key', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('scope_type', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('scope_id', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
    sa.Column('state_version', sa.Integer(), nullable=False),
    sa.Column('idempotency_key', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('run_token', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    sa.Column('run_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    # storage address is unique across ALL sessions — no two identity rows may
    # ever point at one checkpoint thread (plan §3)
    op.create_index(
        op.f('ix_agentsession_thread_id'), 'agentsession', ['thread_id'], unique=True
    )
    # list queries: caller's own sessions in one (agent, scope)
    op.create_index(
        'ix_agentsession_scope_lookup',
        'agentsession',
        ['user_id', 'agent_key', 'scope_type', 'scope_id'],
        unique=False,
    )
    # idempotent create: one live session per key inside a (user, agent, scope);
    # NULL keys (manual creates) don't participate in uniqueness (decision 12.3)
    op.create_index(
        'uq_agentsession_idempotency',
        'agentsession',
        ['user_id', 'agent_key', 'scope_type', 'scope_id', 'idempotency_key'],
        unique=True,
        postgresql_where=sa.text('idempotency_key IS NOT NULL'),
    )

    # one-shot data migration; ON CONFLICT keeps a re-run harmless
    op.execute(
        """
        INSERT INTO agentsession (
            id, thread_id, user_id, agent_key, scope_type, scope_id,
            title, status, state_version, idempotency_key,
            run_token, run_expires_at, created_at, updated_at
        )
        SELECT
            id,
            id::text,
            user_id,
            'chat',
            CASE WHEN chapter_id IS NULL THEN 'user' ELSE 'chapter' END,
            COALESCE(chapter_id::text, user_id::text),
            name,
            'active',
            1,
            NULL,
            NULL,
            NULL,
            COALESCE(created_at, now()),
            COALESCE(created_at, now())
        FROM chatsession
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade():
    # the legacy chatsession table was never touched — dropping this table
    # restores the pre-migration state completely
    op.drop_index('uq_agentsession_idempotency', table_name='agentsession')
    op.drop_index('ix_agentsession_scope_lookup', table_name='agentsession')
    op.drop_index(op.f('ix_agentsession_thread_id'), table_name='agentsession')
    op.drop_table('agentsession')
