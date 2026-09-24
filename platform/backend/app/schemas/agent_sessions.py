"""Request/response schemas for the unified agent-session API.

The unified API is scope-first: callers describe *where* they want to work
(agent + business scope) and the backend resolves the concrete session
(docs/agent-isolation-plan.md §4). Concrete-session operations additionally
carry the expected agent/scope as a consistency assertion — a mismatch is a
404, never a silent switch (plan §4.3).
"""

import uuid

from pydantic import BaseModel, Field

from app.schemas.chat import Message


class AgentSessionScope(BaseModel):
    """The business object a session lives under, as the client states it.

    Both fields are untrusted input until the backend loads the real object
    through the scope adapter (plan §4.2).
    """

    type: str = Field(max_length=50)
    id: str = Field(max_length=64)


class AgentSessionResolveRequest(BaseModel):
    """Read-only "which session should I show" lookup — no creation side effect."""

    agent_key: str = Field(max_length=50)
    scope: AgentSessionScope
    preferred_session_id: uuid.UUID | None = None


class AgentSessionCreateRequest(BaseModel):
    """Explicit new-session creation; ``idempotency_key`` dedups retries."""

    agent_key: str = Field(max_length=50)
    scope: AgentSessionScope
    idempotency_key: str | None = Field(default=None, max_length=100)


class AgentSessionAssertion(BaseModel):
    """Expected agent/scope for concrete-session operations (plan §4.3).

    Must equal the session record's own binding; the assertion can never
    re-route a session onto another executor or business object.
    """

    agent_key: str = Field(max_length=50)
    scope_type: str = Field(max_length=50)
    scope_id: str = Field(max_length=64)


class AgentMessageRequest(AgentSessionAssertion):
    """One send: the newest user-role message plus the consistency assertion."""

    messages: list[Message] = Field(min_length=1)


class AgentSessionUpdateRequest(BaseModel):
    """Manual title rename."""

    title: str = Field(min_length=1, max_length=255)


class OutlineImportHint(BaseModel):
    """One (course, thread) pair reported from a teacher's localStorage."""

    course_id: uuid.UUID
    thread_uuid: uuid.UUID


class OutlineImportRequest(BaseModel):
    """One-shot legacy outline thread report (plan §8.2, decision 12.7)."""

    hints: list[OutlineImportHint] = Field(max_length=50)


class OutlineImportResult(BaseModel):
    imported: int
    skipped: int
