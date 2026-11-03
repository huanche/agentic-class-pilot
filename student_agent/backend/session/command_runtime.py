"""Durable execution of existing teaching actions, outside database transactions."""
from __future__ import annotations

import logging
import secrets
from threading import Event, Lock, Thread

from backend.infrastructure import commands
from backend.infrastructure import persistence
from backend.infrastructure import published_knowledge
from backend.content.knowledge import CURRICULUM_VERSION
from backend.infrastructure.persistence import RecordConflict
from backend.infrastructure import platform_access
from backend.teaching import service as teaching
from backend.contracts import SessionError

logger = logging.getLogger(__name__)
_stop = Event()
_worker_thread = None
_worker_lock = Lock()


def conflict(error: RecordConflict) -> SessionError:
    status = {"ACCESS_DENIED": 403, "SESSION_RESET": 410, "HISTORY_NOT_FOUND": 404,
              "COMMANDS_DRAINING": 503}.get(error.code, 409)
    return SessionError(status, str(error), code=error.code)


def authorize(sid, launch_token):
    if not launch_token:
        raise SessionError(401, "请从平台重新进入课程", code="ACCESS_EXPIRED")
    record = commands.scope(sid)
    context = platform_access.authorize_student(launch_token)
    commands.check_access(record, context)
    return context


def validate(base, kind, payload):
    if teaching.is_dynamic(base):
        return teaching.validate_dynamic_command(base, kind, payload)
    phase = base.get("phase")
    if kind == "start_discussion":
        valid = phase == "discussion" or (phase == "video" and base.get("dialogue")
                                          and base.get("preparation") in {"ready", "partial"})
    elif kind == "submit_answer":
        valid = phase == "discussion" and teaching.describe(base.get("dialogue"))["agentStage"] != "wrapup"
    elif kind in {"finish", "continue_after_class"}:
        valid = phase in ({"discussion", "done"} if kind == "finish" else {"done"})
    elif kind == "postclass_answer":
        valid = phase == "done" and base.get("postclassStage") in {"remediation", "open"}
    elif kind == "reset_lesson":
        valid = phase == "done"
    else:
        valid = False
    if not valid:
        raise SessionError(409, "当前阶段不允许此操作，请刷新学习状态", code="INVALID_ACTION")
    if kind in {"submit_answer", "postclass_answer"}:
        text = payload.get("text")
        if not isinstance(text, str) or not 1 <= len(text) <= 2000:
            raise SessionError(422, "回答长度必须在 1–2000 字符之间", code="INVALID_PAYLOAD")
        if set(payload) - {"text", "taskId"}:
            raise SessionError(422, "回答参数无效", code="INVALID_PAYLOAD")
        if payload.get("taskId") is not None and payload["taskId"] != base.get("currentTaskId"):
            raise SessionError(409, "当前学习任务已变化，请刷新后重试", code="TASK_CHANGED")
    elif payload:
        raise SessionError(422, "操作不接受额外参数", code="INVALID_PAYLOAD")


def _changes(base, kind, payload):
    if teaching.is_dynamic(base):
        extra = teaching.dynamic_command(base, kind, payload)
        if extra is not None:
            return extra
    prepared = {}
    if not base.get("contentRef") and kind in {"start_discussion", "submit_answer"} and (
            (base.get("dialogue") or {}).get("curriculum_version") != CURRICULUM_VERSION):
        context = base["context"]
        result = published_knowledge.read(str(context["courseId"]), str(base["lessonId"]), base["videoRevision"])
        if not result or result["status"] != "ready":
            raise SessionError(409, "本课知识点正在整理，请稍后重试", code="CONTENT_NOT_READY")
        prepared = {"dialogue": teaching.new_dialogue(result["points"]), "preparation": "ready",
                    "preparationCoverage": result["coverage"]}
        base = dict(base, **prepared)
    if kind == "start_discussion":
        changed = teaching.start_discussion(base)
    elif kind == "submit_answer":
        changed = teaching.classroom_turn(base, payload["text"])
    elif kind == "postclass_answer":
        changed = teaching.postclass_turn(base, payload["text"])
    elif kind == "finish":
        changed = teaching.finish(base)
    elif kind == "continue_after_class":
        changed = teaching.start_postclass(base)
    else:
        raise SessionError(409, "无效的教学命令", code="INVALID_ACTION")
    return dict(prepared, **changed)


def process(sid, command_id):
    claimed = commands.claim(sid, command_id)
    if not claimed:
        return
    token = claimed["token"]
    stop = Event()
    def heartbeat():
        while not stop.wait(30):
            try:
                if not commands.renew(sid, command_id, token):
                    return
            except Exception:
                logger.exception("Command lease renewal failed: %s", command_id)
                return
    thread = Thread(target=heartbeat, name="student-command-lease", daemon=True)
    thread.start()
    try:
        if claimed["type"] == "reset_lesson":
            base = claimed["base"]
            fresh = {"id": secrets.token_urlsafe(24), "context": base["context"], "courses": base["courses"],
                     "phase": "idle", "lessonId": None, "messages": [], "dialogue": None}
            commands.complete_reset(sid, command_id, token, fresh)
        else:
            changed = _changes(claimed["base"], claimed["type"], claimed["payload"])
            commands.complete(sid, command_id, token, changed)
    except Exception as error:
        code = getattr(error, "code", None) or ("MODEL_UNAVAILABLE" if isinstance(error, SessionError)
                                               else "STORAGE_UNAVAILABLE")
        failure = {"code": code, "detail": str(error) if isinstance(error, (SessionError, RecordConflict))
                   else "保存学习记录失败，请稍后重试", "retryable": code not in {
                       "VERSION_CONFLICT", "INVALID_ACTION", "INVALID_PAYLOAD", "COMMAND_CANCELLED"}}
        logger.exception("Student command failed: %s", command_id)
        # A lost commit acknowledgement must never turn a completed command into a failed one.
        try:
            commands.fail(sid, command_id, token, failure)
        except Exception:
            logger.exception("Command failure receipt unavailable; lease recovery will retry")
    finally:
        stop.set()
        thread.join(timeout=1)


def result(sid, command_id, launch_token=""):
    from backend.session import service as learning_session
    receipt = commands.read(sid, command_id)
    if not receipt:
        raise SessionError(404, "找不到此命令", code="COMMAND_NOT_FOUND")
    snapshot = receipt["result"] if receipt["status"] == "completed" else persistence.restore(sid)
    if not snapshot:
        raise SessionError(410, "本课学习记录已重置", code="SESSION_RESET")
    # Cache publication is secondary to the database commit and cannot roll a newer view back.
    if receipt["status"] == "completed":
        current = persistence.restore(snapshot["id"])
        if current:
            snapshot = current
            with learning_session.session_lock:
                cached = learning_session.sessions.get(current["id"])
                if cached is None or cached.get("stateVersion", 0) <= current["stateVersion"]:
                    current["launchToken"] = launch_token or (cached or {}).get("launchToken")
                    learning_session.sessions[current["id"]] = current
    return {"commandId": command_id, "status": receipt["status"],
            "appliedStateVersion": (receipt["result"] or {}).get("stateVersion"),
            "sessionView": learning_session.state(snapshot), "failure": receipt["failure"]}


def execute(sid, command, launch_token):
    try:
        context = authorize(sid, launch_token)
        receipt = commands.accept(sid, command, context, validate)
        if receipt["status"] in {"pending", "processing"}:
            process(sid, command["commandId"])
        return result(sid, command["commandId"], launch_token)
    except RecordConflict as error:
        raise conflict(error) from error
    except SessionError:
        raise
    except Exception as error:
        logger.exception("Command persistence unavailable")
        raise SessionError(503, "学习记录暂不可用，请稍后重试", code="STORAGE_UNAVAILABLE") from error


def status(sid, command_id, launch_token):
    try:
        authorize(sid, launch_token)
        return result(sid, command_id, launch_token)
    except RecordConflict as error:
        raise conflict(error) from error
    except SessionError:
        raise
    except Exception as error:
        raise SessionError(503, "学习记录暂不可用，请稍后重试", code="STORAGE_UNAVAILABLE") from error


def read_records(sid, launch_token):
    try:
        authorize(sid, launch_token)
        session = persistence.restore(sid)
        if not session:
            raise SessionError(410, "本课学习记录已重置", code="SESSION_RESET")
        from backend.evidence import records as learning_records
        return {"sessionId": sid, "stateVersion": session["stateVersion"], "contentRef": session.get("contentRef"),
                **session["learningRecords"], "currentTaskPublic": learning_records.public_view(session)["currentTaskPublic"],
                "contentLimitations": (session.get("lessonContent") or {}).get("coverageGaps", [])}
    except RecordConflict as error:
        raise conflict(error) from error

    except SessionError:
        raise
    except Exception as error:
        raise SessionError(503, "学习记录暂不可用，请稍后重试", code="STORAGE_UNAVAILABLE") from error


def sync_once():
    try:
        claimed = commands.claim_sync()
        if not claimed:
            return False
        row, token = claimed
        event_id, sid, user, course, classroom, event = row
        session = {"id": sid, "context": {"userId": user, "courseId": course}, "classroomId": classroom}
        success = False
        try:
            success = bool(platform_access.report_learning_progress(session, event))
        finally:
            commands.finish_sync(event_id, token, success)
        return True
    except Exception:
        logger.exception("Progress sync deferred; durable intent retained")
        return False


def _worker():
    while not _stop.is_set():
        try:
            pending = commands.next_pending()
            if pending:
                process(*pending)
            sync_once()
        except Exception:
            logger.exception("Student command recovery worker failed")
        _stop.wait(2)


def start_worker():
    global _worker_thread
    with _worker_lock:
        if _worker_thread and _worker_thread.is_alive():
            return
        _stop.clear()
        _worker_thread = Thread(target=_worker, name="student-commands", daemon=True)
        _worker_thread.start()


def stop_worker():
    _stop.set()
    if _worker_thread:
        _worker_thread.join(timeout=2)
