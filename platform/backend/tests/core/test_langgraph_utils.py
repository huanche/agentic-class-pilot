"""Tests for the graph message helpers (token counting / trimming / extraction).

Trim assertions are behavioural (kept vs dropped messages) rather than exact
token counts, so they stay stable across tokenizer revisions.
"""

from langchain_core.messages import AIMessage, SystemMessage

from app.core.langgraph.utils import (
    dump_messages,
    extract_text_content,
    prepare_messages,
    process_llm_response,
)
from app.schemas.chat import Message


def _history(count: int, filler: str = "a" * 400) -> list[Message]:
    return [
        Message(role="user" if i % 2 == 0 else "assistant", content=f"{filler} #{i}")
        for i in range(count)
    ]


def test_dump_messages_produces_role_content_dicts() -> None:
    dumped = dump_messages([Message(role="user", content="你好")])
    assert dumped == [{"role": "user", "content": "你好"}]


def test_extract_text_content_passthrough_for_plain_string() -> None:
    assert extract_text_content("纯文本") == "纯文本"


def test_extract_text_content_from_structured_blocks() -> None:
    content = [
        {"type": "reasoning", "id": "r1", "summary": []},
        "夹杂的字符串",
        {"type": "text", "text": "可见回答"},
    ]
    assert extract_text_content(content) == "夹杂的字符串可见回答"


def test_process_llm_response_flattens_block_content() -> None:
    response = AIMessage(content=[{"type": "text", "text": "你好"}])
    flattened = process_llm_response(response)
    assert flattened.content == "你好"


def test_process_llm_response_leaves_plain_content_untouched() -> None:
    response = AIMessage(content="已是纯文本")
    assert process_llm_response(response).content == "已是纯文本"


def test_prepare_messages_keeps_short_history_intact() -> None:
    history = _history(4, filler="短")
    result = prepare_messages(history, "系统提示词")
    assert isinstance(result[0], SystemMessage)
    assert result[0].content == "系统提示词"
    # system prompt + all 4 history messages
    assert len(result) == 5


def test_prepare_messages_trims_long_history_to_budget() -> None:
    history = _history(40)  # 40 × ~400 chars ≫ LLM_CONTEXT_TOKENS budget
    result = prepare_messages(history, "系统提示词")
    system_entry, trimmed = result[0], result[1:]
    assert isinstance(system_entry, SystemMessage)
    # history was cut down...
    assert len(trimmed) < 40
    # ...but the latest message always survives
    assert trimmed[-1].content.endswith(f" #{39}")
    # and the oldest messages were dropped
    assert all(not msg.content.endswith(" #0") for msg in trimmed)


def test_prepare_messages_allows_long_system_prompt() -> None:
    """Regression (inventory gap #1, internal side): chapter courseware pushes
    the rendered system prompt past the 3000-char *input* cap — building it
    as an input ``Message`` raised ValidationError inside the chat node."""
    big_prompt = "课" * 8000
    result = prepare_messages(_history(2, filler="短"), big_prompt)
    assert isinstance(result[0], SystemMessage)
    assert result[0].content == big_prompt
