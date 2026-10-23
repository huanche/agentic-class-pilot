"""Postclass remediation followed by open questions in the same tutor chat."""
from __future__ import annotations

import copy
import json
from typing import TypedDict

from langgraph.graph import START, END, StateGraph

from .graph import _completion, _json_object


def pending_points(points: list[dict]) -> list[dict]:
    return [point for point in points if point.get("status") != "mastered"]


def postclass_stage(points: list[dict]) -> str:
    return "remediation" if pending_points(points) else "open"


def apply_assessment(points: list[dict], point_id: str, assessment: dict | None,
                     student_text: str) -> list[dict]:
    result = copy.deepcopy(points)
    current = next((point for point in pending_points(result) if point["id"] == point_id), None)
    if current is None or pending_points(result)[0]["id"] != point_id:
        raise ValueError("只能评估当前课后补完的知识点")
    current["postclass_rounds"] = int(current.get("postclass_rounds") or 0) + 1
    outcome = (assessment or {}).get("result", "unclear")
    evidence = str((assessment or {}).get("evidence") or student_text)[:1000]
    current.setdefault("assessment_history", []).append({
        "stage": "postclass", "round": current["postclass_rounds"],
        "result": outcome, "evidence": evidence, "studentText": student_text,
    })
    if outcome == "mastered":
        current.update(status="mastered", mastered_in="postclass",
                       excluded_from_discussion=False, evidence=evidence)
    elif outcome in {"partial", "misconception"}:
        current.update(status=outcome, evidence=evidence)
    return result


ASSESS_PROMPT = """你是课后复述评估员，只评估 focus 这一个知识点。学生问题或“懂了”等确认不能判掌握；
只有学生独立、准确地用自己的话解释视频中这个概念的核心含义，才能判 mastered。
只输出 JSON：{"result":"mastered|partial|misconception|unanswered|unclear","evidence":"学生表达中的具体依据"}。
学生问问题时返回 unclear；只重复 AI 刚给出的答案不能判掌握。"""

REMEDIATION_PROMPT = """你是课后课堂导师。先回应学生刚说的话或问题，再帮助他复述 focus。
focus.content 是当前视频的原文依据，不要编造视频没讲的结论。若 assessment 显示仍未掌握，
给出一点具体提示，并只问一个下一步问题；不要直接代替学生完成复述。
若 transition 为 next，肯定刚掌握的内容，再引导复述 nextFocus。
若 transition 为 open，说明课堂未掌握的知识点已补完，可以自由提问其他问题。
不要透露内部评分或状态名。用自然、简洁的中文回答。"""

OPEN_PROMPT = """你是学生的课后 AI 学习伙伴。课堂知识点已经补完，学生可以自由提问。
结合最近对话回答；课堂内容可作为背景，但也可以解答其他合理的学习问题。
若超出视频内容，明确区分一般解释与视频实际讲解。不要编造视频原文。
用自然、准确、简洁的中文回答。"""


class PostclassState(TypedDict):
    points: list[dict]
    messages: list[dict]
    student_text: str
    stage: str
    assessment: dict
    transition: str
    reply: str


def evaluate(state: PostclassState) -> dict:
    if state["stage"] == "open":
        return {"assessment": {}}
    focus = pending_points(state["points"])[0]
    raw = _completion(ASSESS_PROMPT, json.dumps({
        "focus": focus, "recentMessages": state["messages"][-8:],
        "studentText": state["student_text"]}, ensure_ascii=False))
    value = _json_object(raw)
    if value.get("result") not in {"mastered", "partial", "misconception", "unanswered", "unclear"}:
        raise ValueError("课后复述评估格式不正确")
    return {"assessment": value}


def advance(state: PostclassState) -> dict:
    if state["stage"] == "open":
        return {"transition": "open"}
    focus = pending_points(state["points"])[0]
    points = apply_assessment(state["points"], focus["id"], state["assessment"], state["student_text"])
    stage = postclass_stage(points)
    transition = "open" if stage == "open" else "next" if pending_points(points)[0]["id"] != focus["id"] else "continue"
    return {"points": points, "stage": stage, "transition": transition}


def respond(state: PostclassState) -> dict:
    if state["transition"] == "open" and state["assessment"]:
        return {"reply": "这部分已经能用自己的话讲清楚了。课堂上未掌握的知识点都已补完；现在可以自由向我提问其他问题。"}
    focus = pending_points(state["points"])[0] if state["stage"] == "remediation" else None
    system = REMEDIATION_PROMPT if state["stage"] == "remediation" else OPEN_PROMPT
    raw = _completion(system, json.dumps({
        "focus": focus, "nextFocus": focus if state["transition"] == "next" else None,
        "assessment": state["assessment"], "transition": state["transition"],
        "recentMessages": state["messages"][-10:], "studentText": state["student_text"],
    }, ensure_ascii=False)).strip()
    if not raw:
        raise ValueError("课后导师没有返回内容")
    return {"reply": raw}


builder = StateGraph(PostclassState)
builder.add_node("evaluate", evaluate)
builder.add_node("advance", advance)
builder.add_node("respond", respond)
builder.add_edge(START, "evaluate")
builder.add_edge("evaluate", "advance")
builder.add_edge("advance", "respond")
builder.add_edge("respond", END)
postclass_graph = builder.compile()
