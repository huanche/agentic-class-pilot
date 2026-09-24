"""Graph state definition for the LangGraph agent (ported from vendor template).

``messages`` uses the ``add_messages`` reducer so each node's partial updates
append by message id instead of replacing history; ``long_term_memory`` is
intentionally a plain field so every invocation overwrites it with the freshly
retrieved memory.
"""

from typing import Annotated

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class GraphState(BaseModel):
    """State definition for the LangGraph agent/workflow."""

    messages: Annotated[list, add_messages] = Field(
        default_factory=list, description="The messages in the conversation"
    )
    long_term_memory: str = Field(
        default="", description="The long term memory of the conversation"
    )


class OutlineState(BaseModel):
    """State for the teaching-outline agent (the second graph).

    Messages only: revision turns replay through ``add_messages`` like the
    chat agent, and "the current outline" is simply the latest assistant
    message — the frontend renders it directly, so no structured draft
    field is needed.
    """

    messages: Annotated[list, add_messages] = Field(
        default_factory=list, description="The outline conversation messages"
    )
