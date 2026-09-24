# ruff: noqa: T201 — printing the verification transcript is this script's job
"""Acceptance check for the outline agent (the second LangGraph agent).

Runs BOTH agents against the real stack (DATABASE_URL Postgres + configured
LLM) and verifies, in order:

1. outline thread history accumulates across a generate -> revise turn;
2. the tool round-trip works (an explicit ask drives suggest_weekly_plan);
3. thread ownership by construction — the same uuid under another
   teacher's prefix resolves to an empty thread, and both agents coexist
   (note: the prefix is a namespace convention, not an access-control
   wall — see the comment in section 3);
4. the three checkpoint tables hold rows under the outline: namespace;
5. clear_chat_history removes them.

Run from ``backend/``:  uv run python scripts/verify_outline_agent.py
"""

import asyncio
import sys

# Windows console defaults to a legacy codepage (GBK) that can't render the
# ✓/✗ marks or some Chinese output below.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import psycopg

from app.core.config import settings
from app.core.langgraph.graph import LangGraphAgent
from app.core.langgraph.outline import OutlineAgent
from app.schemas.chat import Message

TEACHER_ID = "verify-outline-teacher"
OUTLINE_THREAD = f"outline:{TEACHER_ID}:11111111-1111-1111-1111-111111111111"
CHAT_THREAD = "verify-outline-chat-thread"

COURSE_CONTEXT = (
    "课程标题：线性代数\n"
    "课程描述：数学基础课\n"
    "章节列表：\n"
    "- 1. 行列式\n"
    "- 2. 矩阵"
)


def _count_outline_rows() -> dict[str, int]:
    """Count rows per checkpoint table in the outline namespace."""
    counts: dict[str, int] = {}
    with psycopg.connect(
        str(settings.DATABASE_URL).replace("+psycopg", "", 1)
    ) as conn:
        for table in settings.CHECKPOINT_TABLES:
            row = conn.execute(  # noqa: S608 - static table names from settings
                f"SELECT count(*) FROM {table} WHERE thread_id = %s",
                (OUTLINE_THREAD,),
            ).fetchone()
            counts[table] = row[0]
    return counts


async def main() -> int:
    outline = OutlineAgent()
    chat = LangGraphAgent()
    # Idempotent: creates the checkpoint tables on a fresh database, no-op
    # (fast IF NOT EXISTS) when they already exist.
    await outline.create_graph()
    await chat.create_graph()

    # Start clean so reruns (e.g. after a crash midway) are deterministic.
    await outline.clear_chat_history(OUTLINE_THREAD)
    await chat.clear_chat_history(CHAT_THREAD)

    # --- 1. outline turns accumulate (generate -> revise) -----------------
    turn1 = await outline.get_response(
        [Message(role="user", content="请为《线性代数》课程生成 48 学时的教学大纲。")],
        thread_id=OUTLINE_THREAD,
        username="验收教师",
        course_context=COURSE_CONTEXT,
    )
    print(f"[1] 第 1 轮回复（前 60 字）: {turn1[-1].content[:60]}")

    turn2 = await outline.get_response(
        [Message(role="user", content="请在第二单元后新增一个“特征值与特征向量”单元，输出完整最新版大纲。")],
        thread_id=OUTLINE_THREAD,
        username="验收教师",
        course_context=COURSE_CONTEXT,
    )
    print(f"[2] 第 2 轮回复（前 60 字）: {turn2[-1].content[:60]}")

    history = await outline.get_chat_history(OUTLINE_THREAD)
    roles = [m.role for m in history]
    print(f"[3] outline thread 历史: {roles}")
    accumulated = len(roles) >= 4 and "特征值" in turn2[-1].content
    print(f"[3] 历史累积 + 修订生效: {'✓' if accumulated else '✗'}")

    # --- 2. tool round-trip -------------------------------------------------
    tool_turn = await outline.get_response(
        [
            Message(
                role="user",
                content="请调用 suggest_weekly_plan 工具，计算 64 学时、16 教学周的分配方案。",
            )
        ],
        thread_id=OUTLINE_THREAD,
        username="验收教师",
        course_context=COURSE_CONTEXT,
    )
    reply = tool_turn[-1].content
    print(f"[4] 工具往返回复（前 60 字）: {reply[:60]}")
    # 64 / 16 = 4 hours per week — the tool's own arithmetic, not the model's
    tool_used = "每周 4 课时" in reply or "每周4课时" in reply
    print(f"[4] suggest_weekly_plan 结果出现在回复中: {'✓' if tool_used else '✗'}")

    # --- 3. thread isolation (ownership by construction) -------------------
    # Architecture fact this script pinned down: both agents share the three
    # checkpoint tables and thread_id IS the partition key — a prefix is a
    # namespace convention preventing accidental sharing, NOT an access-
    # control wall (a graph handed a foreign thread id could read its rows).
    # What the routes actually guarantee: the server builds the id as
    # outline:{calling_user}:{uuid}, so the same uuid under another teacher
    # resolves to a different (empty) thread.
    uuid_part = OUTLINE_THREAD.rsplit(":", 1)[-1]
    foreign_history = await outline.get_chat_history(
        f"outline:someone-else:{uuid_part}"
    )
    own_history = await outline.get_chat_history(OUTLINE_THREAD)
    # chat turn while the outline agent holds data: both agents coexist
    # (two pools, two graphs) and the namespaces never collide by format —
    # chat thread ids are bare UUIDs, outline ids always carry the prefix.
    chat_thread_reply = await chat.get_response(
        [Message(role="user", content="请记住暗号：蓝鲸号潜水艇。现在只回复“好的”。")],
        session_id=CHAT_THREAD,
    )
    chat_reply_ok = bool(chat_thread_reply)
    isolated = foreign_history == [] and len(own_history) > 0 and chat_reply_ok
    print(f"[5] 同一 uuid 换他人前缀: {len(foreign_history)} 条（应为 0）")
    print(f"[5] 原前缀历史: {len(own_history)} 条（应 > 0）")
    print(f"[5] 归属由构造保证 + 双 agent 并存冒烟: {'✓' if isolated else '✗'}")

    # --- 4. checkpoint tables (outline namespace) ---------------------------
    counts = _count_outline_rows()
    print(f"[6] outline 命名空间 checkpoint 表行数: {counts}")
    persisted = all(count > 0 for count in counts.values())
    print(f"[6] 三表均有数据: {'✓' if persisted else '✗'}")

    # --- 5. cleanup -----------------------------------------------------------
    await outline.clear_chat_history(OUTLINE_THREAD)
    await chat.clear_chat_history(CHAT_THREAD)
    counts_after = _count_outline_rows()
    print(f"[7] 清空后行数: {counts_after}")
    cleared = all(count == 0 for count in counts_after.values())
    print(f"[7] 清空生效: {'✓' if cleared else '✗'}")

    await outline.close()
    await chat.close()

    ok = accumulated and tool_used and isolated and persisted and cleared
    print("\n验收结果:", "全部通过 ✓" if ok else "存在失败项 ✗")
    return 0 if ok else 1


if __name__ == "__main__":
    # psycopg async cannot run on Windows' default ProactorEventLoop — force a
    # selector loop for this script's asyncio.run.
    if sys.platform == "win32":
        sys.exit(asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop))
    sys.exit(asyncio.run(main()))
