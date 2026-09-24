"""Request schema for the outline endpoints.

Responses reuse ``schemas/chat`` (``ChatResponse``/``HistoryMessage``) —
they are generic message-list envelopes, identical in shape for both
agents.
"""

import uuid

from pydantic import BaseModel, Field

from app.schemas.chat import Message


class OutlineChatRequest(BaseModel):
    """One outline turn: the course the outline is for, plus the newest message."""

    course_id: uuid.UUID
    messages: list[Message] = Field(min_length=1)
