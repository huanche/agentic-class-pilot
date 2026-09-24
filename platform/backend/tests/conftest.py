import asyncio
import os
import sys

# Use a dedicated test database — the fixtures below DELETE all rows, so tests
# must never run against the development database.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres:changethis@localhost:5433/app_test"
)

# TestClient's anyio portal creates its event loop from the default policy,
# which on Windows is a ProactorEventLoop — psycopg's async mode (used by the
# LangGraph checkpointer pool, warmed up in the app lifespan) cannot run on
# it. Switch future loop creation to the selector loop before any portal
# starts. (set_event_loop_policy is deprecated for 3.16; revisit then.)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.config import settings
from app.core.db import engine, init_db
from app.core.langgraph.graph import langgraph_agent
from app.core.langgraph.outline import outline_agent
from app.main import app
from app.models import Chapter, Course, Item, User
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


async def _precreate_checkpoint_schema() -> None:
    # Create + close in the SAME loop: closing a psycopg pool from another
    # event loop raises and leaves the agent holding a broken pool.
    # Both agents: the second setup() is an IF NOT EXISTS no-op, but its
    # pool must be created (and closed) here too, before the db transaction.
    await langgraph_agent.create_graph()
    await langgraph_agent.close()
    await outline_agent.create_graph()
    await outline_agent.close()


@pytest.fixture(scope="session", autouse=True)
def checkpoint_schema() -> None:
    """Create the LangGraph checkpoint tables before ``db`` opens its
    session-long transaction.

    ``checkpointer.setup()`` runs ``CREATE INDEX CONCURRENTLY``, which waits
    for ALL transactions older than itself — the idle-in-transaction ``db``
    session would hang the app lifespan prewarm forever. Once the schema
    exists every setup() statement is an IF NOT EXISTS no-op (verified:
    skips instantly even with an open transaction).
    """
    asyncio.run(_precreate_checkpoint_schema())


@pytest.fixture(scope="session", autouse=True)
def db(checkpoint_schema) -> Generator[Session]:
    assert "app_test" in str(engine.url), "tests must use the app_test database"
    with Session(engine) as session:
        init_db(session)
        yield session
        for model in (Chapter, Course, Item, User):
            session.execute(delete(model))
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
