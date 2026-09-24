"""Chat request/response schemas (ported from vendor template ``schemas/chat.py``).

Differences from upstream: no ``BaseResponse`` envelope (we return payload
models directly), otherwise identical validation semantics.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Message(BaseModel):
    """A single chat message crossing the API boundary."""

    model_config = {"extra": "ignore"}

    role: Literal["user", "assistant", "system"] = Field(
        ..., description="The role of the message sender"
    )
    content: str = Field(
        ..., description="The content of the message", min_length=1, max_length=3000
    )

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Reject script tags and null bytes at the input boundary."""
        if re.search(r"<script.*?>.*?</script>", v, re.IGNORECASE | re.DOTALL):
            raise ValueError("Content contains potentially harmful script tags")

        if "\0" in v:
            raise ValueError("Content contains null bytes")

        return v


class ChatRequest(BaseModel):
    """Request body for the chat endpoints."""

    messages: list[Message] = Field(
        ...,
        description="List of messages in the conversation",
        min_length=1,
    )


class HistoryMessage(BaseModel):
    """A message returned from the agent (chat history or reply).

    Distinct from :class:`Message` on purpose: the input model enforces the
    1-3000 length cap and script-tag hygiene on *user* input, while model
    replies and checkpoint history legitimately exceed that cap. Sharing one
    model made ``__process_messages`` raise on long replies (migration
    inventory gap #1).
    """

    model_config = {"extra": "ignore"}

    role: Literal["user", "assistant"] = Field(
        ..., description="The role of the message sender"
    )
    content: str = Field(..., description="The content of the message")


class ChatResponse(BaseModel):
    """Response payload for the non-streaming chat endpoint."""

    messages: list[HistoryMessage] = Field(..., description="List of messages in the reply")


class StreamResponse(BaseModel):
    """One SSE frame of the streaming chat endpoint.

    ``done`` is the in-stream termination signal: the SSE connection has no
    HTTP status code once opened, so both normal completion and errors are
    signalled through a final ``done=True`` frame.
    """

    content: str = Field(default="", description="The content of the current chunk")
    done: bool = Field(default=False, description="Whether the stream is complete")


class SessionTitle(BaseModel):
    """Structured-output schema for LLM session-title generation."""

    title: str = Field(
        ...,
        min_length=1,
        max_length=60,
    )

    @field_validator("title")
    @classmethod
    def _normalize(cls, v: str) -> str:
        v = " ".join(v.split()).strip(" \"'`.,:;!?-")
        if not v:
            raise ValueError("empty title after normalization")
        return v
