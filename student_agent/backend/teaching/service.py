"""Existing classroom and postclass teaching behind a session-facing interface.

Returns candidate changes; only learning_session persists and publishes them.
Graph state, normalization and message-stage bookkeeping stay private here.
"""
from __future__ import annotations

import logging

from backend.teaching.graph import dialogue_graph
from backend.teaching.graph import initial_state
from backend.teaching.graph import opening
from backend.content.knowledge import CURRICULUM_VERSION
from backend.content.knowledge import learning_points
from backend.teaching.progression import normalize
from backend.teaching.progression import progress
from backend.evidence.feedback import lesson_feedback
from backend.teaching.postclass import pending_points
from backend.teaching.postclass import postclass_graph
from backend.teaching.postclass import postclass_stage
from backend.teaching.postclass import prepare_points
from backend.teaching.postclass import opening_task
from backend.contracts import SessionError
from backend.teaching import dynamic_teaching

logger = logging.getLogger(__name__)


def _model_messages(messages):
    # Traceability metadata must not change the established model input contract.
    return [{key: message[key] for key in ("role", "text", "phase") if key in message} for message in messages]


def new_dialogue(points: list[dict]) -> dict:
    return dict(initial_state(points), curriculum_version=CURRICULUM_VERSION)


def describe(dialogue: dict | None) -> dict:
    normalized = normalize(dialogue) if dialogue else None
    return {"agentStage": (normalized or {}).get("stage"),
            "learningProgress": progress(normalized) if normalized else None}


def opening_text(dialogue: dict) -> str:
    return opening(dialogue["points"])


def prepare(materials: list[dict], course_id: str | None = None, lesson_id: str | None = None) -> tuple[dict, dict]:
    result = learning_points(materials, course_id, lesson_id)
    coverage = {"partial": result.partial, "acceptedCount": len(result.points),
                "rejectedCount": result.rejected_count,
                "candidateCount": result.candidate_count,
                "repairAttempted": result.repair_attempted, "modelCalls": result.model_calls,
                "duplicateCount": result.duplicate_count}
    return dict(initial_state(result.points), curriculum_version=CURRICULUM_VERSION), coverage


def current_feedback(session: dict) -> dict | None:
    saved = session.get("feedback")
    if saved and saved.get("schemaVersion", 1) < 3 and session.get("dialogue"):
        return lesson_feedback(session)
    return saved


def _legacy_classroom_turn(session: dict, text: str) -> dict:
    if session["phase"] != "discussion":
        raise SessionError(409, "当前不在复述与讨论阶段")
    normalized = normalize(session["dialogue"])
    if normalized["stage"] == "wrapup":
        raise SessionError(409, "课堂对话已完成，请结束本课并查看反馈；结束后可继续课后对话")
    student = {"role": "student", "text": text.strip(),
               "phase": normalized["stage"]}
    dialogue = normalized
    dialogue["student_text"] = student["text"]
    dialogue["messages"] = _model_messages(session["messages"] + [student])
    try:
        dialogue = dialogue_graph.invoke(dialogue)
    except Exception as error:
        logger.exception("课堂导师对话失败：session=%s", session["id"])
        raise SessionError(503, "课堂导师暂不可用，请稍后重试") from error
    assistant = {"role": "assistant", "text": dialogue["reply"],
                 "phase": dialogue["stage"]}
    return {"dialogue": dialogue,
            "messages": session["messages"] + [student, assistant]}


def _legacy_finish(session: dict) -> dict:
    if session["phase"] == "done" and session.get("feedback"):
        return {}
    if session["phase"] not in {"discussion", "done"}:
        raise SessionError(409, "请先进入复述与讨论")
    dialogue = normalize(session["dialogue"])
    if dialogue["stage"] != "wrapup":
        dialogue["completion_reason"] = "student_ended_early"
        dialogue["ended_at_stage"] = dialogue["stage"]
    feedback = lesson_feedback(dict(session, dialogue=dialogue))
    return {"phase": "done", "dialogue": dialogue, "feedback": feedback}


def _legacy_start_postclass(session: dict) -> dict:
    if session["phase"] != "done" or not session.get("dialogue"):
        raise SessionError(409, "请先结束本节课")
    points = prepare_points(normalize(session["dialogue"]), _model_messages(session["messages"]))
    if not session.get("postclassStage") or (session.get("postclassStage") == "open" and pending_points(points)):
        stage = postclass_stage(points)
        if stage == "remediation":
            focus = pending_points(points)[0]
            opening_text = opening_task(focus)
        else:
            opening_text = "课堂知识点已经完成了。现在可以自由向我提问其他问题。"
        first = {"role": "assistant", "text": opening_text, "phase": "postclass-" + stage}
        return {"postclassStage": stage, "dialogue": dict(session["dialogue"], points=points),
                "classroomFeedback": session.get("classroomFeedback") or current_feedback(session),
                "messages": session["messages"] + [first]}
    return {}


def _legacy_postclass_turn(session: dict, text: str) -> dict:
    stage = session.get("postclassStage")
    if session["phase"] != "done" or stage not in {"remediation", "open"}:
        raise SessionError(409, "请先进入课后对话")
    student = {"role": "student", "text": text.strip(), "phase": "postclass-" + stage}
    history = [item for item in session["messages"]
               if str(item.get("phase") or "").startswith("postclass-")]
    try:
        result = postclass_graph.invoke({
            "points": prepare_points(normalize(session["dialogue"]), _model_messages(session["messages"])),
            "messages": _model_messages(history + [student]), "student_text": student["text"],
            "stage": stage, "assessment": {}, "transition": "continue", "reply": "",
        })
    except Exception as error:
        logger.exception("课后导师对话失败：session=%s", session["id"])
        raise SessionError(503, "课后导师暂不可用，请稍后重试") from error
    assistant = {"role": "assistant", "text": result["reply"],
                 "phase": "postclass-" + result["stage"]}
    dialogue = dict(session["dialogue"], points=result["points"])
    messages = session["messages"] + [student, assistant]
    draft = dict(session, dialogue=dialogue, messages=messages,
                 postclassStage=result["stage"])
    updated_feedback = lesson_feedback(draft)
    return {"dialogue": dialogue, "messages": messages,
            "postclassStage": result["stage"], "feedback": updated_feedback}


# Two actual implementations share this session-facing Seam. Keep legacy bodies and
# model inputs intact; flow selection happens once at lesson start, never per route.
def select_flow(context, lesson_id):
    return dynamic_teaching.select(context, lesson_id)


def is_dynamic(session):
    flow = session.get("flowVersion", dynamic_teaching.LEGACY)
    if flow not in {dynamic_teaching.LEGACY, dynamic_teaching.FLOW}:
        raise SessionError(409, "此学习流程版本暂不受支持", code="FLOW_UNAVAILABLE")
    return dynamic_teaching.active(session)


def _dynamic_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except dynamic_teaching.DynamicError as error:
        raise SessionError(409, str(error), code=error.code) from error
    except Exception as error:
        logger.exception("动态教学生成失败")
        raise SessionError(503, "导师暂不可用，原回答已保留，请重试", code="MODEL_UNAVAILABLE") from error


def describe_session(session):
    return _dynamic_call(dynamic_teaching.describe, session) if is_dynamic(session) else describe(session.get("dialogue"))


def start_discussion(session):
    if session["phase"] == "discussion":
        return {}
    if is_dynamic(session):
        return _dynamic_call(dynamic_teaching.start, session)
    return {"phase": "discussion", "messages": session["messages"] + [{"role": "assistant",
            "text": opening_text(session["dialogue"]), "phase": "recall"}]}


def classroom_turn(session, text):
    return (_dynamic_call(dynamic_teaching.turn, session, text) if is_dynamic(session)
            else _legacy_classroom_turn(session, text))


def finish(session):
    return (_dynamic_call(dynamic_teaching.finish, session) if is_dynamic(session)
            else _legacy_finish(session))


def start_postclass(session):
    return (_dynamic_call(dynamic_teaching.postclass, session) if is_dynamic(session)
            else _legacy_start_postclass(session))


def postclass_turn(session, text):
    return (_dynamic_call(dynamic_teaching.turn, session, text) if is_dynamic(session)
            else _legacy_postclass_turn(session, text))


def validate_dynamic_command(session, kind, payload):
    stage = _dynamic_call(dynamic_teaching.describe, session)
    active = session["phase"] == "discussion" or (session["phase"] == "done" and session.get("postclassStage"))
    if kind == "start_discussion":
        valid = session["phase"] == "discussion" or (session["phase"] == "video" and session.get("dialogue")
                 and session.get("preparation") in {"ready", "partial"})
    elif kind in {"submit_answer", "postclass_answer", "request_help", "ask_question"}:
        valid = bool(active and stage["activityStatus"] == "active" and stage["allowedActions"])
        if kind == "submit_answer":
            valid = valid and session["phase"] == "discussion"
        if kind == "postclass_answer":
            valid = valid and session["phase"] == "done"
    elif kind in {"pause", "resume_activity"}:
        valid = bool(active and stage["teachingStage"] not in {"summary", "completed"})
    elif kind in {"finish", "continue_after_class", "reset_lesson"}:
        valid = session["phase"] in ({"video", "discussion", "done"} if kind == "finish" else {"done"})
    else:
        valid = False
    if not valid:
        raise SessionError(409, "当前阶段不允许此操作", code="INVALID_ACTION")
    if kind in {"submit_answer", "postclass_answer", "ask_question", "request_help"}:
        if set(payload) - {"text", "taskId"} or not dynamic_teaching._text(payload.get("text")):
            raise SessionError(422, "请输入 1–2000 字符的学习请求", code="INVALID_PAYLOAD")
        if payload.get("taskId") != session.get("currentTaskId"):
            raise SessionError(409, "当前学习任务已变化", code="TASK_CHANGED")
    elif payload:
        raise SessionError(422, "操作不接受额外参数", code="INVALID_PAYLOAD")


def dynamic_command(session, kind, payload):
    if kind in {"request_help", "ask_question"}:
        return _dynamic_call(dynamic_teaching.turn, session, payload["text"], intent=kind)
    if kind in {"pause", "resume_activity"}:
        return _dynamic_call(dynamic_teaching.activity, session, kind)
    return None
