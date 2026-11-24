"""Program-owned progress for typed lessons. No model, storage or transport calls."""
from copy import deepcopy
from backend.teaching import requirements, concept_guidance

VERSION = 4


class InvalidObservation(ValueError):
    """A request quote has no provenance in the current learner message."""


def active(dialogue):
    return bool(dialogue and dialogue.get("flow_version") == VERSION)


def continuous(dialogue):
    return active(dialogue) and dialogue.get("dialogue_version") == 1


def initial(points):
    return {"flow_version": VERSION, "mastery_version": 1, "reply_version": 1, "stage": "recall", "recall_round_limit": 5,
            "reinforce_round_limit": 8, "transition": "continue", "strategy": "ask",
            "messages": [], "student_text": "", "evaluation": {}, "reply": "",
            "last_point_id": None, "current_task": None,
            "points": [dict(deepcopy(p), status="unseen", evidence="", attempts=0,
                recall_attempts=0, reinforce_attempts=0, recall_done=False, reinforce_done=False,
                reinforcement_required=False, excluded_from_discussion=False, mastered_in=None,
                assessment_history=[], known_parts=[], gaps=[], next_step="", help_history=[],
                task_question="", requirements=requirements.initial(p), question_targets=[],
                latest_question="", question_history=[]) for p in points]}


def scoped(state):
    return state.get("mastery_version") == 1


def teaching_plan(state, *, after_class=False):
    point = current(state, after_class=after_class)
    if not point:
        return {"target_ids": [], "action": "summarize"}
    pending = [r for r in point["requirements"] if r["status"] != "demonstrated"]
    history = point["assessment_history"]
    last_result = history[-1]["result"] if history else None
    action = ("ask" if not history else
              "explain" if (state.get("evaluation") or {}).get("intent") == "question" else
              "clarify" if len(history) >= 2 and all(h["result"] in {"unanswered", "unclear"} for h in history[-2:]) else
              "clarify" if last_result == "unclear" else
              "correct" if last_result == "misconception" else
              "explain" if last_result == "unanswered" or any(r["status"] == "needs_help" for r in pending) else "ask")
    # A coverage scope, not a queue of questions. Unasked requirements remain
    # unconfirmed until the learner supplies evidence; help targets real gaps.
    pending.sort(key=lambda r: r["status"] != "needs_help")
    evaluation = state.get("evaluation") or {}
    observation = evaluation.get("observation") or {}
    previous_id = state.get("last_point_id")
    changed = bool(previous_id and previous_id != point["id"])
    control = observation.get("control", "none")
    updates = (history[-1].get("answer_assessment") or {}).get("updates", []) if history else []
    unresolved_feedback = observation.get("teacher_feedback", "")
    for entry in reversed(history):
        if unresolved_feedback or (entry.get("answer_assessment") or {}).get("updates"):
            break
        unresolved_feedback = entry.get("teacher_feedback", "")
    failed_help = bool(unresolved_feedback and last_result != "misconception")
    if not changed:
        if control != "none":
            action = "respond"
        elif failed_help:
            action = "clarify"
        elif observation.get("help_quote"):
            action = "correct" if last_result == "misconception" else "explain"
        elif observation.get("continue_quote"):
            action = "ask"
        elif "observation" in evaluation and evaluation.get("intent") == "unclear" and not updates:
            # No actual request or learner work: do not invent a help topic from
            # the coarse 'unanswered' label (e.g. punctuation-only input).
            action = "clarify"
    if control in {"pause", "revisit"}:
        # Preserve any real learning evidence, but do not ignore the coexisting
        # control request merely because mastery moved the program to a new point.
        action = "respond"
    action = concept_guidance.select_action(
        point, pending, evaluation, state.get("student_text", ""),
        changed=changed, fallback=action)
    return {"target_ids": [r["id"] for r in pending], "action": action,
            "requirements": [r["text"] for r in pending], "point_changed": changed,
            "unresolved_teacher_feedback": unresolved_feedback,
            "answer_result": last_result if not changed else next(
                (p["assessment_history"][-1]["result"] for p in state["points"]
                 if p["id"] == previous_id and p["assessment_history"]), None),
            "control": {"request": control, "applied": bool(after_class and changed and control == "skip")},
            "solicitation": "none" if action in {"respond", "concept_explain"} else "one_task" if action == "concept_hint" else "none" if (not changed and action != "clarify" and (
                observation.get("help_quote") or action == "correct"
                or any(r["status"] == "needs_help" for r in pending))) else "one_task"}


def current(state, *, after_class=False):
    if continuous(state):
        selected = state.get("focus_id", state["points"][0]["id"] if state["points"] else None)
        return next((point for point in state["points"] if point["id"] == selected), None)
    review_id = state.get("review_point_id")
    if review_id:
        review = next((p for p in state["points"] if p["id"] == review_id), None)
        if review:
            return review
    if after_class:
        selected = state.get("postclass_point_id")
        if selected:
            point = next((p for p in state["points"] if p["id"] == selected and p["status"] != "mastered"), None)
            if point:
                return point
        return next((p for p in state["points"] if p["status"] != "mastered"), None)
    selected = state.get("selected_point_id")
    if selected and state["stage"] in {"recall", "reinforce"}:
        point = next((p for p in state["points"] if p["id"] == selected and p["status"] != "mastered"), None)
        if point:
            return point
    if state["stage"] == "recall":
        return next((p for p in state["points"] if not p["recall_done"]), None)
    if state["stage"] == "reinforce":
        return next((p for p in state["points"] if p["status"] != "mastered" and not p["reinforce_done"]), None)
    return None


def next_point(state, *, after_class=False):
    focus = current(state, after_class=after_class)
    if not focus:
        return None
    index = state["points"].index(focus)
    return state["points"][index + 1] if index + 1 < len(state["points"]) else None


def can_skip_last(state, *, after_class=False):
    focus = current(state, after_class=after_class)
    return bool(focus and focus["status"] != "mastered" and not next_point(state, after_class=after_class))


def previous_point(state, *, after_class=False):
    focus = current(state, after_class=after_class)
    if not focus:
        return state["points"][-1] if continuous(state) and state["points"] else None
    index = state["points"].index(focus)
    return state["points"][index - 1] if index else None


def skip_to_next(state, *, after_class=False):
    result = deepcopy(state)
    focus = current(result, after_class=after_class)
    following = next_point(result, after_class=after_class)
    if not focus or not following:
        raise ValueError("没有下一个待学习知识点")
    if after_class:
        result["postclass_point_id"] = following["id"]
    else:
        field = "recall_done" if result["stage"] == "recall" else "reinforce_done"
        if focus["status"] != "mastered":
            focus[field] = True
        if result["stage"] == "recall" and focus["status"] != "mastered":
            focus["reinforcement_required"] = True
        result["selected_point_id"] = following["id"]
    result["review_point_id"] = following["id"] if following["status"] == "mastered" else None
    result["transition"] = "manual_next"
    result["current_task"] = task(result, after_class=after_class)
    return result


def go_to_previous(state, *, after_class=False):
    result = deepcopy(state)
    previous = previous_point(result, after_class=after_class)
    if not previous:
        raise ValueError("没有上一个知识点")
    result["review_point_id"] = previous["id"]
    result["current_task"] = task(result, after_class=after_class)
    return result


def task(state, *, after_class=False):
    point = current(state, after_class=after_class)
    return ({"pointId": point["id"], "stage": "postclass" if after_class else state["stage"],
             "question": point["task_question"]} if point else None)


def advance(state, intent, assessment, *, after_class=False, observation=None, count_attempt=True):
    # 在副本上完成整轮校验和推进，任何异常都不会污染调用方的原始状态。
    result = deepcopy(state)
    point = current(result, after_class=after_class)
    if not point:
        raise ValueError("当前没有待评估的知识点")
    if observation is not None:
        # 求助、继续、纠错和控制请求必须引用本轮学生原文，避免模型编造学生诉求。
        observation = deepcopy(observation)
        for key in ("help_quote", "continue_quote", "teacher_feedback", "control_quote"):
            quote = observation.get(key, "")
            if quote and (not quote.strip() or quote not in result["student_text"]):
                raise InvalidObservation("本轮诉求依据必须逐字引用当前学生输入")
            # Punctuation/emoji alone conveys no specific request to explain a
            # topic; leave it for clarification rather than inventing a question.
            if quote and not any(char.isalnum() for char in quote):
                observation[key] = ""
        if observation.get("control", "none") != "none" and not observation.get("control_quote"):
            raise InvalidObservation("控制请求必须包含本轮学生原文依据")
        help_quote = observation.get("help_quote", "")
        continue_quote = observation.get("continue_quote", "")
        if help_quote and continue_quote:
            text = result["student_text"]
            disjoint = (text.find(help_quote) + len(help_quote) <= text.rfind(continue_quote)
                        or text.find(continue_quote) + len(continue_quote) <= text.rfind(help_quote))
            if not disjoint:
                raise InvalidObservation("确认/继续与具体求助的原文片段不能重叠；请分别引用最小片段。没有具体内容疑问、明确不会或讲解请求时，help_quote留空。")
    submitted = deepcopy(assessment)
    # 保留模型原始提交供历史审阅，再用程序汇总逐项要求得到整点结果。
    if scoped(result):
        assessment = requirements.apply(point, assessment, result["student_text"])
    old_stage = result["stage"]
    result["last_point_id"] = point["id"]
    outcome = assessment["result"] if assessment else "unclear"
    evidence = assessment["evidence"] if assessment else ""
    if after_class:
        counter, stage = "postclass_rounds", "postclass"
    else:
        counter = "recall_attempts" if old_stage == "recall" else "reinforce_attempts"
        stage = old_stage
    point[counter] = point.get(counter, 0) + int(count_attempt)
    # 是否计次由调用方决定，例如尚未完成的题组可以分次提交而不重复消耗轮数。
    point["attempts"] = point["recall_attempts"] + point["reinforce_attempts"]
    point["assessment_history"].append({"stage": stage, "round": point[counter],
        "result": outcome, "evidence": evidence, "studentText": result["student_text"]})
    if observation and observation.get("teacher_feedback"):
        point["assessment_history"][-1]["teacher_feedback"] = observation["teacher_feedback"]
    if scoped(result):
        point["assessment_history"][-1].update(
            result=submitted["answer_result"] if submitted else "unclear", point_result=outcome,
            answer_assessment=submitted, target_ids=deepcopy(point["question_targets"]),
            question=point["latest_question"])
    result["evaluation"] = {"intent": intent, "assessments": [
        {"id": point["id"], **deepcopy(assessment)}] if assessment else []}
    if observation is not None:
        result["evaluation"]["observation"] = deepcopy(observation)
    # 只有真实评估才覆盖证据摘要。纯求助仍写入历史，但保留上次有效的学习证据。
    if submitted:
        point.update(status=outcome, evidence=evidence, known_parts=assessment["known_parts"],
                     gaps=assessment["gaps"], next_step=assessment["next_step"])
    elif not scoped(result) and point["status"] == "unseen":
        point["status"] = "unclear"
    result["strategy"] = ("answer_question" if intent == "question" else "correct" if outcome == "misconception"
                          else "clarify" if outcome == "unclear" else "hint")
    result["transition"] = "continue"
    if outcome == "mastered":
        # 先检查掌握，再检查轮数，确保最后一次允许的回答仍可正常过关。
        result["selected_point_id"] = None
        point.update(recall_done=True, reinforce_done=True, reinforcement_required=False,
                     mastered_in=stage, gaps=[])
        result["transition"] = "mastered_next"
    elif not after_class:
        # 达到课堂限额只结束该点本阶段的教学，保留缺口供补强或课后继续。
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
            result["selected_point_id"] = None
            result["transition"] = "enter_" + result["stage"]
        if result["stage"] == "wrapup":
            result["completion_reason"] = ("all_mastered" if all(p["status"] == "mastered" for p in result["points"])
                                           else "rounds_exhausted")
    else:
        # Navigation is independent of mastery. Persist the selected point so
        # the next command/resume cannot silently pick the first gap again.
        if observation and observation.get("control") == "skip":
            index = result["points"].index(point)
            ordered = result["points"][index + 1:] + result["points"][:index]
            following = next((p for p in ordered if p["status"] != "mastered"), None)
            if following:
                result["postclass_point_id"] = following["id"]
                result["transition"] = "postclass_next"
        if current(result, after_class=True) is None:
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
        if scoped(state) and category == "needs_review":
            label = "待巩固" if any(r["status"] == "needs_help" for r in point["requirements"]) else "本次尚未确认"
        entries.append({"id": point["id"], "title": point["title"], "category": category, "label": label,
            "status": point["status"], "knownParts": deepcopy(point["known_parts"]), "gaps": deepcopy(point["gaps"]),
            "evidence": point["evidence"], "suggestion": "" if category == "mastered" else point["next_step"] or
                ("从这个知识点的第一问开始学习。" if not attempted else "接着原题，先说清还不确定的地方。")})
        if scoped(state):
            entries[-1]["requirements"] = requirements.public(point)
        if continuous(state):
            entries[-1]["skipped"] = bool(point.get("skipped"))
            if point.get("open_issue") and category != "mastered":
                entries[-1]["suggestion"] = point["open_issue"]["text"]
    counts = {k: sum(p["category"] == k for p in entries) for k in ("mastered", "needs_review", "not_assessed")}
    return {"schemaVersion": 4, "typedTeaching": True, "points": entries, "counts": counts,
            "endedEarly": state.get("completion_reason") == "student_ended_early",
            "summary": f"本课 {len(entries)} 个知识点：{counts['mastered']} 个已掌握，"
                       f"{counts['needs_review']} 个待巩固，{counts['not_assessed']} 个尚未学习／评估。"}
