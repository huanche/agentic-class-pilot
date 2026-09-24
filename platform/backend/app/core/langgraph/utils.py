"""Message-handling helpers for the LangGraph agent.

Ported from the vendor template ``app/utils/graph.py``. Adaptations:
- lives under ``core/langgraph/`` (our backend has a flat ``app/utils.py``,
  and these helpers are graph-specific);
- trim budget reads ``LLM_CONTEXT_TOKENS`` (context window) instead of the
  template's ``MAX_TOKENS`` (which, in our config, caps generation output).

Types are wider than ``Message`` on purpose: the graph state stores LangChain
``BaseMessage`` objects, and both it and our schema are pydantic models, so
``model_dump``-based helpers accept either (see ``prepare_messages``).
"""

import asyncio
from collections.abc import Sequence
from typing import Any

import tiktoken
from langchain_core.messages import (
    BaseMessage,
    SystemMessage,
    ToolMessage,
    convert_to_openai_messages,
)
from langchain_core.messages import trim_messages as _trim_messages
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import logger
from app.schemas.chat import HistoryMessage

# Cache tiktoken encoding at module level — thread-safe and reusable.
# DeepSeek model names are unknown to tiktoken, so the KeyError fallback to
# cl100k_base is the expected path here (approximate count, good enough for
# trimming).
try:
    _TIKTOKEN_ENCODING = tiktoken.encoding_for_model(settings.DEFAULT_LLM_MODEL)
except KeyError:
    _TIKTOKEN_ENCODING = tiktoken.get_encoding("cl100k_base")


def _count_tokens_tiktoken(messages: list) -> int:
    """Count tokens locally using tiktoken — no API call needed."""
    num_tokens = 0
    for message in messages:
        # Every message has overhead tokens for role/name
        num_tokens += 4
        if isinstance(message, dict):
            for _, value in message.items():
                if isinstance(value, str):
                    num_tokens += len(_TIKTOKEN_ENCODING.encode(value))
        elif isinstance(message, BaseMessage):
            content = message.content
            if isinstance(content, str):
                num_tokens += len(_TIKTOKEN_ENCODING.encode(content))
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, str):
                        num_tokens += len(_TIKTOKEN_ENCODING.encode(block))
                    elif isinstance(block, dict) and "text" in block:
                        num_tokens += len(_TIKTOKEN_ENCODING.encode(block["text"]))
    num_tokens += 2  # every reply is primed with assistant
    return num_tokens


def dump_messages(messages: Sequence[BaseModel]) -> list[dict[str, Any]]:
    """Dump the messages to a list of dictionaries via ``model_dump``."""
    return [message.model_dump() for message in messages]


def extract_text_content(content: str | list) -> str:
    """Extract plain text from an LLM content value.

    Handles both the simple string format and the structured block list
    returned by GPT-5 / Responses API models:
        [{'type': 'reasoning', ...}, {'type': 'text', 'text': '...'}]

    Returns:
        Plain text string (empty string when nothing extractable is present).
    """
    if isinstance(content, str):
        return content

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif block.get("type") == "reasoning":
                logger.debug(
                    "reasoning_block_received",
                    reasoning_id=block.get("id"),
                    has_summary=bool(block.get("summary")),
                )
    return "".join(parts)


def process_llm_response(response: BaseMessage) -> BaseMessage:
    """Normalise a raw LLM response so ``content`` is always a plain string."""
    if isinstance(response.content, list):
        response.content = extract_text_content(response.content)
        logger.debug(
            "processed_structured_content",
            extracted_length=len(response.content),
        )
    return response


def prepare_messages(
    messages: Sequence[BaseModel], system_prompt: str
) -> list[BaseModel]:
    """Prepare the messages for the LLM: trim history to the token budget,
    then prepend the system prompt.

    ``trim_messages`` converts dict input back to LangChain messages, so the
    result is plain ``BaseMessage`` objects throughout — they dump to dicts
    the LLM client accepts.

    Unrecognized content blocks (e.g. reasoning blocks from GPT-5 style
    models) make token counting raise; in that case we skip trimming rather
    than fail the call.
    """
    trimmed: list[BaseModel]
    try:
        trimmed = list(
            _trim_messages(
                dump_messages(messages),
                strategy="last",
                token_counter=_count_tokens_tiktoken,
                max_tokens=settings.LLM_CONTEXT_TOKENS,
                start_on="human",
                include_system=False,
                allow_partial=False,
            )
        )
    except ValueError as e:
        if "Unrecognized content block type" in str(e):
            logger.warning(
                "token_counting_failed_skipping_trim",
                error=str(e),
                message_count=len(messages),
            )
            # Skip trimming and return all messages
            trimmed = list(messages)
        else:
            raise

    # A LangChain SystemMessage, NOT our input ``Message`` model: the
    # rendered prompt (chapter courseware can be large) legitimately exceeds
    # the 3000-char *input* cap, which made big-context chapters fail
    # validation inside _chat (inventory gap #1, internal side).
    return [SystemMessage(content=system_prompt), *trimmed]


async def execute_tool_calls(
    tool_calls: list[dict[str, Any]],
    tools_by_name: dict[str, Any],
) -> list[ToolMessage]:
    """Execute the last AI message's tool calls and pair each result.

    Multiple calls run concurrently via ``asyncio.gather``; a single call
    skips the gather overhead (the common case).
    """

    async def _execute_tool(tool_call: dict[str, Any]) -> ToolMessage:
        tool_result = await tools_by_name[tool_call["name"]].ainvoke(
            tool_call["args"]
        )
        return ToolMessage(
            content=tool_result,
            name=tool_call["name"],
            tool_call_id=tool_call["id"],
        )

    if len(tool_calls) == 1:
        return [await _execute_tool(tool_calls[0])]
    return list(await asyncio.gather(*[_execute_tool(tc) for tc in tool_calls]))


def to_history_messages(messages: list[BaseMessage]) -> list[HistoryMessage]:
    """Convert graph messages to the API ``HistoryMessage`` shape.

    Keeps just assistant and user messages; ``HistoryMessage`` (not the
    input ``Message``) so replies longer than the 3000-char input cap don't
    fail validation. Tool/system turns are dropped from API responses.
    """
    openai_style_messages = convert_to_openai_messages(messages)
    return [
        HistoryMessage(role=message["role"], content=str(message["content"]))
        for message in openai_style_messages
        if message["role"] in ["assistant", "user"] and message["content"]
    ]
