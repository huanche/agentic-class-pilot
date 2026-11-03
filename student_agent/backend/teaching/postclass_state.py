"""Pure classroom-to-postclass state projection; no model or database."""
from __future__ import annotations
import copy

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
