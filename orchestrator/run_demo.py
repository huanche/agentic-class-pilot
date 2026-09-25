"""在 LangGraph 上跑一节完整的课 —— 演示脚本。

模拟一名学生与编排器的一整节课（时间戳注入 now，可回放）：
  10:00  开场（intro）
  10:01-10:21  讲解阶段：本课为「整段视频」模式（delivery=video），AI 静默不出讲解词，
               视频时间照常计入课时；22 分钟视频全片播完 → media_done → 切进复述
  10:23-10:31  复述阶段：兜底链取 TMISSION 检验问题；
               3 个 KP 完整复述（3星）、1 个零散（2星，未关闭）
  10:32-10:38  深层探究阶段：探究字段为空 → 降级为通用探究问题；
               学生回答浅 → 星级不动 → 预算 7 分钟到点切幕
  10:38  下课总结（ending）

跑完打印：每一轮的对话与编排状态、阶段快照、掌握档案。
落盘产物在 runtime/（演示后由外部恢复空白模板）。

用法：python orchestrator/run_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import EVENT_MEDIA_DONE, LLM_DIAG, build_graph, llm_available, run_one_turn  # noqa: E402

try:
    from langgraph.checkpoint.memory import InMemorySaver
except ImportError:  # 兼容旧名称
    from langgraph.checkpoint.memory import MemorySaver as InMemorySaver


def at(hm: str) -> str:
    return f"2026-09-18T{hm}:00+08:00"


# (时间, 说话人, 学生消息, 外部事件) —— 消息取自一名"中等偏上但不完美"的模拟学生。
# 事件只在个别轮出现：讲解视频 10:00 开播，10:22 全片播完。
TURNS = [
    ("10:00",   "host",    "开始上课", None),
    ("10:01",   "student", "老师好", None),
    ("10:04",   "student", "嗯，CPU 一次只能跑一个，所以要有人决定谁先用", None),
    ("10:09",   "student", "明白了，作业进内存是高级调度的事", None),
    ("10:13",   "student", "好", None),
    ("10:17",   "student", "好", None),
    ("10:20",   "student", "懂了", None),
    ("10:22",   "host",    "", EVENT_MEDIA_DONE),   # 22 分钟视频全片播完
    # ── 复述阶段 ──
    ("10:23",   "student", "来吧", None),
    # ── 复述阶段（续）──
    ("10:24",   "student", "高级调度把作业从外存调入内存变成进程，"
                           "低级调度从就绪进程里挑一个上 CPU，中级调度负责对换、平衡内存", None),
    ("10:25",   "student", "系统会打断 A，因为 B 的运行时间更短，"
                           "抢占式就是允许中断当前进程", None),
    ("10:27",   "student", "SJF 就是短作业先跑，长作业会倒霉一直等着……"
                           "怎么缓解来着我记不清了", None),
    ("10:28",   "student", "周转时间是从提交到完成；等待时间是在就绪队列里等的时间；"
                           "响应时间是第一次拿到 CPU 的快慢", None),
    ("10:31",   "student", "好的", None),
    # ── 深层探究阶段 ──
    ("10:32",   "student", "好", None),
    ("10:34",   "student", "呃，就是短作业先跑吧，排队的时候短的不用等太久", None),
    ("10:36",   "student", "反正就是快的先走，没什么特别的", None),
    ("10:38",   "student", "行", None),
    # ── 收尾 ──
    ("10:39",   "student", "谢谢老师", None),
]


def main() -> int:
    graph = build_graph(checkpointer=InMemorySaver())
    session = "demo-001"

    # 确定性回放：先清掉该学生的历史掌握档案，保证每次跑都从 0 星开始
    # （同一学生跨课次延续星级是设计行为，但 demo 必须可重复）
    import shutil
    student_dir = Path(__file__).resolve().parent.parent / "runtime" / "students" / "student-001"
    if student_dir.is_dir():
        shutil.rmtree(student_dir)

    print("=" * 72)
    print("主动引导智能体 · LangGraph 编排器 —— 一节课的完整模拟")
    print("=" * 72)

    last_phase = None
    for hm, speaker, msg, ev in TURNS:
        now = at(hm)
        st = run_one_turn(graph, session, now, msg, speaker,
                          tick_only=(speaker == "host" and not msg),
                          external_event=ev)

        phase = st["host_phase"]
        tag = "▶" if phase != last_phase else " "
        print(f"\n{tag} [{hm}] ({phase} | 本幕 {st['stage_elapsed_minutes']}/"
              f"{st['stage_budget_minutes']} 分 | 全课 {st['lesson_elapsed_minutes']} 分)")
        if speaker == "student":
            print(f"  学生> {msg}")
        elif ev:
            print(f"  ⚡ 外部事件> {ev}")
        elif not msg:
            print(f"  （静默轮）")
        else:
            print(f"  主持> {msg}")
        reply = (st.get("reply_text") or "").replace("\n", "\n        ")
        # 区分"大模型生成"与"降级脚本"，否则接没接上 AI 看不出来
        src = "AI  " if st.get("llm_used") else "脚本"
        print(f"  老师[{src}]> {reply}")

        if st.get("advance_reason"):
            print(f"  ⚙ 判定: {st['advance_reason']}")
        ev = st.get("turn_evidence") or []
        if ev:
            print(f"  ✔ 证据: {'; '.join(ev)}")
        stars = st.get("kp_stars") or {}
        if stars:
            print("  ★ 星级: " + "  ".join(
                f"{k}={'★'*v}" for k, v in sorted(stars.items())))
        last_phase = phase

    # ── 课后的档案 ──
    st = dict(graph.get_state({"configurable": {"thread_id": session}}).values)
    print("\n" + "=" * 72)
    print("阶段快照（stage_snapshots，Annotated 累加，一幕一条）：")
    for snap in st.get("stage_snapshots") or []:
        print(f"  - {snap['snapshot_id']} {snap['stage']} "
              f"({snap['stage_elapsed_minutes']} 分) "
              f"关闭 {snap['targets_closed']} / 未关 {snap['targets_open']}")
        print(f"      stars: {snap['stars_snapshot']}")

    # ── LLM 接入实况 ──
    print("\n" + "─" * 72)
    if llm_available():
        print(f"LLM：已接入   调用 {LLM_DIAG['calls']} 次 → "
              f"成功 {LLM_DIAG['ok']} / 失败 {LLM_DIAG['failed']}")
        if LLM_DIAG["last_error"]:
            print(f"  末次失败原因：{LLM_DIAG['last_error']}")
        print("  说明：模型只润色表达；切幕与星级由确定性骨架决定，不受影响。")
    else:
        print("LLM：未配置（三个 AGENT_LLM_* 变量缺任一）→ teach 全程走降级脚本")
        print("  配好后重跑即可看到 [AI] 标记。")

    print("\n落盘文件已更新：")
    for p in ("runtime/DIALOGUE-LOG.md", "runtime/data/mastery-state.json",
              "runtime/data/mastery-history.json", "runtime/data/dialogue-log.json"):
        print(f"  - {p} ({Path(p).stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
