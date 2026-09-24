"""Unified agent-session service: resolver, idempotent create, lease, cleanup.

The single authority for "whose session is this, which agent/scope does it
bind to, and where does its history live" (docs/agent-isolation-plan.md §3-5,
decisions §12). The LangGraph checkpointer stays the only message store; this
service owns the identity row, the run lease (multi-worker mutex, §12.4) and
checkpoint cleanup on delete.

HTTP semantics (§12.5): 404 = missing OR foreign OR mismatched binding
(indistinguishable on purpose); 403 = business access denied; 409 = busy
(``SessionBusyError``) — routes translate the latter.
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, select

from app.core.db import engine
from app.core.logging import logger
from app.models import AgentSession, User, get_datetime_utc
from app.services.agent_registry import (
    AgentSpec,
    ScopeContext,
    get_agent,
    require_agent,
    require_scope,
)

LEASE_TTL_SECONDS = 120
LEASE_HEARTBEAT_SECONDS = 30
AUTO_TITLE_MAX_CHARS = 24


class SessionBusyError(Exception):
    """Another run holds the session's lease — maps to HTTP 409."""


class LeaseLostError(Exception):
    """Our lease expired and was stolen mid-run; the run was aborted.

    Raised by the exclusive runners when the heartbeat can no longer renew —
    the generation is cancelled instead of continuing to write into a thread
    another request may now own (review finding: lease must bound ALL runs).
    """


@dataclass(frozen=True)
class ResolvedSession:
    """Everything a run operation needs, validated in one place (§4.2).

    Caller and owner are distinct: a superuser touching a student's chat
    session resolves with the *owner* as the identity the agent sees.
    """

    session: AgentSession
    spec: AgentSpec
    scope: ScopeContext
    owner: User


# ----- Scope resolution -----


def resolve_scope(
    db: Session, user: User, agent_key: str, scope_type: str, scope_id: str
) -> tuple[AgentSpec, ScopeContext]:
    """Validate agent + scope against the registry and load the real object."""
    spec = require_agent(agent_key)
    if scope_type not in spec.allowed_scope_types:
        raise HTTPException(status_code=404, detail="Agent session not found")
    adapter = require_scope(scope_type)
    scope = adapter.load(db, user, scope_id, manage=spec.scope_requires_manage)
    return spec, scope


# ----- Listing / picking (read-only, no creation side effects) -----


def list_sessions(
    db: Session,
    user: User,
    spec: AgentSpec,
    scope: ScopeContext | None = None,
    *,
    skip: int = 0,
    limit: int = 100,
) -> tuple[list[AgentSession], int]:
    """The caller's own sessions for one agent, newest activity first.

    ``scope=None`` lists across scopes (the legacy chat route's behaviour);
    the unified API always passes a scope. Stable order: updated_at, id.
    """
    where = [
        AgentSession.user_id == user.id,
        AgentSession.agent_key == spec.agent_key,
        AgentSession.status == "active",
    ]
    if scope is not None:
        where.extend(
            [
                AgentSession.scope_type == scope.scope_type,
                AgentSession.scope_id == scope.scope_id,
            ]
        )
    count = (
        db.exec(select(func.count()).select_from(AgentSession).where(*where)).one()
    )
    statement = (
        select(AgentSession)
        .where(*where)
        .order_by(col(AgentSession.updated_at).desc(), col(AgentSession.id))
        .offset(skip)
        .limit(limit)
    )
    return list(db.exec(statement).all()), count


def pick_session(
    db: Session,
    user: User,
    spec: AgentSpec,
    scope: ScopeContext,
    preferred_session_id: uuid.UUID | None,
) -> AgentSession | None:
    """§4.2: a preferred session must match exactly (else 404, never a
    silent switch); without a preference, the most recently active or None."""
    if preferred_session_id is not None:
        return get_session_for_action(
            db, user, spec, preferred_session_id, expect=(scope.scope_type, scope.scope_id)
        ).session
    sessions, _ = list_sessions(db, user, spec, scope, limit=1)
    return sessions[0] if sessions else None


# ----- Creation (idempotent) -----


def create_session(
    db: Session,
    user: User,
    spec: AgentSpec,
    scope: ScopeContext,
    idempotency_key: str | None = None,
) -> AgentSession:
    """Create a session identity + fresh opaque thread (§7.1, §12.2/12.3).

    A retry with the same idempotency key inside the same (user, agent,
    scope) returns the existing session instead of a duplicate.
    """
    if idempotency_key:
        existing = _find_by_idempotency_key(db, user, spec, scope, idempotency_key)
        if existing is not None:
            return existing
    agent_session = AgentSession(
        user_id=user.id,
        agent_key=spec.agent_key,
        scope_type=scope.scope_type,
        scope_id=scope.scope_id,
        thread_id=f"sess:{uuid.uuid4()}",
        state_version=spec.state_version,
        idempotency_key=idempotency_key,
    )
    try:
        db.add(agent_session)
        db.commit()
        db.refresh(agent_session)
    except IntegrityError:
        # concurrent twin request won the unique (user, agent, scope, key) index
        db.rollback()
        if not idempotency_key:
            raise
        existing = _find_by_idempotency_key(db, user, spec, scope, idempotency_key)
        if existing is None:
            raise
        return existing
    return agent_session


def _find_by_idempotency_key(
    db: Session, user: User, spec: AgentSpec, scope: ScopeContext, key: str
) -> AgentSession | None:
    return db.exec(
        select(AgentSession).where(
            AgentSession.user_id == user.id,
            AgentSession.agent_key == spec.agent_key,
            AgentSession.scope_type == scope.scope_type,
            AgentSession.scope_id == scope.scope_id,
            AgentSession.idempotency_key == key,
            AgentSession.status == "active",
        )
    ).first()


# ----- Concrete-session resolution (the permission chain of §5) -----


def get_session_for_action(
    db: Session,
    caller: User,
    spec: AgentSpec,
    session_id: uuid.UUID,
    expect: tuple[str, str] | None = None,
) -> ResolvedSession:
    """Full check chain for operating on one session: existence → binding →
    ownership policy → live business access, then load owner + scope.

    ``expect`` is the client's (scope_type, scope_id) assertion — a mismatch
    is a 404, never a re-route onto another executor or business object.
    """
    agent_session = db.get(AgentSession, session_id)
    if (
        agent_session is None
        or agent_session.status != "active"
        or agent_session.agent_key != spec.agent_key
    ):
        raise HTTPException(status_code=404, detail="Agent session not found")
    if expect is not None and (
        agent_session.scope_type != expect[0] or agent_session.scope_id != expect[1]
    ):
        raise HTTPException(status_code=404, detail="Agent session not found")
    if agent_session.user_id != caller.id and not (
        caller.is_superuser and spec.allow_superuser_session_access
    ):
        raise HTTPException(status_code=404, detail="Agent session not found")
    if agent_session.scope_type not in spec.allowed_scope_types:
        # defensive: drifted data never reaches an executor
        raise HTTPException(status_code=404, detail="Agent session not found")
    adapter = require_scope(agent_session.scope_type)
    scope = adapter.load(
        db, caller, agent_session.scope_id, manage=spec.scope_requires_manage
    )
    owner = db.get(User, agent_session.user_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Agent session not found")
    return ResolvedSession(agent_session, spec, scope, owner)


def ensure_state_compatible(spec: AgentSpec, agent_session: AgentSession) -> None:
    """Run gate for the state-version contract (§6.4, review finding #8).

    History reads stay allowed for older versions (the retention policy is
    explicit and separate); *continuing* a session on an incompatible graph
    is refused until a migration or a compat declaration exists.
    """
    if agent_session.state_version != spec.state_version:
        raise HTTPException(
            status_code=409,
            detail=(
                f"会话状态版本不兼容（会话 v{agent_session.state_version}，"
                f"当前图 v{spec.state_version}），该会话暂不能继续生成"
            ),
        )


# ----- Run lease (multi-worker mutex, §7.2 / §12.4) -----


def acquire_lease(
    db: Session, agent_session: AgentSession, *, ttl_seconds: int = LEASE_TTL_SECONDS
) -> str:
    """Take the session's run lease via one conditional UPDATE.

    Works across worker processes (no in-memory state); a crashed holder
    loses the lease at TTL expiry. Raises ``SessionBusyError`` if held.
    """
    token = uuid.uuid4().hex
    now = get_datetime_utc()
    result = db.execute(
        update(AgentSession)
        .where(
            AgentSession.id == agent_session.id,
            or_(
                AgentSession.run_token.is_(None),
                AgentSession.run_expires_at < now,
            ),
        )
        .values(run_token=token, run_expires_at=now + timedelta(seconds=ttl_seconds))
    )
    db.commit()
    if result.rowcount != 1:
        raise SessionBusyError("该会话正在回复，请稍候")
    return token


def release_lease(db: Session, session_id: uuid.UUID, token: str) -> None:
    """Best-effort release; a lost token just waits out the TTL."""
    db.execute(
        update(AgentSession)
        .where(AgentSession.id == session_id, AgentSession.run_token == token)
        .values(run_token=None, run_expires_at=None)
    )
    db.commit()


def renew_lease(
    db: Session, session_id: uuid.UUID, token: str, *, ttl_seconds: int = LEASE_TTL_SECONDS
) -> bool:
    """Extend our own lease; False means we lost it (expired + stolen)."""
    result = db.execute(
        update(AgentSession)
        .where(AgentSession.id == session_id, AgentSession.run_token == token)
        .values(run_expires_at=get_datetime_utc() + timedelta(seconds=ttl_seconds))
    )
    db.commit()
    return result.rowcount == 1


def renew_lease_standalone(
    session_id: uuid.UUID, token: str, *, ttl_seconds: int = LEASE_TTL_SECONDS
) -> bool:
    """Heartbeat helper for streaming runs: its own short-lived session, so
    the request-scoped Session is never shared with the heartbeat task."""
    with Session(engine) as db:
        return renew_lease(db, session_id, token, ttl_seconds=ttl_seconds)


async def lease_heartbeat(
    session_id: uuid.UUID,
    token: str,
    *,
    on_lost: Callable[[], None] | None = None,
) -> None:
    """Renew the lease every interval until cancelled (§7.2).

    ``on_lost`` fires when renewal fails — used to cancel the run the lease
    was protecting, so a stolen lease never leaves two writers on one thread.
    """
    while True:
        await asyncio.sleep(LEASE_HEARTBEAT_SECONDS)
        if not renew_lease_standalone(session_id, token):
            logger.warning("session_lease_lost", session_id=str(session_id))
            if on_lost is not None:
                on_lost()
            return


# Sentinels pumped through the stream runner's queue (never user text).
_STREAM_DONE = object()
_STREAM_LEASE_LOST = object()


async def run_exclusive(
    db: Session, agent_session: AgentSession, invoke: Callable[[], Awaitable[Any]]
) -> Any:
    """Run one non-streamed agent invocation under the session lease.

    The heartbeat renews for the whole (possibly minutes-long) generation;
    if the lease is lost the invocation task is cancelled and
    ``LeaseLostError`` propagates — never a second concurrent writer.
    """
    token = acquire_lease(db, agent_session)  # SessionBusyError → 409 upstream
    lost = False

    def _abort() -> None:
        nonlocal lost
        lost = True
        run_task.cancel()

    run_task = asyncio.create_task(invoke())
    heartbeat = asyncio.create_task(
        lease_heartbeat(agent_session.id, token, on_lost=_abort)
    )
    try:
        return await run_task
    except asyncio.CancelledError:
        if not lost:
            raise  # we were cancelled (client disconnect), not the lease
        raise LeaseLostError("会话租约已丢失，执行已中止") from None
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        release_lease(db, agent_session.id, token)


async def stream_exclusive(
    db: Session,
    agent_session: AgentSession,
    token: str,
    make_chunks: Callable[[], AsyncGenerator[str]],
) -> AsyncGenerator[str]:
    """Stream one agent run under an already-acquired lease.

    The agent consumption runs in a producer task pumping a queue; the
    heartbeat cancels that producer on lease loss, which surfaces here as
    ``LeaseLostError`` instead of silently writing into a stolen thread.
    Acquire the lease (and map ``SessionBusyError``) in the route BEFORE the
    StreamingResponse starts, so busy stays an HTTP 409.
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def produce() -> None:
        try:
            async for chunk in make_chunks():
                await queue.put(chunk)
        except asyncio.CancelledError:
            queue.put_nowait(_STREAM_LEASE_LOST)  # type: ignore[arg-type]
        except Exception as e:  # producer errors re-raised in the consumer
            queue.put_nowait(e)
        else:
            queue.put_nowait(_STREAM_DONE)  # type: ignore[arg-type]

    producer = asyncio.create_task(produce())
    heartbeat = asyncio.create_task(
        lease_heartbeat(agent_session.id, token, on_lost=producer.cancel)
    )
    try:
        while True:
            item = await queue.get()
            if item is _STREAM_DONE:
                return
            if item is _STREAM_LEASE_LOST:
                raise LeaseLostError("会话租约已丢失，执行已中止")
            if isinstance(item, BaseException):
                raise item
            yield item  # type: ignore[misc]
    finally:
        heartbeat.cancel()
        producer.cancel()
        await asyncio.gather(heartbeat, producer, return_exceptions=True)
        release_lease(db, agent_session.id, token)


# ----- Mutation -----


def rename_session(db: Session, agent_session: AgentSession, title: str) -> AgentSession:
    agent_session.title = title
    agent_session.updated_at = get_datetime_utc()
    db.add(agent_session)
    db.commit()
    db.refresh(agent_session)
    return agent_session


def touch_session(
    db: Session, agent_session: AgentSession, first_user_content: str | None = None
) -> None:
    """Bump activity time; auto-title from the first message once (§12.6)."""
    agent_session.updated_at = get_datetime_utc()
    if not agent_session.title and first_user_content:
        agent_session.title = (
            first_user_content.strip().replace("\n", " ")[:AUTO_TITLE_MAX_CHARS]
        )
    db.add(agent_session)
    db.commit()


async def clear_session_history(db: Session, resolved: ResolvedSession) -> None:
    """Clear checkpoints but keep the session row (legacy chat endpoint)."""
    token = acquire_lease(db, resolved.session)
    try:
        await resolved.spec.executor.clear_chat_history(resolved.session.thread_id)
    finally:
        release_lease(db, resolved.session.id, token)
    touch_session(db, resolved.session)


async def delete_session(
    db: Session,
    caller: User,
    spec: AgentSpec,
    session_id: uuid.UUID,
    expect: tuple[str, str] | None = None,
) -> None:
    """Lease → clear checkpoints → drop the identity row (§12.11).

    Deliberately NO intermediate ``status='deleting'`` commit (review finding
    #3): a crash between clearing checkpoints and dropping the row must leave
    a plain 'active' session with empty history — a legal state the owner can
    see and delete again — not a row stranded behind an "active-only" gate.
    The lease is what excludes concurrent runs, not the status flag.
    """
    resolved = get_session_for_action(db, caller, spec, session_id, expect=expect)
    token = acquire_lease(db, resolved.session)
    try:
        await resolved.spec.executor.clear_chat_history(resolved.session.thread_id)
        db.delete(resolved.session)
        db.commit()
    finally:
        release_lease(db, resolved.session.id, token)


# ----- Cleanup hooks for deletion flows (§5, §12.11) -----


async def purge_scope_sessions(
    db: Session, scope_type: str, scope_ids: Iterable[str]
) -> int:
    """Delete sessions bound to gone business objects, checkpoints included.

    Called from course/chapter deletion: the generic ``scope_id`` column has
    no FK cascade, so this is the only cleanup path. A concurrently running
    generation may still write checkpoint rows afterwards — they become
    invisible orphans (accepted edge, see plan §7.2 delete/running race).
    """
    ids = list(scope_ids)
    if not ids:
        return 0
    rows = db.exec(
        select(AgentSession).where(
            AgentSession.scope_type == scope_type,
            col(AgentSession.scope_id).in_(ids),
        )
    ).all()
    await _purge_rows(db, rows)
    return len(rows)


async def purge_user_sessions(db: Session, user_id: uuid.UUID) -> int:
    rows = db.exec(
        select(AgentSession).where(AgentSession.user_id == user_id)
    ).all()
    await _purge_rows(db, rows)
    return len(rows)


async def _purge_rows(db: Session, rows: list[AgentSession]) -> None:
    from app.core.langgraph.graph import langgraph_agent

    for agent_session in rows:
        spec = get_agent(agent_session.agent_key)
        # both agents' pools hit the same checkpoint tables, so the chat
        # agent's pool is a safe fallback for unknown keys (drifted data)
        executor = spec.executor if spec is not None else langgraph_agent
        await executor.clear_chat_history(agent_session.thread_id)
        db.delete(agent_session)
    db.commit()
    if rows:
        logger.info("agent_sessions_purged", count=len(rows))
