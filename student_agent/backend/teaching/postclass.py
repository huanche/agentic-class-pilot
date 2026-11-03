"""Postclass remediation followed by open questions in the same tutor chat."""
from __future__ import annotations

import json
from typing import TypedDict

from langgraph.graph import START, END, StateGraph

from backend.teaching.postclass_state import pending_kind
from backend.teaching.postclass_state import prepare_points
from backend.teaching.postclass_state import pending_points
from backend.teaching.postclass_state import opening_task
from backend.teaching.postclass_state import postclass_stage
from backend.teaching.postclass_state import apply_assessment
from backend.infrastructure import model
from backend.teaching.prompts import POSTCLASS_ASSESS_PROMPT as ASSESS_PROMPT
from backend.teaching.prompts import POSTCLASS_REMEDIATION_PROMPT as REMEDIATION_PROMPT
from backend.teaching.prompts import POSTCLASS_OPEN_PROMPT as OPEN_PROMPT


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
    raw = model.complete(ASSESS_PROMPT, json.dumps({
        "focus": focus, "taskType": pending_kind(focus), "classroomDiscussion": focus.get("discussion_context", []), "recentMessages": state["messages"][-8:],
        "studentText": state["student_text"]}, ensure_ascii=False))
    value = model.json_object(raw)
    if value.get("result") not in {"mastered", "partial", "misconception", "unanswered", "unclear"}:
        raise ValueError("课后复述评估格式不正确")
    return {"assessment": value}


def advance(state: PostclassState) -> dict:
    if state["stage"] == "open":
        return {"transition": "open"}
    focus = pending_points(state["points"])[0]
    old_kind = pending_kind(focus)
    points = apply_assessment(state["points"], focus["id"], state["assessment"], state["student_text"])
    stage = postclass_stage(points)
    transition = "open" if stage == "open" else "next" if (pending_points(points)[0]["id"] != focus["id"] or pending_kind(pending_points(points)[0]) != old_kind) else "continue"
    return {"points": points, "stage": stage, "transition": transition}


def respond(state: PostclassState) -> dict:
    if state["transition"] == "open" and state["assessment"]:
        return {"reply": "这部分已经能用自己的话讲清楚了。课堂未完成的学习任务都已补完；现在可以自由向我提问其他问题。"}
    focus = pending_points(state["points"])[0] if state["stage"] == "remediation" else None
    system = REMEDIATION_PROMPT if state["stage"] == "remediation" else OPEN_PROMPT
    raw = model.complete(system, json.dumps({
        "focus": focus, "taskType": pending_kind(focus) if focus else None, "classroomDiscussion": (focus or {}).get("discussion_context", []), "nextFocus": focus if state["transition"] == "next" else None,
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
