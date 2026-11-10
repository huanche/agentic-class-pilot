"""Program-owned progress for typed lessons. No model, storage or transport calls."""
from copy import deepcopy

VERSION = 4


def active(dialogue):
    return bool(dialogue and dialogue.get("flow_version") == VERSION)


def initial(points):
    return {"flow_version": VERSION, "stage": "recall", "recall_round_limit": 5,
            "reinforce_round_limit": 8, "transition": "continue", "strategy": "ask",
            "messages": [], "student_text": "", "evaluation": {}, "reply": "",
            "last_point_id": None, "current_task": None,
            "points": [dict(deepcopy(p), status="unseen", evidence="", attempts=0,
                recall_attempts=0, reinforce_attempts=0, recall_done=False, reinforce_done=False,
                reinforcement_required=False, excluded_from_discussion=False, mastered_in=None,
                assessment_history=[], known_parts=[], gaps=[], next_step="", help_history=[],
                task_question="") for p in points]}


def current(state, *, after_class=False):
    if after_class:
        return next((p for p in state["points"] if p["status"] != "mastered"), None)
    if state["stage"] == "recall":
        return next((p for p in state["points"] if not p["recall_done"]), None)
    if state["stage"] == "reinforce":
        return next((p for p in state["points"] if p["status"] != "mastered" and not p["reinforce_done"]), None)
    return None


def task(state, *, after_class=False):
    point = current(state, after_class=after_class)
    return ({"pointId": point["id"], "stage": "postclass" if after_class else state["stage"],
             "question": point["task_question"]} if point else None)


def advance(state, intent, assessment, *, after_class=False):
    result = deepcopy(state)
    point = current(result, after_class=after_class)
    if not point:
        raise ValueError("当前没有待评估的知识点")
    old_stage = result["stage"]
    result["last_point_id"] = point["id"]
    submitted_assessment = deepcopy(assessment)
    if assessment and assessment["result"] == "mastered" and assessment["gaps"]:
        assessment = {**assessment, "result": "partial"}
    outcome = assessment["result"] if assessment else "unclear"
    evidence = assessment["evidence"] if assessment else ""
    if after_class:
        counter, stage = "postclass_rounds", "postclass"
    else:
        counter = "recall_attempts" if old_stage == "recall" else "reinforce_attempts"
        stage = old_stage
    point[counter] = point.get(counter, 0) + 1
    point["attempts"] = point["recall_attempts"] + point["reinforce_attempts"]
    point["assessment_history"].append({"stage": stage, "round": point[counter],
        "result": outcome, "evidence": evidence, "studentText": result["student_text"],
        "submitted_assessment": submitted_assessment})
    result["evaluation"] = {"intent": intent, "assessments": [
        {"id": point["id"], **deepcopy(assessment)}] if assessment else []}
    if assessment:
        point.update(status=outcome, evidence=evidence, known_parts=assessment["known_parts"],
                     gaps=assessment["gaps"], next_step=assessment["next_step"])
    elif point["status"] == "unseen":
        point["status"] = "unclear"
    result["strategy"] = ("answer_question" if intent == "question" else "correct" if outcome == "misconception"
                          else "clarify" if outcome == "unclear" else "hint")
    result["transition"] = "continue"
    if outcome == "mastered":
        point.update(recall_done=True, reinforce_done=True, reinforcement_required=False,
                     mastered_in=stage)
        result["transition"] = "mastered_next"
    elif not after_class:
        limit = result["recall_round_limit" if old_stage == "recall" else "reinforce_round_limit"]
        if point[counter] >= limit:
            point["recall_done" if old_stage == "recall" else "reinforce_done"] = True
            point["reinforcement_required"] = old_stage == "recall"
            result["transition"] = "defer" if old_stage == "recall" else "record_gap"
    if not after_class:
        if all(p["recall_done"] for p in result["points"]):
            result["stage"] = "reinforce" if any(
                p["status"] != "mastered" and not p["reinforce_done"] for p in result["points"]) else "wrapup"
        if result["stage"] != old_stage:
            result["transition"] = "enter_" + result["stage"]
        if result["stage"] == "wrapup":
            result["completion_reason"] = ("all_mastered" if all(p["status"] == "mastered" for p in result["points"])
                                           else "rounds_exhausted")
    elif current(result, after_class=True) is None:
        result["transition"] = "all_mastered"
    result["current_task"] = task(result, after_class=after_class)
    return result


def progress(state):
    point = current(state)
    return {"total": len(state["points"]), "recallCompleted": sum(p["recall_done"] for p in state["points"]),
            "currentPoint": point["title"] if point else None,
            "reinforcementStarted": state["stage"] == "reinforce" or any(p["reinforce_attempts"] for p in state["points"]),
            "completionReason": state.get("completion_reason")}


def feedback(session):
    state = session["dialogue"]
    entries = []
    for point in state["points"]:
        attempted = bool(point["assessment_history"])
        category = ("mastered" if point["status"] == "mastered" else "not_assessed" if not attempted else "needs_review")
        label = ("已掌握" if category == "mastered" else "尚未学习／评估" if not attempted
                 else "待巩固" if point["gaps"] else "本次尚未确认")
        entries.append({"id": point["id"], "title": point["title"], "category": category, "label": label,
            "status": point["status"], "knownParts": deepcopy(point["known_parts"]), "gaps": deepcopy(point["gaps"]),
            "evidence": point["evidence"], "suggestion": "" if category == "mastered" else point["next_step"] or
                ("从这个知识点的第一问开始学习。" if not attempted else "接着原题，先说清还不确定的地方。")})
    counts = {k: sum(p["category"] == k for p in entries) for k in ("mastered", "needs_review", "not_assessed")}
    return {"schemaVersion": 4, "typedTeaching": True, "points": entries, "counts": counts,
            "endedEarly": state.get("completion_reason") == "student_ended_early",
            "summary": f"本课 {len(entries)} 个知识点：{counts['mastered']} 个已掌握，"
                       f"{counts['needs_review']} 个待巩固，{counts['not_assessed']} 个尚未学习／评估。"}
