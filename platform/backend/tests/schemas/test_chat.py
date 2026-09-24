"""Validation tests for the chat schemas (ported from the vendor template)."""

import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatRequest, Message, SessionTitle


def test_message_accepts_valid_content() -> None:
    message = Message(role="user", content="什么是二分查找？")
    assert message.role == "user"
    assert message.content == "什么是二分查找？"


def test_message_rejects_script_tags() -> None:
    with pytest.raises(ValidationError, match="script tags"):
        Message(role="user", content="hello <script>alert(1)</script>")


def test_message_rejects_null_bytes() -> None:
    with pytest.raises(ValidationError, match="null bytes"):
        Message(role="assistant", content="bad\x00content")


def test_message_content_length_bounds() -> None:
    with pytest.raises(ValidationError):
        Message(role="user", content="")  # min_length=1
    with pytest.raises(ValidationError):
        Message(role="user", content="a" * 3001)  # max_length=3000
    assert Message(role="user", content="a" * 3000).content == "a" * 3000


def test_message_rejects_unknown_role() -> None:
    with pytest.raises(ValidationError):
        Message(role="tool", content="oops")  # type: ignore[arg-type]


def test_message_ignores_extra_fields() -> None:
    message = Message(role="user", content="hi", extra_field="ignored")
    assert "extra_field" not in message.model_dump()


def test_chat_request_requires_at_least_one_message() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(messages=[])
    assert len(ChatRequest(messages=[Message(role="user", content="hi")]).messages) == 1


def test_session_title_normalizes_whitespace_and_punctuation() -> None:
    title = SessionTitle(title='  " 二分查找   基础 ",. ')
    assert title.title == "二分查找 基础"


def test_session_title_rejects_empty_after_normalization() -> None:
    with pytest.raises(ValidationError, match="empty title"):
        SessionTitle(title='  "  "  ')


def test_session_title_rejects_overlong_title() -> None:
    with pytest.raises(ValidationError):
        SessionTitle(title="标" * 61)
