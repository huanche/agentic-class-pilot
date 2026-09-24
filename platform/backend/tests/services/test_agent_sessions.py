"""Service-level tests for the exclusive runners, delete recovery, and the
state-version gate (review findings #1, #3, #8).

The runners are exercised with stubbed invocations and a monkeypatched
heartbeat interval so lease-loss scenarios run in milliseconds; no real LLM
or checkpoint pool is involved.
"""

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app import crud
from app.models import AgentSession, UserCreate
from app.services import agent_sessions
from app.services.agent_registry import require_agent
from app.services.agent_sessions import LeaseLostError
from tests.utils.utils import random_email, random_lower_string


def _make_user(db: Session) -> Any:
    return crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(), password=random_lower_string()
        ),
    )


def _make_session(db: Session, user: Any) -> AgentSession:
    spec = require_agent("chat")
    scope = agent_sessions.ScopeContext("user", str(user.id), user)
    return agent_sessions.create_session(db, user, spec, scope)


# ----- run_exclusive (finding #1) -----


def test_run_exclusive_returns_result_and_releases(db: Session) -> None:
    user = _make_user(db)
    row = _make_session(db, user)

    async def invoke() -> str:
        return "ok"

    assert asyncio.run(agent_sessions.run_exclusive(db, row, invoke)) == "ok"
    db.refresh(row)
    assert row.run_token is None


def test_run_exclusive_cancels_run_when_lease_lost(db: Session, monkeypatch: Any) -> None:
    user = _make_user(db)
    row = _make_session(db, user)
    monkeypatch.setattr(agent_sessions, "LEASE_HEARTBEAT_SECONDS", 0.02)
    monkeypatch.setattr(agent_sessions, "renew_lease_standalone", lambda *a, **k: False)

    cancelled = False

    async def invoke() -> str:
        nonlocal cancelled
        try:
            await asyncio.sleep(0.5)  # a long generation
            return "never"
        except asyncio.CancelledError:
            cancelled = True
            raise

    with pytest.raises(LeaseLostError):
        asyncio.run(agent_sessions.run_exclusive(db, row, invoke))
    assert cancelled  # the generation was actually aborted, not just reported


def test_stream_exclusive_aborts_on_lease_loss_after_yielded_chunks(
    db: Session, monkeypatch: Any
) -> None:
    user = _make_user(db)
    row = _make_session(db, user)
    monkeypatch.setattr(agent_sessions, "LEASE_HEARTBEAT_SECONDS", 0.02)
    monkeypatch.setattr(agent_sessions, "renew_lease_standalone", lambda *a, **k: False)

    async def make_chunks():  # type: ignore[async-generator]
        yield "a"
        await asyncio.sleep(0.5)  # cancelled here by the stolen lease
        yield "b"

    token = agent_sessions.acquire_lease(db, row)

    async def consume() -> list[str]:
        chunks = []
        async for chunk in agent_sessions.stream_exclusive(db, row, token, make_chunks):
            chunks.append(chunk)
        return chunks

    with pytest.raises(LeaseLostError):
        asyncio.run(consume())
    db.refresh(row)
    assert row.run_token is None


def test_stream_exclusive_propagates_producer_error(db: Session) -> None:
    user = _make_user(db)
    row = _make_session(db, user)

    async def make_chunks():  # type: ignore[async-generator]
        yield "a"
        raise RuntimeError("upstream exploded")

    token = agent_sessions.acquire_lease(db, row)

    async def consume() -> list[str]:
        chunks = []
        async for chunk in agent_sessions.stream_exclusive(db, row, token, make_chunks):
            chunks.append(chunk)
        return chunks

    with pytest.raises(RuntimeError, match="upstream exploded"):
        asyncio.run(consume())
    db.refresh(row)
    assert row.run_token is None


# ----- delete recovery (finding #3) -----


def test_delete_can_retry_after_checkpoint_clear_failure(
    db: Session, monkeypatch: Any
) -> None:
    from app.core.langgraph.graph import langgraph_agent

    user = _make_user(db)
    row = _make_session(db, user)
    spec = require_agent("chat")
    row_id = row.id

    calls = {"n": 0}

    async def flaky_clear(thread_id: str) -> None:
        del thread_id  # the stub ignores which thread it clears
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("checkpoint clear failed mid-delete")

    monkeypatch.setattr(langgraph_agent, "clear_chat_history", flaky_clear)

    with pytest.raises(RuntimeError):
        asyncio.run(agent_sessions.delete_session(db, user, spec, row_id))

    # the row is NOT stranded behind a non-active status — it stays a plain
    # active session the owner can see and delete again
    db.expire_all()
    survivor = db.get(AgentSession, row_id)
    assert survivor is not None
    assert survivor.status == "active"

    asyncio.run(agent_sessions.delete_session(db, user, spec, row_id))
    db.expire_all()
    assert db.get(AgentSession, row_id) is None
    assert calls["n"] == 2


# ----- state-version gate (finding #8) -----


def test_create_records_spec_state_version(db: Session) -> None:
    user = _make_user(db)
    row = _make_session(db, user)
    assert row.state_version == require_agent("chat").state_version


def test_state_mismatch_refuses_run(db: Session) -> None:
    user = _make_user(db)
    row = _make_session(db, user)
    row.state_version = 99  # a future graph version
    db.add(row)
    db.commit()
    with pytest.raises(HTTPException) as exc_info:
        agent_sessions.ensure_state_compatible(require_agent("chat"), row)
    assert exc_info.value.status_code == 409
