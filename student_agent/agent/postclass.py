"""Postclass remediation followed by open questions in the same tutor chat."""
from __future__ import annotations

import copy
import json
from typing import TypedDict

from langgraph.graph import START, END, StateGraph

from .graph import _completion, _json_object
from .prompts import POSTCLASS_ASSESS_PROMPT as ASSESS_PROMPT, POSTCLASS_REMEDIATION_PROMPT as REMEDIATION_PROMPT, POSTCLASS_OPEN_PROMPT as OPEN_PROMPT


def pending_kind(point: dict) -> str | None:
    if point.get("status") != "mastered":
        return "concept"
    if point.get("reinforcement_required") and not point.get("reinforce_done"):
        return "confirmation"
    if point.get("discussion_required") and point.get("discussion_result") != "mastered":
        return "discussion"
    return None


def prepare_points(dialogue: dict, messages: list[dict]) -> list[dict]:
    points = copy.deepcopy(dialogue["points"])
    remaining = (dialogue.get("discussion_point_ids") or [])[dialogue.get("discussion_index", 0):]
    for point in points:
        if (point["id"] in remaining
                or point.get("discussion_result") in {"partial", "misconception", "unanswered"}
                or (dialogue.get("completion_reason") == "student_ended_early"
                    and not point.get("excluded_from_discussion"))):
            point["discussion_required"] = True
            point.setdefault("discussion_context", [m for m in messages if m.get("phase") == "discuss"][-10:]
                             if (remaining and point["id"] == remaining[0]) or point.get("discussion_result") else [])
    return points


def pending_points(points: list[dict]) -> list[dict]:
    return [point for point in points if pending_kind(point)]


def opening_task(point: dict) -> str:
    kind = pending_kind(point)
    if kind == "discussion":
        if not point.get("discussion_context"):
            return f"我们继续「{point['title']}」的讨论：请结合一个具体例子，解释它如何发挥作用。"
        return f"我们继续「{point['title']}」尚未完成的讨论。请继续回答之前的讨论题；如果不记得题目，可以请我提示。"
    if kind == "confirmation":
        return f"「{point['title']}」已在首轮掌握，还需要一次加强确认。请用自己的话再解释它的核心含义或关键关系。"
    return f"我们先继续「{point['title']}」的概念复述：请用自己的话说说你的理解，不记得可以请我提示。"


def postclass_stage(points: list[dict]) -> str:
    return "remediation" if pending_points(points) else "open"


def apply_assessment(points: list[dict], point_id: str, assessment: dict | None,
                     student_text: str) -> list[dict]:
    result = copy.deepcopy(points)
    current = next((point for point in pending_points(result) if point["id"] == point_id), None)
    if current is None or pending_points(result)[0]["id"] != point_id:
        raise ValueError("只能评估当前课后补完的知识点")
    kind = pending_kind(current)
    current["postclass_rounds"] = int(current.get("postclass_rounds") or 0) + 1
    outcome = (assessment or {}).get("result", "unclear")
    evidence = str((assessment or {}).get("evidence") or student_text)[:1000]
    current.setdefault("assessment_history", []).append({
        "stage": "postclass_discuss" if kind == "discussion" else "postclass", "taskType": kind, "round": current["postclass_rounds"],
        "result": outcome, "evidence": evidence, "studentText": student_text,
    })
    if kind == "discussion":
        current.update(discussion_result=outcome, discussion_evidence=evidence)
        return result
    if outcome == "mastered":
        current.update(status="mastered", mastered_in="postclass",
                       excluded_from_discussion=False, evidence=evidence, recall_done=True, reinforce_done=True)
    elif outcome in {"partial", "misconception"}:
        current.update(status=outcome, evidence=evidence)
    return result


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
        "focus": focus, "taskType": pending_kind(focus), "classroomDiscussion": focus.get("discussion_context", []), "recentMessages": state["messages"][-8:],
        "studentText": state["student_text"]}, ensure_ascii=False))
    value = _json_object(raw)
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
    raw = _completion(system, json.dumps({
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
