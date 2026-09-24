"""Shared Postgres checkpoint infrastructure for the LangGraph agents.

Extracted from ``graph.py`` so every agent (chat, outline, …) owns its own
pool and compiled graph while reusing the same connection handling and
thread-row cleanup, instead of copying ~150 lines of infrastructure per
agent. Behaviour is unchanged from the pre-extraction code.
"""

from typing import cast

from psycopg import (
    AsyncConnection,
    sql,
)
from psycopg.rows import (
    DictRow,
    dict_row,
)
from psycopg_pool import AsyncConnectionPool

from app.core.config import settings
from app.core.logging import logger

PostgresConnPool = AsyncConnectionPool[AsyncConnection[DictRow]]


def checkpointer_conninfo() -> str:
    """Return the DSN for a checkpointer's dedicated pool.

    The SQLModel engine DSN carries SQLAlchemy's ``+psycopg`` driver suffix;
    libpq (used directly by psycopg) wants the bare ``postgresql://`` scheme.
    """
    return str(settings.DATABASE_URL).replace("+psycopg", "", 1)


async def create_checkpoint_pool() -> PostgresConnPool:
    """Open a new connection pool for an AsyncPostgresSaver.

    Returns:
        The opened connection pool.

    Raises:
        Exception: If the pool cannot be created, in every environment.
    """
    try:
        # Configure pool size based on environment
        max_size = settings.CHECKPOINT_POOL_SIZE

        # The constructor cannot infer the dict_row connection type, hence
        # the cast (matches the declared PostgresConnPool alias).
        pool = cast(
            PostgresConnPool,
            AsyncConnectionPool(
                checkpointer_conninfo(),
                open=False,
                max_size=max_size,
                kwargs={
                    "autocommit": True,
                    "connect_timeout": 5,
                    # langgraph checkpointer is incompatible with psycopg
                    # prepared statements — must stay disabled.
                    "prepare_threshold": None,
                    "row_factory": dict_row,
                },
            ),
        )
        await pool.open()
        logger.info(
            "connection_pool_created",
            max_size=max_size,
            environment=settings.ENVIRONMENT.value,
        )
    except Exception as e:
        logger.exception(
            "connection_pool_creation_failed",
            error=str(e),
            environment=settings.ENVIRONMENT.value,
        )
        # Never degrade silently: the checkpointer is the only store for
        # conversation history and HITL resume state. Serving without it
        # loses data rather than surfacing an outage.
        raise e
    return pool


async def clear_thread_rows(pool: PostgresConnPool, thread_id: str) -> None:
    """Delete every checkpoint row for a thread across the three tables.

    Batched in a single pipeline round-trip. The checkpoint_migrations
    management table is intentionally untouched (inventory gap #8).
    """
    # Batch all DELETEs in a single pipeline round-trip
    async with pool.connection() as conn:
        async with conn.pipeline():
            for table in settings.CHECKPOINT_TABLES:
                await conn.execute(
                    sql.SQL("DELETE FROM {} WHERE thread_id = %s").format(
                        sql.Identifier(table)
                    ),
                    (thread_id,),
                )
    logger.info(
        "checkpoint_tables_cleared_for_session",
        tables=settings.CHECKPOINT_TABLES,
        session_id=thread_id,
    )


async def thread_row_count(pool: PostgresConnPool, thread_id: str) -> int:
    """Count checkpoint rows for a thread (0 = new/empty session).

    Used by the legacy outline import to skip threads that were never used
    (plan §8.2, decision 12.8) — a fresh client UUID creates no rows until
    the first turn.
    """
    async with pool.connection() as conn:
        cursor = await conn.execute(
            sql.SQL("SELECT count(*) AS n FROM checkpoints WHERE thread_id = %s"),
            (thread_id,),
        )
        row = await cursor.fetchone()
    return int(row["n"]) if row else 0
