"""Agent registry and scope adapters (docs/agent-isolation-plan.md §6, §12.13).

Single server-side place that declares "which agents exist, which business
scopes they may bind to, and how a conversation is executed". New agents
register here instead of growing their own session/thread/history rules.

Two deliberate non-features: no plugin loading (code registration only) and
no sandbox — the registry constrains trusted first-party code, per plan §6.1.
"""

from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.langgraph.graph import langgraph_agent
from app.core.langgraph.outline import outline_agent
from app.models import Chapter, Course, User
from app.schemas.chat import HistoryMessage, Message
from app.services.course_access import get_accessible_course, get_owned_course


def _parse_uuid(raw: str, what: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"{what} not found") from None


# ----- Scope adapters: load + access-check a business object -----


@dataclass(frozen=True)
class ScopeContext:
    """A loaded, access-checked business object a session may bind to."""

    scope_type: str
    scope_id: str
    resource: Any  # Chapter / Course / User — agent-agnostic
    course_id: UUID | None = None  # parent course of a chapter scope


@dataclass(frozen=True)
class ScopeAdapter:
    """Normalize a scope id and load its real object with the caller's access.

    ``manage`` selects the access level the requesting agent demands on the
    resource (read vs. manage, plan §6.1): chat needs read access to a
    chapter's course, the outline agent needs course ownership.
    """

    scope_type: str
    load: Callable[..., ScopeContext]


def _load_chapter(db: Session, user: User, scope_id: str, *, manage: bool) -> ScopeContext:
    chapter = db.get(Chapter, _parse_uuid(scope_id, "Chapter"))
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    if manage:
        get_owned_course(db, user, chapter.course_id)
    else:
        get_accessible_course(db, user, chapter.course_id)
    return ScopeContext("chapter", str(chapter.id), chapter, chapter.course_id)


def _load_course(db: Session, user: User, scope_id: str, *, manage: bool) -> ScopeContext:
    course = db.get(Course, _parse_uuid(scope_id, "Course"))
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if manage:
        get_owned_course(db, user, course.id)
    else:
        get_accessible_course(db, user, course.id)
    return ScopeContext("course", str(course.id), course)


def _load_user(db: Session, user: User, scope_id: str, *, manage: bool) -> ScopeContext:
    del manage  # personal namespace — access is the session-owner rule, not a course rule
    target = db.get(User, _parse_uuid(scope_id, "User"))
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    # the user scope binds to the caller's own namespace; the superuser read
    # exception for chat sessions is preserved, everyone else gets the
    # indistinguishable 404
    if target.id != user.id and not user.is_superuser:
        raise HTTPException(status_code=404, detail="User not found")
    return ScopeContext("user", str(target.id), target)


# ----- Agent specs -----


@dataclass(frozen=True)
class AgentSpec:
    """Everything the unified session service needs to run one agent."""

    agent_key: str
    display_name: str
    allowed_scope_types: frozenset[str]
    # access level this agent demands on the scope resource (read vs. manage)
    scope_requires_manage: bool
    # chat keeps the legacy superuser session-access exception; outline does
    # not — cross-teacher outline history has no entrance, not even for admins
    allow_superuser_session_access: bool
    state_version: int
    executor: Any  # agent instance: get_chat_history / clear_chat_history / thread_has_history
    invoke: Callable[..., Awaitable[list[HistoryMessage]]]
    stream: Callable[..., AsyncGenerator[str]]
    build_context: Callable[[Session, ScopeContext], str]


async def _chat_invoke(
    messages: list[Message], thread_id: str, *, owner: User, context: str
) -> list[HistoryMessage]:
    return await langgraph_agent.get_response(
        messages,
        thread_id,
        user_id=str(owner.id),
        username=owner.full_name,
        chapter_context=context,
    )


def _chat_stream(
    messages: list[Message], thread_id: str, *, owner: User, context: str
) -> AsyncGenerator[str]:
    return langgraph_agent.get_stream_response(
        messages,
        thread_id,
        user_id=str(owner.id),
        username=owner.full_name,
        chapter_context=context,
    )


def _chat_context(db: Session, scope: ScopeContext) -> str:
    """Chapter title/description for chapter scopes; empty for personal chat."""
    del db  # the chapter is already loaded in the scope context
    if scope.scope_type != "chapter":
        return ""
    chapter: Chapter = scope.resource
    return f"章节标题：{chapter.title}\n章节说明：{chapter.description or '无'}"


async def _outline_invoke(
    messages: list[Message], thread_id: str, *, owner: User, context: str
) -> list[HistoryMessage]:
    return await outline_agent.get_response(
        messages, thread_id, username=owner.full_name, course_context=context
    )


def _outline_stream(
    messages: list[Message], thread_id: str, *, owner: User, context: str
) -> AsyncGenerator[str]:
    return outline_agent.get_stream_response(
        messages, thread_id, username=owner.full_name, course_context=context
    )


def _outline_context(db: Session, scope: ScopeContext) -> str:
    """Course title/description plus its chapters in teaching order."""
    course: Course = scope.resource
    chapters = db.exec(
        select(Chapter)
        .where(Chapter.course_id == course.id)
        .order_by(Chapter.order_index)  # type: ignore
    ).all()
    chapter_lines = "\n".join(
        f"- {(c.order_index or 0) + 1}. {c.title}：{c.description or '无说明'}"
        for c in chapters
    )
    return (
        f"课程标题：{course.title}\n"
        f"课程描述：{course.description or '无'}\n"
        f"章节列表：\n{chapter_lines or '- （该课程暂无章节）'}"
    )


# ----- The registry itself -----

_AGENTS: dict[str, AgentSpec] = {}
_SCOPES: dict[str, ScopeAdapter] = {}


def register_scope(adapter: ScopeAdapter) -> None:
    if adapter.scope_type in _SCOPES:
        raise RuntimeError(f"duplicate scope adapter: {adapter.scope_type}")
    _SCOPES[adapter.scope_type] = adapter


def register_agent(spec: AgentSpec) -> None:
    if spec.agent_key in _AGENTS:
        raise RuntimeError(f"duplicate agent_key: {spec.agent_key}")
    missing = spec.allowed_scope_types - _SCOPES.keys()
    if missing:
        raise RuntimeError(
            f"agent {spec.agent_key} references unregistered scopes: {sorted(missing)}"
        )
    _AGENTS[spec.agent_key] = spec


register_scope(ScopeAdapter("chapter", _load_chapter))
register_scope(ScopeAdapter("course", _load_course))
register_scope(ScopeAdapter("user", _load_user))

register_agent(
    AgentSpec(
        agent_key="chat",
        display_name="章节问答",
        allowed_scope_types=frozenset({"chapter", "user"}),
        scope_requires_manage=False,
        allow_superuser_session_access=True,
        state_version=1,
        executor=langgraph_agent,
        invoke=_chat_invoke,
        stream=_chat_stream,
        build_context=_chat_context,
    )
)
register_agent(
    AgentSpec(
        agent_key="outline",
        display_name="教学大纲",
        allowed_scope_types=frozenset({"course"}),
        scope_requires_manage=True,
        allow_superuser_session_access=False,
        state_version=1,
        executor=outline_agent,
        invoke=_outline_invoke,
        stream=_outline_stream,
        build_context=_outline_context,
    )
)


def validate_registry() -> None:
    """Startup sanity check (plan §6.4): every agent is runnable as declared."""
    if not _AGENTS:
        raise RuntimeError("agent registry is empty")
    for spec in _AGENTS.values():
        missing = spec.allowed_scope_types - _SCOPES.keys()
        if missing:
            raise RuntimeError(
                f"agent {spec.agent_key} references unregistered scopes: {sorted(missing)}"
            )
        for op in ("get_chat_history", "clear_chat_history", "thread_has_history"):
            if not hasattr(spec.executor, op):
                raise RuntimeError(
                    f"agent {spec.agent_key} executor lacks {op}"
                )


def get_agent(agent_key: str) -> AgentSpec | None:
    return _AGENTS.get(agent_key)


def require_agent(agent_key: str) -> AgentSpec:
    """Unknown or unregistered agents never fall back to another graph."""
    spec = _AGENTS.get(agent_key)
    if spec is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return spec


def require_scope(scope_type: str) -> ScopeAdapter:
    adapter = _SCOPES.get(scope_type)
    if adapter is None:
        raise HTTPException(status_code=404, detail="Scope type not found")
    return adapter
