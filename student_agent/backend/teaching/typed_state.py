"""Program-owned progress for typed lessons. No model, storage or transport calls."""
from copy import deepcopy
from backend.teaching import requirements, concept_guidance

VERSION = 4


class InvalidObservation(ValueError):
    """A request quote has no provenance in the current learner message."""


def active(dialogue):
    return bool(dialogue and dialogue.get("flow_version") == VERSION)


def initial(points, *, explanation=False):
    state = {"flow_version": VERSION, "mastery_version": 1, "reply_version": 1, "stage": "recall", "recall_round_limit": 5,
            "reinforce_round_limit": 8, "transition": "continue", "strategy": "ask",
            "messages": [], "student_text": "", "evaluation": {}, "reply": "",
            "last_point_id": None, "current_task": None,
            "points": [dict(deepcopy(p), status="unseen", evidence="", attempts=0,
                recall_attempts=0, reinforce_attempts=0, recall_done=False, reinforce_done=False,
                reinforcement_required=False, excluded_from_discussion=False, mastered_in=None,
                assessment_history=[], known_parts=[], gaps=[], next_step="", help_history=[],
                task_question="", requirements=[] if explanation else requirements.initial(p), question_targets=[],
                latest_question="", question_history=[]) for p in points]}
    if explanation:
        state.update(assessment_basis="explanation", mastery_version=0)
        for point in state["points"]:
            point.setdefault("title", point["name"])
    return state


def explanation_based(state):
    return state.get("assessment_basis") == "explanation"


def natural_reply(state):
    return (scoped(state) or explanation_based(state)) and state.get("reply_version") == 1


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
        if unresolved_feedback or (entry.get("answer_assessment") if explanation_based(state) else (entry.get("answer_assessment") or {}).get("updates")):
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
    if control != "none":
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
            "control": {"request": control, "applied": bool(after_class and control == "skip" and state.get("transition") == "postclass_next")},
            "solicitation": "none" if (action in {"respond", "concept_explain"} or (
                explanation_based(state) and action == "explain" and point.get("question_history")
                and point["question_history"][-1].get("planned_action") == "clarify")) else "one_task" if action == "concept_hint" else "none" if (not changed and action != "clarify" and (
                observation.get("help_quote") or action == "correct"
                or any(r["status"] == "needs_help" for r in pending))) else "one_task"}


def current(state, *, after_class=False):
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


def previous_point(state, *, after_class=False):
    focus = current(state, after_class=after_class)
    if not focus:
        return None
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
    result = deepcopy(state)
    point = current(result, after_class=after_class)
    if not point:
        raise ValueError("当前没有待评估的知识点")
    if observation is not None:
        observation = deepcopy(observation)
        for key in ("help_quote", "continue_quote", "teacher_feedback", "control_quote"):
            quote = observation.get(key, "")
            if quote and (not quote.strip() or quote not in result["student_text"]):
                raise InvalidObservation("observation 的非空引文必须逐字来自本轮 studentText。请重新选取对应诉求的最小连续原文；没有对应表达的字段留空，不改写或引用老师、历史发言。保留本轮实际作答评估后重新调用工具。")
            # Punctuation/emoji alone conveys no specific request to explain a
            # topic; leave it for clarification rather than inventing a question.
            if quote and not any(char.isalnum() for char in quote):
                observation[key] = ""
        if observation.get("control", "none") != "none" and not observation.get("control_quote"):
            raise InvalidObservation("control 非 none 时必须用本轮学生原文填写 control_quote；没有明确导航请求则将 control 改为 none、control_quote 留空。仅表示继续用 continue_quote。修正后重新调用工具，不自行执行导航。")
        help_quote = observation.get("help_quote", "")
        continue_quote = observation.get("continue_quote", "")
        if help_quote and continue_quote:
            text = result["student_text"]
            disjoint = (text.find(help_quote) + len(help_quote) <= text.rfind(continue_quote)
                        or text.find(continue_quote) + len(continue_quote) <= text.rfind(help_quote))
            if not disjoint:
                raise InvalidObservation("help_quote 与 continue_quote 的引文不能重叠，必须分别引用最小原文片段。具体求助、明确不会或要求讲解用 help_quote，确认或继续用 continue_quote；没有对应诉求则留空，不能把同一片段重复归类。请修正后重新调用工具。")
    submitted = deepcopy(assessment)
    if scoped(result):
        assessment = requirements.apply(point, assessment, result["student_text"])
    if explanation_based(result) and assessment:
        if not assessment["evidence"].strip():
            raise InvalidObservation("非空 assessment 必须说明可核对的学生表现。请引用实际学生原话、步骤或正式题卡选择，区分本轮表现和累计覆盖；没有可评估表现时用 null，正式题卡提交除外。不要为填 evidence 编造表现，修正后重新调用工具。")
        if assessment["result"] == "mastered" and (assessment["gaps"] or not assessment["known_parts"]):
            raise InvalidObservation("mastered 要求 known_parts 有真实学生证据支持且 gaps 为空。请重新核对课程内容和累计学生表现；仍有未确认内容或需要帮助的缺口时使用相符的非 mastered 结果。不能通过删除真实缺口或编造已会内容来通过校验。修正后重新调用工具。")
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
    point["attempts"] = point["recall_attempts"] + point["reinforce_attempts"]
    point["assessment_history"].append({"stage": stage, "round": point[counter],
        "result": outcome, "evidence": evidence, "studentText": result["student_text"]})
    if observation and observation.get("teacher_feedback"):
        point["assessment_history"][-1]["teacher_feedback"] = observation["teacher_feedback"]
    if scoped(result) or explanation_based(result):
        point["assessment_history"][-1].update(
            result=(submitted["result"] if explanation_based(result) else submitted["answer_result"]) if submitted else "unclear", point_result=outcome,
            answer_assessment=submitted, target_ids=deepcopy(point["question_targets"]),
            question=point["latest_question"])
    result["evaluation"] = {"intent": intent, "assessments": [
        {"id": point["id"], **deepcopy(assessment)}] if assessment else []}
    if observation is not None:
        result["evaluation"]["observation"] = deepcopy(observation)
    if assessment:
        point.update(status=outcome, evidence=evidence, known_parts=assessment["known_parts"],
                     gaps=assessment["gaps"], next_step=assessment["next_step"])
    elif point["status"] == "unseen":
        point["status"] = "unclear"
    result["strategy"] = ("answer_question" if intent == "question" else "correct" if outcome == "misconception"
                          else "clarify" if outcome == "unclear" else "hint")
    result["transition"] = "continue"
    if outcome == "mastered":
        result["selected_point_id"] = None
        point.update(recall_done=True, reinforce_done=True, reinforcement_required=False,
                     mastered_in=stage, gaps=[])
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
                ("从这个知识点的当前任务开始；若尚无任务，再开始第一问。" if not attempted else "接着原任务，继续尚未完成或尚未确认的部分。")})
        if scoped(state):
            entries[-1]["requirements"] = requirements.public(point)
    counts = {k: sum(p["category"] == k for p in entries) for k in ("mastered", "needs_review", "not_assessed")}
    return {"schemaVersion": 4, "typedTeaching": True, "points": entries, "counts": counts,
            "endedEarly": state.get("completion_reason") == "student_ended_early",
            "summary": f"本课共 {len(entries)} 个知识点：{counts['mastered']} 个已掌握，"
                       f"{counts['needs_review']} 个待巩固或尚未确认，{counts['not_assessed']} 个尚未学习／评估。"}
