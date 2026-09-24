"""Unified agent-session API: every agent behind one set of endpoints.

Scope-first contract (docs/agent-isolation-plan.md §4.3): list/resolve/create
take (agent_key, scope); concrete-session operations additionally carry the
expected agent/scope as a consistency assertion (query params on the
read/write-pure ops, body fields alongside the message on sends). The
assertion can never re-route a session — a mismatch is a 404.

Legacy migration entrance: ``POST /outline/import-hints`` imports a teacher's
localStorage thread map after server-side verification (§8.2, §12.7).
"""

import uuid
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.deps import CurrentUser, SessionDep, TeacherUser
from app.api.sse import sse_frames
from app.core.langgraph.outline import outline_agent
from app.core.logging import logger
from app.core.config import settings
from app.models import (
    AgentSession,
    AgentSessionPublic,
    AgentSessionsPublic,
    Message,
)
from app.schemas.agent_sessions import (
    AgentMessageRequest,
    AgentSessionCreateRequest,
    AgentSessionResolveRequest,
    AgentSessionUpdateRequest,
    OutlineImportRequest,
    OutlineImportResult,
)
from app.schemas.chat import ChatResponse, HistoryMessage
from app.schemas.chat import Message as ChatMessage
from app.services import agent_sessions
from app.services.agent_registry import require_agent
from app.services.agent_sessions import LeaseLostError, SessionBusyError
from app.services.course_access import get_owned_course

router = APIRouter(prefix="/agent-sessions", tags=["agent-sessions"])

# streaming error copy per agent family, mirroring the legacy routes
_STREAM_ERROR_TEXT = {
    "chat": "对话服务暂时不可用，请稍后重试",
    "outline": "大纲服务暂时不可用，请稍后重试",
}


def _latest_user_message(messages: list[ChatMessage]) -> ChatMessage:
    """The single message forwarded to the agent: the newest, role=user one."""
    latest = messages[-1]
    if latest.role != "user":
        raise HTTPException(status_code=422, detail="最新一条消息必须是 user 角色")
    return latest


def _acquire_or_409(db: Session, agent_session: AgentSession) -> str:
    try:
        return agent_sessions.acquire_lease(db, agent_session)
    except SessionBusyError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


def _run_gate(resolved: agent_sessions.ResolvedSession) -> None:
    """Checks every send入口 shares before executing: state-version gate."""
    if not settings.EMBEDDED_AGENTS_ENABLED:
        raise HTTPException(status_code=503, detail="请从平台首页进入独立教师工作台；学生 Agent 尚未接入。")
    agent_sessions.ensure_state_compatible(resolved.spec, resolved.session)


# ----- Scope-level operations (no concrete session yet) -----


@router.get("", response_model=AgentSessionsPublic)
def list_agent_sessions(
    session: SessionDep,
    current_user: CurrentUser,
    agent_key: str,
    scope_type: str,
    scope_id: str,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """List the caller's own sessions in one scope — read-only, never creates."""
    spec, scope = agent_sessions.resolve_scope(
        session, current_user, agent_key, scope_type, scope_id
    )
    data, count = agent_sessions.list_sessions(session, current_user, spec, scope, skip=skip, limit=limit)
    return AgentSessionsPublic(
        data=[AgentSessionPublic.model_validate(s) for s in data], count=count
    )


@router.post("/resolve", response_model=AgentSessionPublic | None)
def resolve_agent_session(
    session: SessionDep,
    current_user: CurrentUser,
    body: AgentSessionResolveRequest,
) -> Any:
    """Pick the session to show: the exact preferred one (404 if stale — the
    client drops its preference and retries) or the most recently active.
    Returns null when the scope has no sessions yet — no creation here."""
    spec, scope = agent_sessions.resolve_scope(
        session, current_user, body.agent_key, body.scope.type, body.scope.id
    )
    picked = agent_sessions.pick_session(
        session, current_user, spec, scope, body.preferred_session_id
    )
    return AgentSessionPublic.model_validate(picked) if picked else None


@router.post("", response_model=AgentSessionPublic, status_code=201)
def create_agent_session(
    session: SessionDep,
    current_user: CurrentUser,
    body: AgentSessionCreateRequest,
) -> Any:
    """Explicit new session; ``idempotency_key`` makes first-send retries safe."""
    spec, scope = agent_sessions.resolve_scope(
        session, current_user, body.agent_key, body.scope.type, body.scope.id
    )
    created = agent_sessions.create_session(
        session, current_user, spec, scope, body.idempotency_key
    )
    return AgentSessionPublic.model_validate(created)


# ----- Concrete-session operations -----


def _resolved_with_assertion(
    db: Session,
    caller: Any,
    session_id: uuid.UUID,
    agent_key: str,
    scope_type: str,
    scope_id: str,
) -> agent_sessions.ResolvedSession:
    spec = require_agent(agent_key)
    return agent_sessions.get_session_for_action(
        db, caller, spec, session_id, expect=(scope_type, scope_id)
    )


@router.get("/{session_id}", response_model=AgentSessionPublic)
def read_agent_session(
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    agent_key: str,
    scope_type: str,
    scope_id: str,
) -> Any:
    resolved = _resolved_with_assertion(
        session, current_user, session_id, agent_key, scope_type, scope_id
    )
    return AgentSessionPublic.model_validate(resolved.session)


@router.get("/{session_id}/messages", response_model=ChatResponse)
async def read_agent_session_messages(
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    agent_key: str,
    scope_type: str,
    scope_id: str,
) -> Any:
    """History served from the checkpoint thread the session row points at."""
    resolved = _resolved_with_assertion(
        session, current_user, session_id, agent_key, scope_type, scope_id
    )
    messages = await resolved.spec.executor.get_chat_history(
        resolved.session.thread_id
    )
    return ChatResponse(messages=messages)


@router.patch("/{session_id}", response_model=AgentSessionPublic)
def update_agent_session(
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    body: AgentSessionUpdateRequest,
    agent_key: str,
    scope_type: str,
    scope_id: str,
) -> Any:
    resolved = _resolved_with_assertion(
        session, current_user, session_id, agent_key, scope_type, scope_id
    )
    renamed = agent_sessions.rename_session(session, resolved.session, body.title)
    return AgentSessionPublic.model_validate(renamed)


@router.delete("/{session_id}", response_model=Message)
async def delete_agent_session(
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    agent_key: str,
    scope_type: str,
    scope_id: str,
) -> Any:
    """Lease-guarded delete: checkpoints first, then the identity row."""
    spec = require_agent(agent_key)
    try:
        await agent_sessions.delete_session(
            session,
            current_user,
            spec,
            session_id,
            expect=(scope_type, scope_id),
        )
    except SessionBusyError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return Message(message="Agent session deleted successfully")


@router.post("/{session_id}/messages", response_model=ChatResponse)
async def send_agent_session_message(
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    body: AgentMessageRequest,
) -> Any:
    """Send one user message; returns the full conversation history."""
    latest = _latest_user_message(body.messages)  # 422 before any side effect
    resolved = _resolved_with_assertion(
        session,
        current_user,
        session_id,
        body.agent_key,
        body.scope_type,
        body.scope_id,
    )
    _run_gate(resolved)
    try:
        result = await agent_sessions.run_exclusive(
            session,
            resolved.session,
            lambda: resolved.spec.invoke(
                [latest],
                resolved.session.thread_id,
                owner=resolved.owner,
                context=resolved.spec.build_context(session, resolved.scope),
            ),
        )
    except (SessionBusyError, LeaseLostError) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        logger.exception(
            "agent_request_failed",
            agent_key=resolved.spec.agent_key,
            session_id=str(session_id),
            user_id=str(current_user.id),
            error=str(e),
        )
        raise HTTPException(status_code=502, detail="服务暂时不可用，请稍后重试") from e
    agent_sessions.touch_session(session, resolved.session, latest.content)
    return ChatResponse(messages=result)


@router.post("/{session_id}/messages/stream")
async def send_agent_session_message_stream(
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    body: AgentMessageRequest,
) -> Any:
    """Send one user message; streams the reply as SSE ``data:`` frames.

    Same frame protocol as the legacy routes (api/sse.py): token frames,
    then always a ``done=true`` frame. The run lease is held for the whole
    stream with a heartbeat renewing it (§7.2/§12.4).
    """
    latest = _latest_user_message(body.messages)  # 422 before headers are sent
    resolved = _resolved_with_assertion(
        session,
        current_user,
        session_id,
        body.agent_key,
        body.scope_type,
        body.scope_id,
    )
    _run_gate(resolved)
    # acquire (and map busy → 409) before the response starts; the runner
    # then owns heartbeat + release + abort-on-lease-loss for the whole stream
    token = _acquire_or_409(session, resolved.session)
    context = resolved.spec.build_context(session, resolved.scope)
    thread_id = resolved.session.thread_id

    async def token_gen():
        run = agent_sessions.stream_exclusive(
            session,
            resolved.session,
            token,
            lambda: resolved.spec.stream(
                [latest], thread_id, owner=resolved.owner, context=context
            ),
        )
        async for chunk in run:
            yield chunk
        agent_sessions.touch_session(session, resolved.session, latest.content)

    return StreamingResponse(
        sse_frames(
            token_gen(),
            error_text=_STREAM_ERROR_TEXT.get(
                body.agent_key, "服务暂时不可用，请稍后重试"
            ),
            log_event="stream_agent_request_failed",
            session_id=thread_id,
            user_id=str(current_user.id),
        ),
        media_type="text/event-stream",
    )


# ----- Legacy outline import (one-shot, §8.2 / §12.7) -----


@router.post("/outline/import-hints", response_model=OutlineImportResult)
async def import_outline_hints(
    session: SessionDep,
    teacher: TeacherUser,
    body: OutlineImportRequest,
) -> Any:
    """Import legacy ``outline:{teacher}:{uuid}`` threads reported by the
    teacher's browser. Each hint is verified (course ownership, non-empty
    checkpoint, no ambiguous multi-course uuid, not yet imported); failures
    are skipped, leaving the checkpoint rows untouched as 待归类 history."""
    imported = skipped = 0
    uuid_courses: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for hint in body.hints:
        uuid_courses[hint.thread_uuid].add(hint.course_id)

    for hint in body.hints:
        thread_id = f"outline:{teacher.id}:{hint.thread_uuid}"
        if len(uuid_courses[hint.thread_uuid]) > 1:
            skipped += 1  # ambiguous binding → 待归类, never guess
            continue
        try:
            course = get_owned_course(session, teacher, hint.course_id)
        except HTTPException:
            skipped += 1
            continue
        already = session.exec(
            select(AgentSession).where(AgentSession.thread_id == thread_id)
        ).first()
        if already is not None:
            skipped += 1
            continue
        if not await outline_agent.thread_has_history(thread_id):
            skipped += 1  # fresh-uuid threads were never used (§12.8)
            continue
        title = await _legacy_outline_title(thread_id, course.title)
        session.add(
            AgentSession(
                user_id=teacher.id,
                agent_key="outline",
                scope_type="course",
                scope_id=str(course.id),
                thread_id=thread_id,  # legacy format kept, never rewritten
                title=title,
            )
        )
        try:
            session.commit()
            imported += 1
        except IntegrityError:
            session.rollback()  # concurrent import of the same thread
            skipped += 1
    return OutlineImportResult(imported=imported, skipped=skipped)


async def _legacy_outline_title(thread_id: str, course_title: str) -> str:
    """Same auto-title rule as new sessions: first user message, truncated."""
    try:
        history: list[HistoryMessage] = await outline_agent.get_chat_history(thread_id)
    except Exception:
        history = []
    for message in history:
        if message.role == "user" and message.content.strip():
            return message.content.strip().replace("\n", " ")[
                : agent_sessions.AUTO_TITLE_MAX_CHARS
            ]
    return f"{course_title}（历史）"
