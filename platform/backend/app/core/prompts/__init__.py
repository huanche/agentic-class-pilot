"""Prompt templates for the chat agent.

Ported from the vendor template ``app/core/prompts/__init__.py``: templates
are read once at module load (no per-request file I/O) and rendered with
``str.format`` per call.

Upstream's generic assistant prompt is replaced by a Chinese teaching
assistant, with an added ``chapter_context`` placeholder so the chapter Q&A
flow (courseware text) can ride the same injection pipeline.
"""

from datetime import datetime
from pathlib import Path

from app.core.config import settings

_PROMPTS_DIR = Path(__file__).parent

# Read templates once at module load — no file I/O per request
_SYSTEM_PROMPT_TEMPLATE = (_PROMPTS_DIR / "system.md").read_text(encoding="utf-8")
_OUTLINE_PROMPT_TEMPLATE = (_PROMPTS_DIR / "outline.md").read_text(encoding="utf-8")
SESSION_TITLE_PROMPT = (_PROMPTS_DIR / "session_title.md").read_text(encoding="utf-8")


def load_system_prompt(
    username: str | None = None,
    *,
    long_term_memory: str = "",
    chapter_context: str = "",
) -> str:
    """Load the system prompt from the cached template.

    Args:
        username: Display name of the user, injected as personalised context.
        long_term_memory: Retrieved long-term memory for this user (empty
            until the memory service lands in migration step 4).
        chapter_context: Courseware text for chapter-scoped Q&A (empty for
            general chat).
    """
    user_context = f"# 用户\n你正在与 {username} 对话。\n" if username else ""
    return _SYSTEM_PROMPT_TEMPLATE.format(
        agent_name=f"{settings.PROJECT_NAME} 智能助教",
        current_date_and_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user_context=user_context,
        chapter_context=chapter_context,
        long_term_memory=long_term_memory,
    )


def load_outline_system_prompt(
    teacher_name: str | None = None,
    *,
    course_context: str = "",
) -> str:
    """Load the outline agent's system prompt from the cached template.

    Args:
        teacher_name: Display name of the teacher the outline is for.
        course_context: Course title/description and its chapter list,
            built by the outline route (rides config metadata like the
            chat agent's ``chapter_context``).
    """
    user_context = (
        f"# 用户\n你正在协助教师 {teacher_name} 设计教学大纲。\n" if teacher_name else ""
    )
    return _OUTLINE_PROMPT_TEMPLATE.format(
        agent_name=f"{settings.PROJECT_NAME} 教学设计助手",
        current_date_and_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user_context=user_context,
        course_context=course_context,
    )
