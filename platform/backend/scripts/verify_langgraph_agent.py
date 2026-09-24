# ruff: noqa: T201 — printing the verification transcript is this script's job
"""Step-2 acceptance check for the LangGraph migration (plan appendix E).

Runs the agent against the real stack (DATABASE_URL Postgres + configured
LLM) and verifies, in order:

1. multi-turn history accumulates under one thread_id (turn 2 recalls turn 1);
2. a different thread_id does NOT see that history (isolation);
3. the three checkpoint tables hold rows for both threads;
4. clear_chat_history removes them.

Run from ``backend/``:  uv run python scripts/verify_langgraph_agent.py
"""

import asyncio
import sys

# Windows console defaults to a legacy codepage (GBK) that can't render the
# ✓/✗ marks or some Chinese output below.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import psycopg

from app.core.config import settings
from app.core.langgraph.checkpoint import checkpointer_conninfo
from app.core.langgraph.graph import LangGraphAgent
from app.schemas.chat import Message

THREAD_A = "verify-step2-a"
THREAD_B = "verify-step2-b"


def _count_checkpoint_rows() -> dict[str, int]:
    """Count rows per checkpoint table for our two verification threads."""
    counts: dict[str, int] = {}
    with psycopg.connect(checkpointer_conninfo()) as conn:
        for table in settings.CHECKPOINT_TABLES:
            row = conn.execute(  # noqa: S608 - static table names from settings
                f"SELECT count(*) FROM {table} WHERE thread_id IN (%s, %s)",
                (THREAD_A, THREAD_B),
            ).fetchone()
            counts[table] = row[0]
    return counts


async def main() -> int:
    agent = LangGraphAgent()
    # Idempotent: creates the checkpoint tables on a fresh database, no-op
    # (fast IF NOT EXISTS) when they already exist.
    await agent.create_graph()

    # Start clean so reruns (e.g. after a crash midway) are deterministic.
    await agent.clear_chat_history(THREAD_A)
    await agent.clear_chat_history(THREAD_B)

    # --- 1. multi-turn accumulation (same thread_id) --------------------
    turn1 = await agent.get_response(
        [Message(role="user", content="请记住暗号：蓝鲸号潜水艇。现在只回复“好的”。")],
        session_id=THREAD_A,
    )
    print(f"[1] 第 1 轮回复: {turn1[-1].content[:60]}")

    turn2 = await agent.get_response(
        [Message(role="user", content="暗号是什么？")],
        session_id=THREAD_A,
    )
    print(f"[2] 第 2 轮回复: {turn2[-1].content[:60]}")
    remembers = "蓝鲸号潜水艇" in turn2[-1].content
    print(f"[2] 同 thread 记住暗号: {'✓' if remembers else '✗'}")

    history = await agent.get_chat_history(THREAD_A)
    roles = [m.role for m in history]
    print(f"[3] thread A 历史: {roles}")
    accumulated = roles == ["user", "assistant", "user", "assistant"]
    print(f"[3] 历史累积: {'✓' if accumulated else '✗'}")

    # --- 2. isolation (different thread_id) ------------------------------
    other = await agent.get_response(
        [Message(role="user", content="暗号是什么？")],
        session_id=THREAD_B,
    )
    leaked = "蓝鲸号潜水艇" in other[-1].content
    print(f"[4] thread B 首问回复: {other[-1].content[:60]}")
    print(f"[4] 跨 thread 隔离（不应知道暗号）: {'✗ 泄漏!' if leaked else '✓'}")

    # --- 3. checkpoint tables ---------------------------------------------
    counts = _count_checkpoint_rows()
    print(f"[5] checkpoint 表行数: {counts}")
    persisted = all(count > 0 for count in counts.values())
    print(f"[5] 三表均有数据: {'✓' if persisted else '✗'}")

    # --- 4. cleanup ---------------------------------------------------------
    await agent.clear_chat_history(THREAD_A)
    await agent.clear_chat_history(THREAD_B)
    counts_after = _count_checkpoint_rows()
    print(f"[6] 清空后行数: {counts_after}")
    cleared = all(count == 0 for count in counts_after.values())
    print(f"[6] 清空生效: {'✓' if cleared else '✗'}")

    await agent.close()

    ok = remembers and accumulated and not leaked and persisted and cleared
    print("\n验收结果:", "全部通过 ✓" if ok else "存在失败项 ✗")
    return 0 if ok else 1


if __name__ == "__main__":
    # psycopg async cannot run on Windows' default ProactorEventLoop — force a
    # selector loop for this script's asyncio.run.
    if sys.platform == "win32":
        sys.exit(asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop))
    sys.exit(asyncio.run(main()))
