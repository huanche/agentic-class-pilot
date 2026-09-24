"""编排器时钟与切幕判定的参考实现 + 回归测试。

用途：验证 ORCHESTRATOR.md 第 5/6 节的逻辑真的能跑通。

设计要点：时间全部来自 state["now"] 输入，编排器不自己取时间。
所以喂一串时间戳就能回放整节课，切幕逻辑也因此可单测。

范围：只负责"这门课/这一幕花了多少分钟"，不判断学生是否在场。
"""

from datetime import datetime


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _minutes(now: str, since: str) -> float:
    return round((_dt(now) - _dt(since)).total_seconds() / 60, 2)


def tick(state: dict) -> dict:
    """算出本幕与本课已花的真实分钟数。ORCHESTRATOR.md 第 5.3 节。"""
    return {
        "stage_elapsed_minutes": _minutes(state["now"], state["stage_started_at"]),
        "lesson_elapsed_minutes": _minutes(state["now"], state["lesson_started_at"]),
    }


def judge_advance(state: dict) -> dict:
    """切幕判定。ORCHESTRATOR.md 第 6 节。返回 {'action', 'reason'}。"""
    # 1. 最短幕时长保护
    if state["stage_elapsed_minutes"] < state["min_stage_minutes"]:
        return {"action": "stay", "reason": "未达最短幕时长"}

    # 2. evidence 模式：目标没关完就不走
    if state["advance_when"] == "evidence" and state["unresolved"]:
        return {"action": "stay", "reason": "尚有未关闭目标（evidence 模式）"}

    # 3. 证据到位
    if state["turn_evidence"] and not state["unresolved"]:
        if state["advance_when"] in ("evidence", "either"):
            if state["on_evidence_reached"] == "advance":
                return {"action": "next_stage", "reason": "目标已达成，证据充分"}

    # 4. 预算
    if state["stage_elapsed_minutes"] >= state["stage_budget_minutes"]:
        overrun = state["stage_elapsed_minutes"] - state["stage_budget_minutes"]
        mode = state["on_budget_exhausted"]
        if mode == "force_advance":
            return {"action": "next_stage", "reason": "预算耗尽：强制切幕"}
        if mode == "wrap_up":
            return {"action": "next_stage", "reason": "预算耗尽：本幕收尾"}
        if mode == "extend" and overrun < state["max_stage_overrun_minutes"]:
            return {"action": "stay", "reason": f"预算耗尽但允许延长（超 {overrun:.1f} 分）"}
        return {"action": "next_stage", "reason": "延长额度用尽"}

    # 5. 默认留幕
    return {"action": "stay", "reason": "时间与证据均未触发切幕"}


# ─────────────────── 测试 ───────────────────

def base_state(**over) -> dict:
    t0 = "2026-09-18T10:00:00+08:00"
    s = {
        "now": t0,
        "lesson_started_at": t0,
        "stage_started_at": t0,
        "stage_elapsed_minutes": 0.0,
        "lesson_elapsed_minutes": 0.0,
        "stage_budget_minutes": 22.0,
        "advance_when": "either",
        "on_evidence_reached": "advance",
        "on_budget_exhausted": "wrap_up",
        "min_stage_minutes": 2.0,
        "max_stage_overrun_minutes": 3.0,
        "turn_evidence": [],
        "unresolved": ["KP-002"],
    }
    s.update(over)
    return s


def at(hm: str) -> str:
    return f"2026-09-18T{hm}:00+08:00"


def replay(start: dict, stamps: list) -> dict:
    """依次喂入时间戳，模拟多轮对话。返回最终状态。"""
    st = dict(start)
    for hm in stamps:
        st["now"] = at(hm)
        st.update(tick(st))
    return st


def check(name, verdict, expect, extra=""):
    ok = verdict["action"] == expect
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if extra:
        print(f"       {extra}")
    print(f"       判定 {verdict['action']} ← {verdict['reason']}")
    return ok


def main():
    results = []

    # ── 1. 时长计算单调 ──
    print("── 真实时钟：时长随墙钟增长 ──")
    st = base_state()
    st = replay(st, ["10:01", "10:05", "10:13"])
    ok = st["stage_elapsed_minutes"] == 13.0 and st["lesson_elapsed_minutes"] == 13.0
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] 三轮后本幕/本课均已花 13 分钟")
    print(f"       stage={st['stage_elapsed_minutes']} lesson={st['lesson_elapsed_minutes']}")

    # ── 2. 最短幕时长保护 ──
    print("\n── 最短幕时长保护 ──")
    st = base_state()
    st = replay(st, ["10:01"])
    results.append(check("1 分钟（< min 2 分）→ 留幕", judge_advance(st), "stay",
                         f"已花 {st['stage_elapsed_minutes']} 分"))
    st = base_state()
    st = replay(st, ["10:02"])
    results.append(check("2 分钟（= min 2 分）→ 进入后续判定", judge_advance(st), "stay",
                         f"已花 {st['stage_elapsed_minutes']} 分"))

    # ── 3. 预算触发切幕 ──
    print("\n── 预算触发 ──")
    st = base_state()
    st = replay(st, ["10:21", "10:22"])
    results.append(check("已花 22 分（= 预算 22）→ 切幕", judge_advance(st), "next_stage",
                         f"已花 {st['stage_elapsed_minutes']} 分"))

    # ── 4. 证据优先于时间 ──
    print("\n── 证据与预算的优先级 ──")
    st = base_state()
    st = replay(st, ["10:03"])
    st["turn_evidence"] = ["学生说出高级调度把作业调入内存"]
    st["unresolved"] = []
    results.append(check("3 分钟但目标全关闭 → 切幕（证据优先）",
                         judge_advance(st), "next_stage"))

    st = base_state(advance_when="evidence", on_budget_exhausted="force_advance")
    st = replay(st, ["10:30"])
    st["turn_evidence"] = []
    st["unresolved"] = ["KP-002"]
    results.append(check("evidence 模式 + 目标未关闭 + 超预算 → 留幕（目标优先）",
                         judge_advance(st), "stay"))

    # ── 5. 三种预算策略 ──
    print("\n── on_budget_exhausted 三分支 ──")
    for mode, exp in [("force_advance", "next_stage"), ("wrap_up", "next_stage")]:
        st = base_state(on_budget_exhausted=mode)
        st = replay(st, ["10:25"])
        st["unresolved"] = ["KP-002"]
        results.append(check(f"超预算 + {mode}", judge_advance(st), exp))
    st = base_state(on_budget_exhausted="extend")
    st = replay(st, ["10:23"])
    results.append(check("超预算 1 分 + extend（额度 3 分）→ 留幕", judge_advance(st), "stay"))
    st = base_state(on_budget_exhausted="extend")
    st = replay(st, ["10:22", "10:30"])
    results.append(check("超预算 8 分 + extend（额度 3 分）→ 切幕", judge_advance(st), "next_stage"))

    # ── 6. 可回放性 ──
    print("\n── 回放验证：整节课按时间戳重演 ──")
    st = base_state()
    st = replay(st, ["10:01", "10:05", "10:10", "10:14", "10:18", "10:22"])
    print(f"       本幕已花 {st['stage_elapsed_minutes']} 分 | "
          f"本课已花 {st['lesson_elapsed_minutes']} 分")
    results.append(st["lesson_elapsed_minutes"] == 22.0)
    print(f"[{'PASS' if st['lesson_elapsed_minutes'] == 22.0 else 'FAIL'}] "
          f"回放结果与墙钟一致（可单测）")

    passed = sum(1 for r in results if r)
    print(f"\n结果: {passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
