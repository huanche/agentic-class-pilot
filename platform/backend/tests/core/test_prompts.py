"""Tests for the prompt template loader (variable injection pipeline)."""

import re

from app.core.config import settings
from app.core.prompts import SESSION_TITLE_PROMPT, load_system_prompt


def test_load_system_prompt_injects_all_placeholders() -> None:
    prompt = load_system_prompt(
        "小张",
        long_term_memory="* 正在学习《数据结构》",
        chapter_context="【场景：二分查找】讲解：……",
    )
    assert f"{settings.PROJECT_NAME} 智能助教" in prompt
    assert "你正在与 小张 对话" in prompt
    assert "正在学习《数据结构》" in prompt
    assert "【场景：二分查找】" in prompt
    # datetime placeholder rendered as YYYY-MM-DD HH:MM:SS
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", prompt)
    # No unresolved placeholder survives
    assert "{" not in prompt


def test_load_system_prompt_without_username_has_no_user_context() -> None:
    prompt = load_system_prompt()
    assert "你正在与" not in prompt
    assert "{" not in prompt


def test_session_title_prompt_is_loaded() -> None:
    assert "标题" in SESSION_TITLE_PROMPT
