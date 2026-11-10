"""Stable tasks, messages, learner evidence and delivered tutor help.

Pure functions return record candidates. Persistence commits them with the turn.
Legacy links stay unknown; model judgements are never promoted to proof of mastery.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from backend.content import lesson_content
from backend.contracts import identity
from backend.contracts import is_dynamic_flow
from backend.contracts import LEGACY_FLOW
from backend.evidence.feedback import dynamic_feedback
from backend.teaching.progression import normalize as normalize_dialogue
from backend.teaching.progression import current_point
from backend.teaching.postclass_state import pending_points
from backend.teaching.postclass_state import pending_kind
from backend.teaching.postclass_state import prepare_points
from backend.teaching import typed_state


class InvalidRecord(ValueError):
    code = "INVALID_LEARNING_RECORD"


def message_identity(session, command_id, role="student", offset=0):
    return identity("message", session["id"], session.get("contentGeneration", 0), "command", command_id, role, offset)


def _copy(session):
    return deepcopy({key: value for key, value in session.items() if key not in {"lock", "launchToken", "_cancelPending"}})


def _episode(session, kind):
    return identity("episode", session["id"], session.get("contentGeneration", 0), kind)


def _focus(session):
    dialogue = session.get("dialogue")
    if not dialogue:
        return None
    dialogue = normalize_dialogue(dialogue)
    if session.get("phase") == "discussion":
        point = current_point(dialogue)
        return ("classroom", dialogue["stage"], point) if point else None
    if session.get("phase") == "done" and session.get("postclassStage") == "remediation":
        if typed_state.active(dialogue):
            point = typed_state.current(dialogue, after_class=True)
            return ("after_class", "postclass_concept", point) if point else None
        points = pending_points(prepare_points(dialogue, session.get("messages", [])))
        if points:
            return "after_class", "postclass_" + pending_kind(points[0]), points[0]
    return None


def _task(session, focus):
    episode, kind, point = focus
    task_id = identity("task", session["id"], session.get("contentGeneration", 0), episode, kind, point["id"])
    return task_id


def _ensure_task(session, focus):
    task_id = _task(session, focus)
    records = session["learningRecords"]
    if task_id not in {task["taskId"] for task in records["tasks"]}:
        episode, kind, point = focus
        topic = next((t for t in (session.get("lessonContent") or {}).get("topics", [])
                      if t["topicId"] == point["id"]), {})
        records["tasks"].append({"taskId": task_id, "episodeId": _episode(session, episode), "type": kind,
            "topicId": point["id"], "contentId": (session.get("contentRef") or {}).get("contentId"),
            "purpose": {"recall": "复述本课概念", "reinforce": "加强复述与确认", "discuss": "应用本课知识",
                        "postclass_concept": "补完概念复述", "postclass_confirmation": "完成加强确认",
                        "postclass_discussion": "补完应用讨论"}.get(kind, "学习交流"),
            "sourceRefs": deepcopy(topic.get("sourceRefs", [])), "questionMessageId": None,
            "question": None, "promptMessageIds": [], "criteriaStatus": "legacy_policy_no_fixed_rubric",
            "status": "active", "resumesTaskId": next((t["taskId"] for t in records["tasks"]
                if kind == "postclass_discussion" and t["type"] == "discuss" and t["topicId"] == point["id"]), None)})
        if typed_state.active(session.get("dialogue")):
            created = records["tasks"][-1]
            created.update(purpose="继续巩固当前知识点" if episode == "after_class" else "学习当前知识点",
                           criteriaStatus="typed_point_details")
            question = point.get("task_question", "")
            original = next((t for t in records["tasks"][:-1]
                             if t["topicId"] == point["id"] and t.get("questionMessageId")), None)
            message = next((m for m in reversed(session.get("messages", []))
                            if m["role"] == "assistant" and question and question in m["text"]), None)
            if original:
                created.update(question=original["question"], questionMessageId=original["questionMessageId"],
                               resumesTaskId=original["taskId"])
            elif message:
                created.update(question=question, questionMessageId=message["messageId"])
    if typed_state.active(session.get("dialogue")):
        next(task for task in records["tasks"] if task["taskId"] == task_id)["status"] = "active"
    return task_id


def normalize(session):
    result = lesson_content.bind(_copy(session))
    existing = result.get("learningRecords")
    fresh = not existing
    result["learningRecords"] = records = deepcopy(existing) if existing else {
        "schemaVersion": 1, "tasks": [], "observations": [], "assistance": [], "episodes": []}
    scope = {"sessionId": result["id"], "contentGeneration": result.get("contentGeneration", 0),
             "contentId": (result.get("contentRef") or {}).get("contentId")}
    previous_scope = records.get("scope")
    if previous_scope and previous_scope != scope and any(records[group] for group in ("tasks", "observations", "assistance")):
        raise InvalidRecord("Learning records belong to a different session or content")
    records["scope"] = scope
    for seq, message in enumerate(result.get("messages", []), 1):
        episode = "after_class" if str(message.get("phase", "")).startswith("postclass-") else "classroom"
        message.setdefault("messageId", identity("message", result["id"], result.get("contentGeneration", 0), "legacy", seq))
        message.setdefault("episodeId", _episode(result, episode))
        message.setdefault("taskId", None)
        message.setdefault("createdAt", None)
        message.setdefault("recordOrigin", "legacy_unknown")
    if is_dynamic_flow(result):
        records.setdefault("decisions", [])
        task = (result.get("teachingState") or {}).get("task")
        if task and not _by_task(records, task["taskId"]):
            records["tasks"].append(deepcopy(task))
        if task:
            _by_task(records, task["taskId"])["status"] = "active"
        result["currentTaskId"] = task["taskId"] if task else None
    else:
        focus = _focus(result)
        result["currentTaskId"] = _ensure_task(result, focus) if focus else None
    episode_kinds = {"classroom"} if result.get("dialogue") else set()
    episode_kinds.update("after_class" if str(m.get("phase", "")).startswith("postclass-") else "classroom"
                         for m in result.get("messages", []))
    if result.get("postclassStage") or any(str(m.get("phase", "")).startswith("postclass-") for m in result.get("messages", [])):
        episode_kinds.add("after_class")
    if is_dynamic_flow(result) and result.get("teachingState"):
        episode_kinds.add(result["teachingState"]["episodeKind"])
    for kind in sorted(episode_kinds):
        eid = _episode(result, kind)
        if eid not in {e["episodeId"] for e in records["episodes"]}:
            records["episodes"].append({"episodeId": eid, "kind": kind})
    if fresh:
        # A historical verdict exists; its message/task/help associations may not.
        for point in (result.get("dialogue") or {}).get("points", []):
            for index, assessment in enumerate(point.get("assessment_history") or []):
                records["observations"].append({
                    "observationId": identity("observation", result["id"], result.get("contentGeneration", 0),
                                               "legacy", point["id"], index),
                    "topicId": point["id"], "taskId": None, "episodeId": None,
                    "contentId": (result.get("contentRef") or {}).get("contentId"),
                    "studentMessageIds": [], "studentExcerpt": assessment.get("studentText"),
                    "assessmentResult": assessment.get("result", "unknown"),
                    "modelRationale": assessment.get("evidence", ""), "sourceRefs": [],
                    "assistanceRefs": [], "independence": "unknown", "recordOrigin": "legacy_unknown",
                    "limitations": ["message_link_unknown", "assistance_unknown", "criteria_not_predefined"],
                    "recordedAt": None})
    return result


def input_task(session, kind, command_id):
    session = normalize(session)
    if kind == "postclass_answer" and session.get("postclassStage") == "open":
        return identity("task", session["id"], session.get("contentGeneration", 0), "open_question", command_id)
    return session.get("currentTaskId")


def _by_task(records, task_id):
    return next((t for t in records["tasks"] if t["taskId"] == task_id), None)


def transition(before, candidate, *, command_id=None):
    before = normalize(before)
    raw = _copy(candidate)
    if before.get("phase") in {"video", "discussion", "done"} and (
            before.get("flowVersion", LEGACY_FLOW) != raw.get("flowVersion", LEGACY_FLOW)
            or before.get("teachingPolicy") != raw.get("teachingPolicy")):
        raise InvalidRecord("Lesson flow and teaching policy are pinned until a new session starts")
    generation_changed = raw.get("contentGeneration", 0) != before.get("contentGeneration", 0)
    if generation_changed:
        raw.pop("learningRecords", None)
        raw.pop("recordsStored", None)
        if (raw.get("contentRef") or {}).get("sourceRevision") != str(raw.get("videoRevision") or "legacy-unversioned"):
            raw.pop("contentRef", None)
            raw.pop("lessonContent", None)
        old_messages = []
    else:
        old_messages = before.get("messages", [])
        raw.setdefault("learningRecords", deepcopy(before["learningRecords"]))
        raw.setdefault("contentRef", before.get("contentRef"))
        raw.setdefault("lessonContent", before.get("lessonContent"))
        for old, new in zip(old_messages, raw.get("messages", [])):
            if any(old.get(k) != new.get(k) for k in ("role", "text", "phase")):
                raise InvalidRecord("Committed messages cannot be rewritten")
            if new.get("messageId") and new["messageId"] != old["messageId"]:
                raise InvalidRecord("Committed message identity changed")
            new.update({key: old[key] for key in ("messageId", "episodeId", "taskId", "createdAt", "recordOrigin")})
        if len(raw.get("messages", [])) < len(old_messages):
            raise InvalidRecord("Committed messages cannot be removed")
    timestamp = datetime.now(timezone.utc).isoformat()
    for offset, message in enumerate(raw.get("messages", [])[len(old_messages):]):
        seq = len(old_messages) + offset + 1
        message.setdefault("messageId", message_identity(raw, command_id, message["role"], offset) if command_id else
                           identity("message", raw["id"], raw.get("contentGeneration", 0), "legacy", seq))
        message.setdefault("createdAt", timestamp)
        message["recordOrigin"] = "recorded"
    # Prevent new assessments from being mislabeled as imported historical observations.
    raw.setdefault("learningRecords", {"schemaVersion": 1, "tasks": [], "observations": [], "assistance": [], "episodes": []})
    after = normalize(raw)
    records = after["learningRecords"]
    old_task_id = None if generation_changed else before.get("currentTaskId")
    next_task_id = after.get("currentTaskId")
    new_messages = after.get("messages", [])[len(old_messages):]
    student = next((m for m in new_messages if m["role"] == "student"), None)
    dynamic = is_dynamic_flow(after)
    turn = after.get("dynamicTurn") or {}
    if student and before.get("postclassStage") == "open" and after.get("phase") == "done" and not dynamic:
        old_task_id = identity("task", after["id"], after.get("contentGeneration", 0), "open_question",
                               command_id or student["messageId"])
        if not _by_task(records, old_task_id):
            records["tasks"].append({"taskId": old_task_id, "episodeId": _episode(after, "after_class"),
                "type": "open_question", "topicId": None, "contentId": (after.get("contentRef") or {}).get("contentId"),
                "purpose": "课后自由答疑", "sourceRefs": [], "questionMessageId": student["messageId"],
                "question": student["text"], "promptMessageIds": [], "criteriaStatus": "not_an_assessment",
                "status": "completed"})
    old_task = _by_task(records, old_task_id)
    if student:
        student["taskId"] = old_task_id
        student["episodeId"] = old_task["episodeId"] if old_task else student["episodeId"]
        oid = identity("observation", student["messageId"])
        prior_help = [a["assistanceId"] for a in before["learningRecords"]["assistance"]
                      if a["taskId"] == old_task_id and a.get("guidedPolicy") is True]
        topic_id = (old_task or {}).get("topicId")
        old_point = next((p for p in (before.get("dialogue") or {}).get("points", []) if p["id"] == topic_id), {})
        new_point = next((p for p in (after.get("dialogue") or {}).get("points", []) if p["id"] == topic_id), {})
        index = len(old_point.get("assessment_history") or [])
        assessments = new_point.get("assessment_history") or []
        assessment = assessments[index] if len(assessments) > index else {}
        observation = {"observationId": oid, "topicId": topic_id, "taskId": old_task_id,
            "episodeId": student["episodeId"], "contentId": (after.get("contentRef") or {}).get("contentId"),
            "studentMessageIds": [student["messageId"]], "studentExcerpt": student["text"],
            "assessmentResult": assessment.get("result", "unknown"), "modelRationale": assessment.get("evidence", ""),
            "sourceRefs": deepcopy((old_task or {}).get("sourceRefs", [])), "assistanceRefs": prior_help,
            "independence": "assisted" if prior_help else "unknown", "recordOrigin": "recorded",
            "limitations": ["legacy_policy_not_independent_verification"] + ([] if assessment else ["no_assessment"])
                            + ([] if (old_task or {}).get("sourceRefs") else ["source_reference_unknown"]),
            "recordedAt": student["createdAt"]}
        if dynamic:
            proposed = (turn.get("decision") or {}).get("observation", {})
            independent = (old_task or {}).get("type") == "independent_attempt" and turn.get("intent") not in {"ask_question", "request_help"}
            observation.update(supportedUnderstanding=proposed.get("supportedUnderstanding", ""),
                uncertainties=proposed.get("uncertainties", ""), modelRationale="",
                attemptMode="independent_attempt" if independent else "dialogue",
                independence="assisted" if prior_help else "no_recorded_help_in_task" if independent else "unknown",
                limitations=["semantic_judgement_unverified", "help_outside_this_task_unknown"]
                    + (["request_not_an_assessment"] if turn.get("intent") in {"ask_question", "request_help"} else []))
        elif typed_state.active(after.get("dialogue")):
            observation["limitations"] = ["semantic_judgement_unverified", "help_effect_unknown"] + ([] if assessment else ["no_assessment"])
        if oid not in {o["observationId"] for o in records["observations"]}:
            records["observations"].append(observation)
    for message in new_messages:
        if message["role"] != "assistant":
            continue
        task_id = next_task_id or old_task_id
        task = _by_task(records, task_id)
        message["taskId"] = task_id
        message["relatedTaskIds"] = list(dict.fromkeys(t for t in (old_task_id, next_task_id) if t))
        if task:
            message["episodeId"] = task["episodeId"]
            if next_task_id:
                if message["messageId"] not in task["promptMessageIds"]:
                    task["promptMessageIds"].append(message["messageId"])
                if task["questionMessageId"] is None and task_id not in {t["taskId"] for t in before["learningRecords"]["tasks"]}:
                    task["questionMessageId"] = message["messageId"]
                    if not dynamic:
                        task["question"] = message["text"]
            strategy = (after.get("dialogue") or {}).get("strategy")
            if typed_state.active(after.get("dialogue")):
                strategy = (after.get("dialogue") or {}).get("last_assistance", "none")
            same_task = old_task_id == next_task_id
            kind = strategy if same_task and strategy in {"hint", "correct", "answer_question", "example", "explanation", "correction"} else "tutor_response"
            typed = typed_state.active(after.get("dialogue"))
            if typed:
                kind = strategy
            if str(message.get("phase", "")).startswith("postclass-") and not typed:
                kind = "remediation_response" if same_task else "tutor_response"
            if task["type"] == "open_question":
                kind = "free_answer"
            if dynamic:
                kind = turn.get("assistanceKind", "none")
            aid = identity("assistance", message["messageId"])
            if aid not in {a["assistanceId"] for a in records["assistance"]}:
                records["assistance"].append({"assistanceId": aid, "taskId": task_id,
                    "episodeId": task["episodeId"], "assistantMessageId": message["messageId"],
                    "kind": kind, "guidedPolicy": (kind != "none") if dynamic or typed else True if kind != "tutor_response" else None, "substantive": None,
                    "providedAt": message["createdAt"], "deliveryStatus": "committed",
                    "classificationBasis": "model_reported_help" if typed else "executed_teaching_policy"})
    if old_task and old_task_id != next_task_id and old_task["type"] != "open_question":
        point = next((p for p in (after.get("dialogue") or {}).get("points", [])
                      if p["id"] == old_task.get("topicId")), {})
        mastered = point.get("discussion_result") == "mastered" if "discuss" in old_task["type"] else point.get("status") == "mastered"
        old_task["status"] = "completed" if mastered else "ended" if after.get("phase") == "done" else "deferred"
        if dynamic:
            old_task["status"] = "ended" if (after.get("teachingState") or {}).get("stage") in {"summary", "completed"} else "deferred"
    if dynamic and turn.get("decision") and new_messages:
        decision = deepcopy(turn["decision"])
        decision["studentMessageIds"] = [student["messageId"]] if student else []
        if decision["decisionId"] not in {d["decisionId"] for d in records["decisions"]}:
            records["decisions"].append(decision)
    validate(after, before if not generation_changed else None)
    if dynamic and after.get("phase") == "done" and after.get("postclassStage") and student:
        after["feedback"] = dynamic_feedback(after)
    if after.get("feedback"):
        after["feedback"] = feedback_links(after["feedback"], after)
    return after


def validate(session, before=None):
    records = session["learningRecords"]
    messages = {m["messageId"]: m for m in session.get("messages", [])}
    if len(messages) != len(session.get("messages", [])):
        raise InvalidRecord("Duplicate message identity")
    tasks = {t["taskId"]: t for t in records["tasks"]}
    episodes = {e["episodeId"] for e in records["episodes"]}
    topic_map = {t["topicId"]: t for t in (session.get("lessonContent") or {}).get("topics", [])}
    content_id = (session.get("contentRef") or {}).get("contentId")
    if len(tasks) != len(records["tasks"]):
        raise InvalidRecord("Duplicate task identity")
    for message in messages.values():
        if message["episodeId"] not in episodes or (message["taskId"] and message["taskId"] not in tasks):
            raise InvalidRecord("Message task or episode is invalid")
    for task in tasks.values():
        if task["episodeId"] not in episodes or task["contentId"] != content_id:
            raise InvalidRecord("Task scope is invalid")
        if topic_map and task.get("topicId") and task["topicId"] not in topic_map:
            raise InvalidRecord("Task topic is outside pinned content")
        if task["questionMessageId"] and task["questionMessageId"] not in messages:
            raise InvalidRecord("Task question has no message")
        if task["questionMessageId"] and (task["question"] not in messages[task["questionMessageId"]]["text"]
                if is_dynamic_flow(session) or typed_state.active(session.get("dialogue")) else messages[task["questionMessageId"]]["text"] != task["question"]):
            raise InvalidRecord("Task question changed")
        if task.get("resumesTaskId"):
            original = tasks.get(task["resumesTaskId"])
            if not original or original["topicId"] != task["topicId"] or original["contentId"] != task["contentId"]:
                raise InvalidRecord("Resumed task belongs to a different topic or content")
        for ref in task["sourceRefs"]:
            if ref not in topic_map.get(task.get("topicId"), {}).get("sourceRefs", []):
                raise InvalidRecord("Task source is outside pinned content")
    assistance = {a["assistanceId"]: a for a in records["assistance"]}
    if len(assistance) != len(records["assistance"]):
        raise InvalidRecord("Duplicate help identity")
    for item in assistance.values():
        message = messages.get(item["assistantMessageId"])
        if not message or message["role"] != "assistant" or message["taskId"] != item["taskId"]:
            raise InvalidRecord("Assistance must reference a committed tutor message")
        if item["episodeId"] != message["episodeId"]:
            raise InvalidRecord("Assistance episode is invalid")
    sequence = {m["messageId"]: i for i, m in enumerate(session.get("messages", []))}
    seen = set()
    for item in records["observations"]:
        if item["observationId"] in seen or item["contentId"] != content_id:
            raise InvalidRecord("Observation identity or content is invalid")
        seen.add(item["observationId"])
        if item["recordOrigin"] == "legacy_unknown":
            if item["studentMessageIds"] or item["independence"] != "unknown":
                raise InvalidRecord("Historical associations cannot be invented")
            continue
        if item["taskId"] not in tasks or len(item["studentMessageIds"]) != 1:
            raise InvalidRecord("Observation task is invalid")
        message = messages.get(item["studentMessageIds"][0])
        if not message or message["role"] != "student" or item["studentExcerpt"] != message["text"]:
            raise InvalidRecord("Observation must quote the student's actual message")
        if message["taskId"] != item["taskId"]:
            raise InvalidRecord("Observation and message tasks differ")
        if message["episodeId"] != item["episodeId"] or item["episodeId"] != tasks[item["taskId"]]["episodeId"]:
            raise InvalidRecord("Observation episode is invalid")
        for ref in item["sourceRefs"]:
            if ref not in tasks[item["taskId"]]["sourceRefs"]:
                raise InvalidRecord("Observation source is invalid")
        for aid in item["assistanceRefs"]:
            help_item = assistance.get(aid)
            if (not help_item or help_item["taskId"] != item["taskId"]
                    or sequence[help_item["assistantMessageId"]] >= sequence[message["messageId"]]):
                raise InvalidRecord("Future or unrelated help cannot explain an earlier answer")
        if item["independence"] not in ({"unknown", "assisted", "no_recorded_help_in_task"}
                                       if is_dynamic_flow(session) else {"unknown", "assisted"}):
            raise InvalidRecord("This flow does not verify independent performance")
        if item["independence"] == "no_recorded_help_in_task" and (
                tasks[item["taskId"]]["type"] != "independent_attempt" or item["assistanceRefs"]
                or item.get("attemptMode") != "independent_attempt"):
            raise InvalidRecord("No-help records require a separately bound independent task")
    decision_ids = set()
    for decision in records.get("decisions", []):
        if decision["decisionId"] in decision_ids or decision["contentId"] != content_id:
            raise InvalidRecord("Decision identity or content is invalid")
        decision_ids.add(decision["decisionId"])
        if decision.get("taskId") and decision["taskId"] not in tasks:
            raise InvalidRecord("Decision task is invalid")
        if any(mid not in messages or messages[mid]["role"] != "student"
               or messages[mid]["taskId"] != decision.get("taskId") for mid in decision["studentMessageIds"]):
            raise InvalidRecord("Decision input is not the bound student submission")
        if any(oid not in seen for oid in decision["reasonEvidenceIds"]):
            raise InvalidRecord("Decision evidence does not exist")
    if before:
        prior = before.get("learningRecords") or {}
        for group, key in (("observations", "observationId"), ("assistance", "assistanceId"), ("decisions", "decisionId")):
            current = {item[key]: item for item in records.get(group, [])}
            for old in prior.get(group, []):
                if current.get(old[key]) != old:
                    raise InvalidRecord("Committed evidence and help are immutable")
        for old in prior.get("tasks", []):
            current = tasks.get(old["taskId"])
            if not current:
                raise InvalidRecord("Existing tasks cannot be removed")
            for key in ("type", "episodeId", "topicId", "contentId", "purpose", "sourceRefs", "criteriaStatus"):
                if current[key] != old[key]:
                    raise InvalidRecord("Task definition cannot change after an answer")
            if current.get("criteria") != old.get("criteria"):
                raise InvalidRecord("Predefined task criteria cannot change")
            if old["questionMessageId"] and any(current[key] != old[key] for key in ("questionMessageId", "question")):
                raise InvalidRecord("Original task question cannot change")
            if current.get("resumesTaskId") != old.get("resumesTaskId"):
                raise InvalidRecord("Task resumption link cannot change")


def feedback_links(feedback, session):
    result = deepcopy(feedback)
    records = session.get("learningRecords") or {}
    result["recordSchemaVersion"] = 1
    for point in result.get("points", []):
        observations = [o for o in records.get("observations", []) if o.get("topicId") == point["id"]]
        point["observationIds"] = [o["observationId"] for o in observations]
        point["evidenceLimitations"] = sorted({lim for o in observations for lim in o["limitations"]})
    result["evidenceSummary"] = {"observations": len(records.get("observations", [])),
        "assisted": sum(o["independence"] == "assisted" for o in records.get("observations", [])),
        "independenceUnknown": sum(o["independence"] == "unknown" for o in records.get("observations", []))}
    if is_dynamic_flow(session):
        result["evidenceSummary"]["noRecordedHelpInTask"] = sum(
            o["independence"] == "no_recorded_help_in_task" for o in records.get("observations", []))
    return result


def public_view(session):
    current = _by_task(session["learningRecords"], session.get("currentTaskId"))
    task = ({key: current[key] for key in ("taskId", "episodeId", "type", "topicId", "questionMessageId",
                                          "question", "purpose", "status")} if current else None)
    return {"currentTaskPublic": task, "contentRef": session.get("contentRef"),
            "recordSchemaVersion": 1}
