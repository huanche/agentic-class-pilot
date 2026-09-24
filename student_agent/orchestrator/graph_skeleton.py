"""编排器的 LangGraph 骨架 —— 看清楚"这套设计落到 LangGraph 里长什么样"。

这不是完整实现，是**骨架 + 关键写法**：
- State 用 TypedDict 怎么声明（尤其是 Annotated 累加字段）
- 节点就是普通函数，收 state 返回"部分更新"
- 条件边怎么把 judge_advance 的判断转成路由
- 循环怎么形成（这是"自动推进"的本质）
- checkpointer 怎么让中断后能续上

文件里的 [占位] 标记表示此处是真实实现要写逻辑的地方。
跑一下 `python orchestrator/graph_skeleton.py` 能看到编译出的图结构。
"""

from typing import TypedDict, Annotated, Literal
import operator

from langgraph.graph import StateGraph, START, END


# ═══════════════════════════════════════════════════════════════
# 1. State：整张图共享的一个字典
#    节点不"传参"，而是各自读写这个共享状态。
# ═══════════════════════════════════════════════════════════════

class ClassroomState(TypedDict):
    # ── 会话标识 ──
    session_id: str
    student_id: str
    lesson_id: str

    # ── 编排器核心：演哪一幕 + 这一幕演了多久 ──
    host_phase: Literal[
        "uninitialized", "intro", "guided_learning",
        "recap_discussion", "deep_inquiry", "class_discussion", "ending"
    ]
    active_segment_id: str | None
    stage_started_at: str
    stage_elapsed_minutes: float
    lesson_elapsed_minutes: float
    stage_budget_minutes: float
    remaining_stages: list[str]

    # ── 时钟（外部注入，节点只读）──
    now: str
    lesson_started_at: str | None

    # ── 教学状态 ──
    current_target: str | None
    current_question: str | None
    attempts: int
    mastered: list[str]
    unresolved: list[str]

    # ── 学生轮 ──
    student_message: str
    speaker: Literal["host", "student"]
    student_status: Literal["active", "practicing", "waiting", "ended"]

    # ── 证据与掌握 ──
    turn_evidence: list[str]
    mastery_updates: list[dict]
    # Annotated + operator.add：这个字段是"累加"的，不是覆盖的。
    # 每幕结束 advance_stage 往里追加一条快照，历史不会被冲掉。
    stage_snapshots: Annotated[list[dict], operator.add]

    # ── 输出 ──
    reply_text: str
    speech_kind: Literal["none", "auto"]
    advance_reason: str | None

    # ── 路由中转：judge_advance 写，条件边读 ──
    target_phase: str | None
    assembled_prompt: str


# ═══════════════════════════════════════════════════════════════
# 2. 节点 = 普通函数，签名统一：收到 state，返回"要改的那部分"
#    不返回的字段保持原值。这是 LangGraph 最核心的约定。
# ═══════════════════════════════════════════════════════════════

def load_plan(state: ClassroomState) -> dict:
    """读 lesson-plan.json，把启用阶段装进 remaining_stages。"""
    # [占位] json.load(open("lesson-data/lesson-plan.json"))
    plan = _load_plan()
    enabled = [s for s in plan["stages"] if s["enabled"]]

    first = enabled[0]
    return {
        "remaining_stages": [s["id"] for s in enabled[1:]],
        "stage_budget_minutes": first["minutes"],
        "host_phase": first["id"],
        "lesson_started_at": state["now"],   # 开课时刻 = 本轮 now
        "stage_started_at": state["now"],
        "current_target": None,
        "unresolved": [],
    }


def tick(state: ClassroomState) -> dict:
    """唯一读时间的地方。只做减法，不判任何'人在不在'。"""
    from datetime import datetime

    now = datetime.fromisoformat(state["now"])

    def minutes_since(t: str) -> float:
        return round((now - datetime.fromisoformat(t)).total_seconds() / 60, 2)

    return {
        "stage_elapsed_minutes": minutes_since(state["stage_started_at"]),
        "lesson_elapsed_minutes": minutes_since(state["lesson_started_at"]),
    }


def load_context(state: ClassroomState) -> dict:
    """按 host_phase 分层装配 prompt。空壳阶段注入占位提示，不报错。"""
    phase = state["host_phase"]

    parts = []
    # 规则层（每轮）
    parts.append(_read("rules/KNOWLEDGE-BASE.md"))
    # 计划层（当前阶段那段）
    parts.append(_plan_slice(state["lesson_id"], phase))
    # 课堂层（当前 segment + 绑定的 KP）
    if state.get("active_segment_id"):
        parts.append(_read(f"lesson-data/segments/{state['active_segment_id']}.json"))
    # 阶段层（只有复述/探究/讨论三幕有）
    if phase in ("recap_discussion", "deep_inquiry", "class_discussion"):
        for f in ("questions.md", "prompt.md", "rubric.md"):
            text = _read_optional(f"stages/{phase}/{f}")
            parts.append(text or "[本阶段内容未配置]")  # ← 空壳降级

    return {"assembled_prompt": "\n\n".join(parts)}


def classify_turn(state: ClassroomState) -> dict:
    """判断这轮是谁在说话，决定走主持事件还是教学。"""
    # [占位] 实际可用规则或模型判断
    is_host = state.get("student_message", "") == "" or state.get("speaker") == "host"
    return {"speaker": "host" if is_host else "student"}


def host_event(state: ClassroomState) -> dict:
    """处理开场/收尾这类由主持人触发的事件。"""
    # [占位] 生成开场白或收尾总结
    return {"reply_text": "[占位] 主持事件回复", "target_phase": None}


def teach(state: ClassroomState) -> dict:
    """本幕教学：调模型产出追问、反馈、讲解。"""
    # [占位] llm.invoke(state["assembled_prompt"] + 学生消息)
    reply = _fake_llm(state)
    return {
        "reply_text": reply,
        "turn_evidence": _extract_evidence(reply),
        "current_question": _extract_question(reply),
        "attempts": state["attempts"] + 1,
    }


def judge_mastery(state: ClassroomState) -> dict:
    """按 rubric 判星级，产出 mastery_updates。"""
    # [占位] 对照 MASTERY-STAR-RULES.md 判定
    return {"mastery_updates": []}


def judge_advance(state: ClassroomState) -> dict:
    """★ 编排核心。判定留幕还是切幕，结果写进 target_phase。

    条件边只认 target_phase，判定逻辑全在这里。
    """
    # 没有 lesson-plan 关键字段时的兜底（例如未开课）
    if state["stage_elapsed_minutes"] < state.get("min_stage_minutes", 2.0):
        return {"target_phase": None, "advance_reason": "未达最短幕时长"}

    if state.get("advance_when") == "evidence" and state["unresolved"]:
        return {"target_phase": None, "advance_reason": "尚有未关闭目标"}

    if state["turn_evidence"] and not state["unresolved"]:
        if state.get("on_evidence_reached") == "advance":
            return {"target_phase": _next_phase(state), "advance_reason": "证据充分"}

    if state["stage_elapsed_minutes"] >= state["stage_budget_minutes"]:
        return {"target_phase": _next_phase(state), "advance_reason": "预算耗尽"}

    return {"target_phase": None, "advance_reason": "时间与证据均未触发切幕"}


def advance_stage(state: ClassroomState) -> dict:
    """切幕三连：写快照 → 取下一幕 → 重置本幕状态。"""
    snapshot = {
        "type": "stage_snapshot",
        "stage": state["host_phase"],
        "stage_elapsed_minutes": state["stage_elapsed_minutes"],
        "targets_closed": state["mastered"],
        "targets_open": state["unresolved"],
    }

    rest = state["remaining_stages"]
    if not rest:                                    # 没有下一幕了 → 收尾
        return {
            "stage_snapshots": [snapshot],           # Annotated 累加，不覆盖
            "host_phase": "ending",
            "remaining_stages": [],
            "stage_started_at": state["now"],
            "stage_elapsed_minutes": 0.0,
            "current_target": None,
            "mastered": [],
            "unresolved": [],
        }

    nxt = rest[0]
    return {
        "stage_snapshots": [snapshot],
        "host_phase": nxt,
        "remaining_stages": rest[1:],
        "stage_budget_minutes": _budget_of(state["lesson_id"], nxt),
        "stage_started_at": state["now"],            # 新幕从此刻起算
        "stage_elapsed_minutes": 0.0,
        "current_target": None,
        "mastered": [],
        "unresolved": [],
        "active_segment_id": None,
        "advance_reason": state.get("advance_reason"),
    }


def write_state(state: ClassroomState) -> dict:
    """落盘：DIALOGUE-LOG.md + mastery-*.json。"""
    # [占位] 真正写文件的地方
    _persist(state)
    return {}


def format_reply(state: ClassroomState) -> dict:
    """组装最终回复与播报标记。"""
    return {
        "reply_text": state.get("reply_text", ""),
        "speech_kind": "auto" if state.get("reply_text") else "none",
    }


# ═══════════════════════════════════════════════════════════════
# 3. 路由函数：把 state 映射成一个"边名"，LangGraph 据此选走哪条边
# ═══════════════════════════════════════════════════════════════

def route_after_classify(state: ClassroomState) -> str:
    """分类后分流：主持事件 vs 学生轮教学。"""
    return "host_event" if state["speaker"] == "host" else "teach"


def route_after_judge(state: ClassroomState) -> str:
    """★ 切幕与否。judge_advance 把判决写进 target_phase，这里只读。"""
    return "next_stage" if state.get("target_phase") else "stay"


# ═══════════════════════════════════════════════════════════════
# 4. 建图：加节点 → 加边 → 编译
#    "自动推进"的本质：图里有一条回到 classify_turn 的环，
#    每轮问答都走一圈，judge_advance 决定这一圈要不要换幕。
# ═══════════════════════════════════════════════════════════════

def build_graph():
    g = StateGraph(ClassroomState)

    # ── 加节点 ──
    g.add_node("load_plan", load_plan)
    g.add_node("tick", tick)
    g.add_node("load_context", load_context)
    g.add_node("classify_turn", classify_turn)
    g.add_node("host_event", host_event)
    g.add_node("teach", teach)
    g.add_node("judge_mastery", judge_mastery)
    g.add_node("judge_advance", judge_advance)
    g.add_node("advance_stage", advance_stage)
    g.add_node("write_state", write_state)
    g.add_node("format_reply", format_reply)

    # ── 主干：直线连下去 ──
    g.add_edge(START, "load_plan")
    g.add_edge("load_plan", "tick")
    g.add_edge("tick", "load_context")
    g.add_edge("load_context", "classify_turn")

    # ── 分类后分流 ──
    g.add_conditional_edges(
        "classify_turn",
        route_after_classify,
        {"host_event": "host_event", "teach": "teach"},
    )
    g.add_edge("host_event", "judge_advance")
    g.add_edge("teach", "judge_mastery")
    g.add_edge("judge_mastery", "judge_advance")

    # ── ★ 切幕与否 ──
    g.add_conditional_edges(
        "judge_advance",
        route_after_judge,
        {"stay": "write_state", "next_stage": "advance_stage"},
    )
    g.add_edge("advance_stage", "write_state")
    g.add_edge("write_state", "format_reply")
    g.add_edge("format_reply", END)

    # ── checkpointer：把 state 存下来，中断后可续 ──
    # from langgraph.checkpoint.sqlite import SqliteSaver
    # return g.compile(checkpointer=SqliteSaver.from_conn_string("orchestrator/state.sqlite"))
    return g.compile()


# ═══════════════════════════════════════════════════════════════
# 5. 调用方长这样：每轮把 now 注入，用同一个 thread_id 续上
# ═══════════════════════════════════════════════════════════════

def run_one_turn(graph, session_id: str, now: str, student_message: str):
    config = {"configurable": {"thread_id": session_id}}

    # 只传"这一轮新增的输入"，其余从 checkpoint 恢复
    graph.invoke(
        {"now": now, "student_message": student_message, "speaker": "student"},
        config,
    )
    return graph.get_state(config).values["reply_text"]


# ─────────────────── 下面是让骨架能跑起来的空实现 ───────────────────

def _load_plan():
    import json
    return json.load(open("lesson-data/lesson-plan.json", encoding="utf-8"))


def _budget_of(lesson_id, phase) -> float:
    for s in _load_plan()["stages"]:
        if s["id"] == phase:
            return s["minutes"]
    return 0.0


def _read(path: str) -> str:
    try:
        return open(path, encoding="utf-8").read()
    except FileNotFoundError:
        return ""


def _read_optional(path: str) -> str:
    return _read(path)


def _plan_slice(lesson_id, phase) -> str:
    return f"[计划层] {lesson_id} / {phase}"


def _fake_llm(state: ClassroomState) -> str:
    return f"[占位回复] 当前在 {state['host_phase']}，已花 {state['stage_elapsed_minutes']} 分钟"


def _extract_evidence(reply: str) -> list[str]:
    return []


def _extract_question(reply: str) -> str | None:
    return None


def _next_phase(state: ClassroomState) -> str:
    return state["remaining_stages"][0] if state["remaining_stages"] else "ending"


def _persist(state: ClassroomState) -> None:
    pass


if __name__ == "__main__":
    graph = build_graph()
    print("图编译成功。结构如下:\n")
    try:
        print(graph.get_graph().draw_ascii())
    except Exception as e:
        print(f"(ASCII 绘图不可用: {e})")
