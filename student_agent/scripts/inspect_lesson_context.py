"""看一眼某个会话当前发给模型的是什么上下文，按「课程级 / 课时级 / 当前段落」分开。

用法（在 student_agent/ 下，或从仓库根用 -c 里的路径）：
    .venv/Scripts/python.exe scripts/inspect_lesson_context.py                  # 自动挑最近改动的会话
    .venv/Scripts/python.exe scripts/inspect_lesson_context.py cls-xxxx         # 指定会话
    .venv/Scripts/python.exe scripts/inspect_lesson_context.py cls-xxxx --full  # 打印正文片段

看的是 runtime/sessions/<sid>.json —— 服务端每轮 _step 都会重写它，不用连服务。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.integration import prompt_context  # noqa: E402

SESSIONS = ROOT / "runtime" / "sessions"


def pick_session(argv: list[str]) -> Path:
    named = [a for a in argv if not a.startswith("-")]
    if named:
        path = SESSIONS / f"{named[0]}.json"
        if not path.is_file():
            raise SystemExit(f"没有这个会话：{path}")
        return path
    files = sorted(SESSIONS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise SystemExit("runtime/sessions/ 下没有会话文件")
    return files[0]


def bar(n: int, total: int, width: int = 24) -> str:
    filled = round(width * n / total) if total else 0
    return "█" * filled + "·" * (width - filled)


def main() -> int:
    show_full = "--full" in sys.argv
    path = pick_session([a for a in sys.argv[1:] if a != "--full"])
    state = json.loads(path.read_text(encoding="utf-8"))
    plan = state.get("lesson_plan") or {}
    lesson_id = state.get("lesson_id") or ""

    print(f"会话 {path.stem}")
    print(f"  课时 id  : {lesson_id}")
    print(f"  阶段     : {state.get('host_phase')}  状态: {state.get('lesson_status')}")
    print(f"  当前段落 : {state.get('active_segment_id') or '(无)'}")
    print(f"  计划来源 : {plan.get('source') or '(本地课时，非平台)'}")
    if not prompt_context.is_platform_plan(plan):
        print("\n非平台计划：上下文来自本地 rules/ 与 lesson-data/，不走平台知识包。")
        return 0

    # ── 上下文总量 ──
    ctx = prompt_context.tutor_context(state)
    print(f"\n{'=' * 62}\n发给模型的上下文总量: {len(ctx)} 字符（上限 12000）\n{'=' * 62}")
    if ctx:
        payload = json.loads(ctx)
        for key, value in payload.items():
            size = len(json.dumps(value, ensure_ascii=False))
            print(f"  {key:18s} {size:6d}  {bar(size, len(ctx))}")

    # ── 课时级：这节课自己的段落 / 知识点 ──
    segments = plan.get("segments") or []
    points = plan.get("knowledge_points") or []
    print(f"\n【课时级】这节课自己的内容")
    print(f"  段落 {len(segments)} 个:", ", ".join(str(s.get("id")) for s in segments) or "(空)")
    print(f"  知识点 {len(points)} 个:", ", ".join(str(k.get("id")) for k in points) or "(空)")
    for seg in segments:
        print(f"    · {seg.get('id')}  {seg.get('title')!r}  正文 {len(str(seg.get('content') or ''))} 字符")

    # ── 选进上下文的材料：来源分布 + 重复 ──
    sources = plan.get("knowledge_sources") or []
    print(f"\n【课程级】已发布知识包共 {len(sources)} 份文档（整门课共享，与本课时无关）")
    total_chars = sum(len(str(s.get("content") or "")) for s in sources)
    for s in sources:
        n = len(str(s.get("content") or ""))
        print(f"    {s.get('id'):18s} {n:6d} 字符  {str(s.get('title'))[:34]!r}")
    print(f"  合计 {total_chars} 字符")

    picked = prompt_context.lesson_sources(plan)
    print(f"\n【被选进上下文】{len(picked)} 段 × 1000 字符")
    counts = Counter(p.get("id") for p in picked)
    for i, p in enumerate(picked):
        dup = "  ← 重复" if counts[p.get("id")] > 1 else ""
        print(f"  [{i}] {p.get('id'):18s} {str(p.get('title'))[:30]!r}{dup}")
        if show_full:
            print("      " + str(p.get("content") or "").replace("\n", " ")[:300] + " …")
    wasted = sum(n - 1 for n in counts.values())
    print(f"  → {len(counts)} 份不同文档；{wasted} 段是重复内容"
          f"（占 {round(100 * wasted / max(1, len(picked)))}% 预算）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
