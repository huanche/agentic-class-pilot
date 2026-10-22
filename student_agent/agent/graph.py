"""One LangGraph run per student turn; business transitions stay deterministic."""
from __future__ import annotations

import json
import os
import re
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from .progression import advance, normalize, current_point, eligible_points
from .prompts import (
    EVALUATION_PROMPT, TUTOR_PROMPT, STAGE_PROMPTS, STRATEGY_PROMPTS,
    opening_message,
)


class DialogueState(TypedDict):
    curriculum_version: int
    flow_version: int
    recall_round_limit: int
    reinforce_round_limit: int
    transition: str
    last_point_id: str | None
    stage: str
    points: list[dict]
    messages: list[dict]
    student_text: str
    evaluation: dict
    reply: str
    strategy: str
    discussion_turns: int
    discussion_point_ids: list[str]
    discussion_index: int
    completion_reason: str


def initial_state(points: list[dict]) -> DialogueState:
    return normalize({"stage": "recall", "points": [dict(p, status="unseen", attempts=0,
            evidence="") for p in points], "messages": [], "student_text": "",
            "evaluation": {}, "reply": "", "strategy": "ask", "discussion_turns": 0})


def _model() -> ChatOpenAI:
    key = os.environ.get("STUDENT_AGENT_API_KEY") or os.environ.get("LLM_API_KEY")
    if not key:
        raise RuntimeError("请配置 STUDENT_AGENT_API_KEY 或 LLM_API_KEY")
    return ChatOpenAI(api_key=key,
                      base_url=os.environ.get("STUDENT_AGENT_BASE_URL") or
                      os.environ.get("LLM_BASE_URL") or "https://api.deepseek.com/v1",
                      model=os.environ.get("STUDENT_AGENT_MODEL") or
                      os.environ.get("LLM_MODEL") or "deepseek-v4-flash",
                      temperature=0.2, timeout=45, max_retries=1)


def _completion(system: str, user: str) -> str:
    result = _model().invoke([SystemMessage(content=system), HumanMessage(content=user)])
    return str(result.content)


def _json_object(raw: str) -> dict:
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        value = json.loads(clean)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def evaluate(state: DialogueState) -> dict:
    if state["stage"] == "wrapup":
        return {"evaluation": {"intent": "unclear", "assessments": []}}
    active = current_point(state)
    points = [active] if active else []
    # Only recent dialogue is needed to interpret a short answer such as "是的".
    history = state["messages"][-8:]
    raw = _completion(EVALUATION_PROMPT, json.dumps({"stage": state["stage"], "points": points,
                       "recentMessages": history, "studentText": state["student_text"]}, ensure_ascii=False))
    value = _json_object(raw)
    valid_ids = {p["id"] for p in points}
    if value.get("intent") not in {"answer", "question", "unclear"} or not isinstance(value.get("assessments"), list):
        raise ValueError("课堂评估结果格式不正确")
    assessments = [a for a in value["assessments"] if isinstance(a, dict)
                   and a.get("id") in valid_ids
                   and a.get("result") in {"mastered", "partial", "misconception", "unanswered"}]
    return {"evaluation": {"intent": value.get("intent") if value.get("intent") in
                            {"answer", "question", "unclear"} else "unclear",
                            "assessments": assessments}}


def route(state: DialogueState) -> dict:
    return advance(state)


def respond(state: DialogueState) -> dict:
    stage = state["stage"]
    if stage == "wrapup":
        reason = ("每个已掌握知识点的深入讨论都已完成，刚才的回答和需要巩固的内容都已记录。"
                  if state.get("completion_reason") == "all_points_discussed" else
                  "本次复述与讨论已告一段落。需要巩固的内容已经记录，目前没有适合继续出题的知识点。")
        return {"reply": "现在进入【课堂总结】。\n\n" + reason +
                "\n\n请点击“结束本课并查看反馈”，查看本次学习情况。"
                "结束后还可以回看视频、补完未掌握的内容或继续课后提问。"}
    points = eligible_points(state["points"]) if stage == "discuss" else state["points"]
    active = current_point(state)
    focus = [active] if active else points
    strategy_prompt = STRATEGY_PROMPTS.get(state["strategy"], "")
    if stage == "discuss" and state["strategy"] == "answer_question":
        strategy_prompt = "先回答学生对当前题目的疑问，再请学生继续回答原题；不要另出一道新题。"
    system = "\n\n".join((TUTOR_PROMPT, STAGE_PROMPTS[stage], strategy_prompt))
    user = json.dumps({"focus": focus, "allPoints": points,
                       "transition": state.get("transition"),
                       "previousPointId": state.get("last_point_id"),
                       "roundLimit": (state["recall_round_limit"] if stage == "recall"
                                      else state["reinforce_round_limit"] if stage == "reinforce"
                                      else None),
                       "excludedTitles": [p["title"] for p in state["points"] if p["excluded_from_discussion"]],
                       "extendedReinforcement": bool(active and active.get("extended_reinforcement")),
                       "recentMessages": state["messages"][-10:],
                       "studentText": state["student_text"]}, ensure_ascii=False)
    reply = _completion(system, user).strip()
    if not reply:
        raise ValueError("课堂导师没有返回内容")
    notices = {
        "enter_recall": "现在进入【初始复述】，我们按知识点逐个回顾。",
        "enter_reinforce": "现在进入【加强复述】，我们一起补强刚才还没讲清的内容。",
        "enter_discuss": ("现在进入【深入讨论】。每个已掌握的知识点各讨论一个问题，"
                          "全部完成后进入课堂总结。"),
    }
    notice = notices.get(state.get("transition"))
    return {"reply": f"{notice}\n\n{reply}" if notice else reply}


builder = StateGraph(DialogueState)
builder.add_node("evaluate", evaluate)
builder.add_node("route", route)
builder.add_node("respond", respond)
builder.add_edge(START, "evaluate")
builder.add_edge("evaluate", "route")
builder.add_edge("route", "respond")
builder.add_edge("respond", END)
dialogue_graph = builder.compile()


def opening(points: list[dict]) -> str:
    return opening_message(points)
