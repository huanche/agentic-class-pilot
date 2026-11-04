"""Learning-session use cases; owns session mutation and persistence coordination.

Public operations return the existing browser view. HTTP validation and transport
live in main; platform I/O and teaching details live behind their own seams.
P1 deliberately preserves existing locks, snapshots, writes and failure behavior.
"""
from __future__ import annotations

import json
import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
import traceback
from contextlib import ExitStack
from pathlib import Path
from threading import Lock
from typing import Callable, Protocol

from backend.content.context import classroom_materials
from backend.content.context import lesson_points
from backend.content.knowledge import CURRICULUM_VERSION
from backend.content.knowledge import KnowledgePreparationError
from backend.infrastructure import persistence
from backend.infrastructure import published_knowledge
from backend.content import lesson_content
from backend.evidence import records as learning_records
from backend.infrastructure import platform_access
from backend.infrastructure.platform_identity import current_identity, PlatformIdentity
from backend.teaching import service as teaching
from backend.contracts import SessionError


class BackgroundWork(Protocol):
    """Scheduling seam, satisfied by FastAPI BackgroundTasks or an offline collector."""

    def add_task(self, func: Callable[..., object], *args: object, **kwargs: object) -> None: ...


logger = logging.getLogger(__name__)
sessions: dict[str, dict] = {}
session_lock = Lock()
preparing: set[str] = set()


def _credential(session, supplied=None) -> PlatformIdentity | str | None:
    return current_identity.get() or supplied or session.get("launchToken")


def _browser_snapshot(session: dict) -> str:
    payload = {key: value for key, value in session.items()
               if key not in {"lock", "launchToken"}}
    if session.get("context"):
        payload = {"id": session["id"], "context": {key: session["context"][key]
                    for key in ("userId", "courseId", "publication")}, "courses": [], "messages": [],
                   "phase": session["phase"], "lessonId": session.get("lessonId"),
                   "stateVersion": session.get("stateVersion", 0)}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    secret = (os.environ.get("STUDENT_TOKEN_SIGNING_KEY")
              or os.environ["STUDENT_SERVICE_KEY"]).encode()
    signature = hmac.new(secret, b"browser-session:" + encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _restore_browser_snapshot(value: str) -> dict:
    encoded, separator, signature = value.partition(".")
    keys = (os.environ.get("STUDENT_TOKEN_SIGNING_KEY", ""),
            os.environ.get("STUDENT_SERVICE_KEY", ""))
    valid = any(key and hmac.compare_digest(
        signature,
        hmac.new(key.encode(), b"browser-session:" + encoded.encode(), hashlib.sha256).hexdigest(),
    ) for key in keys)
    if not separator or not valid:
        raise SessionError(400, "浏览器学习记录无效，请重新进入课程")
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        restored = json.loads(raw)
    except (ValueError, UnicodeError, TypeError) as error:
        raise SessionError(400, "浏览器学习记录无效，请重新进入课程") from error
    if (not isinstance(restored, dict) or not isinstance(restored.get("id"), str)
            or not isinstance(restored.get("courses"), list)
            or not isinstance(restored.get("messages"), list)
            or restored.get("phase") not in {"idle", "video", "discussion", "done", "replay", "postclass"}):
        raise SessionError(400, "浏览器学习记录不完整，请重新进入课程")
    restored["lock"] = Lock()
    return restored


def schedule_progress_sync(session: dict, event: str, tasks: BackgroundWork) -> None:
    if session.get("context") and session.get("classroomId"):
        if "stateVersion" in session:
            from backend.session.command_runtime import sync_once
            tasks.add_task(sync_once)
        else:
            tasks.add_task(platform_access.report_learning_progress, dict(session), event)


def catalog(context: dict) -> list[dict]:
    course_id = str(context.get("courseId") or "course")
    published = context.get("lessonCatalog") or context.get("lessons") or []
    selected = {str(item.get("id")): item for item in context.get("lessons") or []}
    lessons = []
    for index, item in enumerate(published, 1):
        details = selected.get(str(item.get("id")), item)
        classroom = details.get("classroom") or {}
        classroom_title = str(classroom.get("title") or "").strip()
        lesson_title = str(item.get("title") or f"第 {index} 课").strip()
        lessons.append({
            "id": str(item.get("id") or index), "title": lesson_title,
            "week": item.get("week") or index, "lessonNumber": item.get("lessonNumber") or 1,
            "summary": str(details.get("summary") or (classroom_title if classroom_title != lesson_title else "")),
            "teachingHours": item.get("teachingHours"), "publishedAt": details.get("publishedAt"),
            "playerUrl": classroom.get("playerUrl"), "classroomId": classroom.get("id"),
            "segmentCount": item.get("segmentCount") or len(classroom.get("scenes") or []),
        })
    return [{"id": course_id, "title": context.get("courseTitle") or "我的课程", "lessons": lessons}]


def video_revision(context: dict, lesson_id: str) -> str | None:
    lesson = next((item for item in context.get("lessons") or []
                   if str(item.get("id")) == lesson_id), None)
    if not lesson:
        return None
    classroom = lesson.get("classroom") or {}
    # Playback grants change on every request; only published video data counts.
    payload = [classroom.get("id"), lesson.get("publishedAt"), classroom.get("scenes")]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def refresh_lesson(session: dict, current: dict | None = None) -> bool:
    """Caller holds the session lock. Replace stale video progress atomically."""
    original = session.get("context")
    lesson_id = session.get("lessonId")
    if not original or not lesson_id:
        return False
    token = _credential(session)
    if not token:
        raise SessionError(401, "请从平台重新进入课程以检查最新教学视频")
    current = current or platform_access.platform_context(token, lesson_id, True)
    if any(str(current.get(key)) != str(original.get(key)) for key in ("userId", "courseId")):
        raise SessionError(403, "学习记录与当前用户或课程不匹配")
    if str(current.get("selectedLessonId")) != lesson_id or len(current.get("lessons") or []) != 1:
        raise SessionError(409, "当前课时尚未发布")
    courses = catalog(current)
    lesson = next(item for course in courses for item in course["lessons"] if item["id"] == lesson_id)
    if not lesson.get("playerUrl"):
        raise SessionError(409, "当前课时没有已发布的教学视频")
    revision = video_revision(current, lesson_id)
    previous = session.get("videoRevision") or video_revision(original, lesson_id)
    if previous:
        changed = previous != revision
    else:
        # Old database snapshots have only the catalog, not classroom scenes.
        old = next((item for course in session["courses"] for item in course["lessons"]
                    if item["id"] == lesson_id), {})
        changed = (old.get("classroomId"), old.get("publishedAt")) != (lesson.get("classroomId"), lesson.get("publishedAt"))
    if not changed:
        session.update(context=current, courses=courses, videoRevision=revision)
        return False
    replacement = {"id": session["id"], "context": current, "courses": courses,
                   "launchToken": token if isinstance(token, str) else None, "lessonId": lesson_id,
                   "classroomId": lesson["classroomId"], "phase": "video", "messages": [],
                   "dialogue": None, "preparation": "pending",
                   "preparationMaterials": lesson_points(current, lesson_id),
                   "videoRevision": revision, "videoUpdated": True,
                   "contentGeneration": session.get("contentGeneration", 0) + 1}
    replacement.update({key: session[key] for key in ("flowVersion", "teachingPolicy") if key in session})
    try:
        persistence.discard_lesson_session(session, replacement)
    except persistence.RecordConflict as error:
        from backend.session.command_runtime import conflict
        raise conflict(error) from error
    except Exception as error:
        logger.exception("Failed to reset outdated lesson session")
        raise SessionError(503, "新版课堂进度初始化失败，请稍后重试") from error
    lock = session["lock"]
    session.clear()
    session.update(replacement, lock=lock)
    return True


def get_session(sid: str, *, allow_database: bool = False) -> dict:
    allow_database = allow_database or current_identity.get() is not None
    with session_lock:
        session = sessions.get(sid)
    if session is None:
        if persistence.fresh_session_mode() and not allow_database:
            raise SessionError(404, "浏览器学习会话已结束，请重新打开课程")
        try:
            session = persistence.restore(sid)
        except Exception as error:
            raise SessionError(503, "恢复课堂失败，请稍后重试", code="STORAGE_UNAVAILABLE") from error
        if session:
            with session_lock:
                session = sessions.setdefault(sid, session)
        else:
            raise SessionError(404, "会话不存在，请重新进入课堂")
    if session.get("context") and "stateVersion" in session:
        with session["lock"]:
            try:
                saved = persistence.restore(sid)
            except Exception as error:
                raise SessionError(503, "读取学习记录失败，请稍后重试", code="STORAGE_UNAVAILABLE") from error
            if not saved:
                raise SessionError(410, "本课学习记录已重置，请重新选择课时", code="SESSION_RESET")
            original_context = session.get("context") or {}
            if saved.get("videoRevision") == session.get("videoRevision"):
                saved["context"] = dict(original_context, **saved["context"])
            session.update({key: value for key, value in saved.items() if key != "lock"})
    return session


def restore_lesson(context: dict, token: str, lesson_id: str) -> dict | None:
    """Restore only the authenticated lesson; database state outranks browser hints."""
    lessons = context.get("lessons") or []
    if (str(context.get("selectedLessonId")) != lesson_id or len(lessons) != 1
            or str(lessons[0].get("id")) != lesson_id):
        raise SessionError(409, "所选课时与课程不匹配，请重新进入课程")
    classroom_id = str((lessons[0].get("classroom") or {}).get("id") or "")
    publication = context.get("publication") or {}
    try:
        sid = persistence.latest_session_key(
            str(context["userId"]), str(context["courseId"]),
            str(publication["id"]), int(publication["version"]), lesson_id, classroom_id)
    except Exception as error:
        logger.exception("Failed to find student lesson history")
        raise SessionError(503, "读取历史会话失败，请稍后重试") from error
    if not sid:
        return None

    def read_saved() -> dict:
        try:
            saved = persistence.restore(sid)
        except Exception as error:
            logger.exception("Failed to restore student lesson history")
            raise SessionError(503, "恢复历史会话失败，请稍后重试") from error
        if not saved:
            raise SessionError(503, "历史会话暂不可用，请稍后重试")
        identity = saved.get("context") or {}
        if (saved.get("id") != sid
                or str(identity.get("userId")) != str(context["userId"])
                or str(identity.get("courseId")) != str(context["courseId"])
                or identity.get("publication") != publication
                or saved.get("lessonId") != lesson_id
                or str(saved.get("classroomId") or "") != classroom_id
                or saved.get("phase") not in {"video", "discussion", "done", "postclass", "replay"}):
            raise SessionError(409, "历史会话与当前用户或课时不匹配")
        # Postclass is a frontend view; its API handlers use the completed
        # classroom phase while postclassStage tracks the ongoing conversation.
        if saved["phase"] == "postclass":
            saved["phase"] = "done"
        saved["launchToken"] = token if isinstance(token, str) else None
        refresh_lesson(saved, context)
        return saved

    with session_lock:
        cached = sessions.get(sid)
    if cached is None:
        saved = read_saved()
        with session_lock:
            cached = sessions.setdefault(sid, saved)
        if cached is saved:
            return cached
    # Serialize refreshes with local commits; stale snapshots cannot replace
    # the newer conversation persisted by this process or another device.
    with cached["lock"]:
        saved = read_saved()
        cached.update({key: value for key, value in saved.items() if key != "lock"})
    return cached


def state(session: dict) -> dict:
    session = learning_records.normalize(session)
    teaching_view = teaching.describe_session(session)
    result = {"sessionId": session["id"], "phase": session["phase"], "lessonId": session.get("lessonId"),
            "stateVersion": session.get("stateVersion", 0),
            "contentGeneration": session.get("contentGeneration", 0),
            "flowVersion": session.get("flowVersion", "legacy_recall_v3"),
            "pendingSubmission": session.get("pendingSubmission"),
            "messages": list(session["messages"]), "courses": session["courses"],
            "preparation": session.get("preparation", "ready" if session.get("dialogue") else "idle"),
            "preparationError": session.get("preparationError", ""),
            "preparationErrorCode": session.get("preparationErrorCode", ""),
            "preparationRequestId": session.get("preparationRequestId", ""),
            "preparationCoverage": session.get("preparationCoverage"),
            "feedback": (learning_records.feedback_links(teaching.current_feedback(session), session)
                         if teaching.current_feedback(session) else None),
            **learning_records.public_view(session),
            **teaching_view,
            "postclassStage": session.get("postclassStage"),
            "videoRevision": session.get("videoRevision"),
            "videoUpdated": session.get("videoUpdated", False),
            "postclassMessages": [item for item in session["messages"]
                                  if str(item.get("phase") or "").startswith("postclass-")]}
    if persistence.fresh_session_mode():
        context = session.get("context") or {}
        course_key = f"{context.get('userId')}:{context.get('courseId')}" if context else "demo"
        result["browserCourseKey"] = course_key
        result["browserKey"] = f"{course_key}:{session.get('lessonId') or 'catalog'}"
        result["browserSnapshot"] = _browser_snapshot(session)
    if session.get("context"):
        result["userId"] = str(session["context"]["userId"])
        result["authProtocol"] = "platform-cookie-v1"
    return result


def commit(session: dict, changed: dict, *, cancel_pending: bool = False) -> None:
    if session.get("reset"):
        raise SessionError(410, "本课学习记录已重置，请重新选择课时")
    old_count = len(session["messages"])
    draft = {key: value for key, value in session.items() if key != "lock"}
    draft.update(changed)
    if cancel_pending:
        draft["_cancelPending"] = True
    try:
        draft.update(learning_records.transition(session, draft))
        persistence.save(draft, old_count)
    except persistence.RecordConflict as error:
        from backend.session.command_runtime import conflict
        raise conflict(error) from error
    except Exception as error:
        logger.exception("Failed to persist student learning record")
        raise SessionError(503, "保存学习记录失败，请稍后重试") from error
    session.update({key: value for key, value in draft.items() if key not in {"lock", "_cancelPending"}})
    if "stateVersion" in draft:
        session["stateVersion"] = draft["stateVersion"]
        session["pendingSubmission"] = None


def _safe_failure(error: Exception, request_id: str, elapsed: float) -> tuple[str, str]:
    typed = error if isinstance(error, KnowledgePreparationError) else KnowledgePreparationError("unexpected")
    cause = error.__cause__
    frames = traceback.extract_tb((cause or error).__traceback__)
    logger.error("knowledge_preparation_failed request_id=%s code=%s stage=%s error_type=%s "
                 "cause_type=%s provider_status=%s elapsed_ms=%d candidates=%d accepted=%d rejected=%d issues=%s frames=%s",
                 request_id, typed.code, typed.stage, type(error).__name__,
                 type(cause).__name__ if cause else "", getattr(cause, "status_code", None),
                 int(elapsed * 1000), typed.candidate_count,
                 typed.accepted_count, typed.rejected_count,
                 [{"index": issue.index, "reason": issue.reason} for issue in typed.issues],
                 [(Path(frame.filename).name, frame.lineno, frame.name) for frame in frames[-8:]])
    return typed.code, str(typed)


def current_materials(session: dict) -> list[dict]:
    context = session.get("context") or {}
    lesson_id = session.get("lessonId")
    if context.get("lessons"):
        return lesson_points(context, lesson_id)
    if not session.get("classroomId"):
        return session.get("preparationMaterials") or []  # Local demo only.
    return classroom_materials(persistence.classroom_scenes(session["classroomId"]))


def prepare_in_background(session: dict) -> None:
    request_id = secrets.token_hex(8)
    started = time.monotonic()
    generation = session.get("contentGeneration", 0)
    try:
        # The model must never hold the session lock while a video is playing.
        materials = current_materials(session)
        dialogue, coverage = teaching.prepare(materials)
        logger.info("knowledge_preparation_completed request_id=%s elapsed_ms=%d accepted=%d rejected=%d repair=%s",
                    request_id, int((time.monotonic() - started) * 1000),
                    coverage["acceptedCount"], coverage["rejectedCount"], coverage["repairAttempted"])
        with session["lock"]:
            if generation != session.get("contentGeneration", 0):
                return
            commit(session, {"dialogue": dialogue,
                             "preparation": "partial" if coverage["partial"] else "ready",
                             "preparationMaterials": materials,
                             "preparationError": "", "preparationErrorCode": "",
                             "preparationRequestId": request_id, "preparationCoverage": coverage})
    except Exception as error:
        code, message = _safe_failure(error, request_id, time.monotonic() - started)
        with session["lock"]:
            if generation != session.get("contentGeneration", 0):
                return
            had_partial = bool(session.get("dialogue") and
                               (session.get("preparationCoverage") or {}).get("partial"))
            changed = {"preparation": "partial" if had_partial else "error",
                       "preparationError": message,
                       "preparationErrorCode": code, "preparationRequestId": request_id}
            try:
                commit(session, changed)
            except SessionError:
                session.update(changed)
    finally:
        with session_lock:
            preparing.discard(session["id"])


def schedule_preparation(session: dict, tasks: BackgroundWork) -> None:
    if session.get("context"):
        return  # Published lessons are prepared by the durable publication worker.
    if session.get("preparation") != "pending":
        return
    with session_lock:
        if session["id"] in preparing:
            return
        preparing.add(session["id"])
    tasks.add_task(prepare_in_background, session)


def sync_published_preparation(session: dict, *, persist: bool = True) -> None:
    """Populate only this student's dialogue from the published shared result."""
    context = session.get("context") or {}
    if not context or session.get("phase") != "video" or session.get("dialogue"):
        return
    lesson_id, revision = session.get("lessonId"), session.get("videoRevision")
    if not lesson_id or not revision:
        return
    result = published_knowledge.read(str(context["courseId"]), str(lesson_id), revision)
    if result and result["status"] == "ready" and result["points"]:
        binding = lesson_content.bind(session, result)
        changed = {"dialogue": teaching.new_dialogue(result["points"]),
                   "contentRef": binding["contentRef"], "lessonContent": binding["lessonContent"],
                   "preparation": "ready", "preparationCoverage": result["coverage"],
                   "preparationError": "", "preparationErrorCode": ""}
        if persist:
            commit(session, changed)
        else:
            session.update(changed)
    elif result and result["status"] == "failed":
        session.update(preparation="error", preparationError="知识点整理失败，可点击重试",
                       preparationErrorCode="published_extraction_failed")
    else:
        session.update(preparation="pending", preparationError="", preparationErrorCode="")


def upgrade_curriculum(session: dict) -> None:
    """Rebuild old saved sessions from the exact classroom shown by the player."""
    previous = session.get("dialogue") or {}
    if previous.get("points"):
        return
    if previous.get("curriculum_version") == CURRICULUM_VERSION:
        return
    if session.get("context"):
        context = session["context"]
        result = published_knowledge.read(str(context["courseId"]),
                                          str(session["lessonId"]), str(session["videoRevision"]))
        if not result or result["status"] != "ready":
            raise SessionError(409, "本课知识点正在整理，请稍后重试")
        dialogue = teaching.new_dialogue(result["points"])
        commit(session, {"dialogue": dialogue, "preparation": "ready",
                         "preparationCoverage": result["coverage"]})
        return
    materials = current_materials(session)
    try:
        dialogue, coverage = teaching.prepare(materials)
    except Exception as error:
        request_id = secrets.token_hex(8)
        code, message = _safe_failure(error, request_id, 0)
        raise SessionError(409 if code == "no_content" else 503,
                            f"{message}（问题编号：{request_id}）") from error
    messages = list(session["messages"])
    if session["phase"] == "discussion":
        messages.append({"role": "assistant", "phase": "recall",
                         "text": "我已重新整理本课的学习内容，接下来以这份清单为准。\n\n"
                                 + teaching.opening_text(dialogue)})
    commit(session, {"dialogue": dialogue, "preparationMaterials": materials,
                     "preparation": "partial" if coverage["partial"] else "ready",
                     "preparationCoverage": coverage, "preparationError": "",
                     "preparationErrorCode": "",
                     "messages": messages})


def start(launch_token: str = "") -> dict:
    identity = current_identity.get()
    if identity or launch_token:
        context = platform_access.platform_context(identity or launch_token)
        courses = catalog(context)
    else:
        context = None
        demo = os.environ.get("STUDENT_NEW_DEMO_PLAYER_URL", "")
        if not demo:
            raise SessionError(400, "请从课程平台进入课堂")
        courses = [{"id": "demo", "title": "演示课程", "lessons": [{
            "id": "demo-lesson", "title": "演示课时", "week": 1, "lessonNumber": 1,
            "summary": "本地流程预览", "playerUrl": demo, "segmentCount": 1}]}]
    sid = secrets.token_urlsafe(24)
    with session_lock:
        sessions[sid] = {"id": sid, "context": context, "courses": courses,
                         "launchToken": launch_token if context and not identity else None,
                         "phase": "idle", "lessonId": None, "messages": [],
                         "dialogue": None, "lock": Lock()}
    return state(sessions[sid])


def resume(launch_token: str, lesson_id: str, background_tasks: BackgroundWork) -> dict:
    launch_token = current_identity.get() or launch_token
    if not launch_token:
        raise SessionError(401, "请从平台重新进入课程以恢复历史会话")
    context = platform_access.platform_context(launch_token, lesson_id)
    session = restore_lesson(context, launch_token, lesson_id)
    if session is None:
        raise SessionError(404, "该课时暂无历史会话", code="HISTORY_NOT_FOUND")
    with session["lock"]:
        schedule_preparation(session, background_tasks)
        schedule_progress_sync(session, "ended" if session["phase"] == "done" else "started", background_tasks)
        return state(session)


def browser_restore(snapshot: str, launch_token: str, background_tasks: BackgroundWork) -> dict:
    if not persistence.fresh_session_mode():
        raise SessionError(404, "浏览器学习记录恢复未启用")
    restored = _restore_browser_snapshot(snapshot)
    if restored.get("context") and not restored.get("lessonId"):
        if not launch_token:
            raise SessionError(401, "请从平台重新进入课程以恢复历史会话")
        return start(launch_token)
    current = None
    saved = None
    lesson_id = restored.get("lessonId")
    if restored.get("context") and lesson_id:
        if not launch_token:
            raise SessionError(401, "请从平台重新进入课程以恢复学习记录")
        current = platform_access.platform_context(launch_token, lesson_id, True)
        original = restored["context"]
        if any(str(current.get(key)) != str(original.get(key)) for key in ("userId", "courseId")):
            raise SessionError(403, "学习记录与当前用户或课程不匹配")
        if str(current.get("selectedLessonId")) != lesson_id or len(current.get("lessons") or []) != 1:
            raise SessionError(409, "当前课时尚未发布")
        classroom_id = str((current["lessons"][0].get("classroom") or {}).get("id") or "")
        publication = current.get("publication") or {}
        try:
            latest_id = persistence.latest_session_key(
                str(current["userId"]), str(current["courseId"]),
                str(publication["id"]), int(publication["version"]),
                lesson_id, classroom_id,
            )
            saved = persistence.restore(latest_id or restored["id"])
        except Exception as error:
            logger.exception("Failed to restore browser lesson from database")
            raise SessionError(503, "读取学习记录失败，请稍后重试") from error
        if not saved:
            raise SessionError(404, "本课学习记录已重置，请重新选择课时")
        saved_context = saved.get("context") or {}
        if (str(saved_context.get("userId")) != str(current["userId"])
                or str(saved_context.get("courseId")) != str(current["courseId"])
                or saved.get("lessonId") != lesson_id):
            raise SessionError(409, "数据库学习记录与当前课时不匹配")
        restored = saved
    restored["launchToken"] = launch_token or None
    with session_lock:
        session = sessions.setdefault(restored["id"], restored)
    with session["lock"]:
        if saved and session is not restored:
            session.update({key: value for key, value in restored.items()
                            if key not in {"lock", "launchToken"}})
        if launch_token:
            session["launchToken"] = launch_token
        refresh_lesson(session, current)
        schedule_progress_sync(session, "ended" if session["phase"] == "done" else "started", background_tasks)
    return state(session)


def read(sid: str, background_tasks: BackgroundWork) -> dict:
    session = get_session(sid)
    with session["lock"]:
        if current_identity.get():
            projected = dict(session)
            sync_published_preparation(projected, persist=False)
            return state(projected)
        sync_published_preparation(session)
        schedule_preparation(session, background_tasks)
        return state(session)


def begin(sid: str, lesson_id: str, background_tasks: BackgroundWork) -> dict:
    session = get_session(sid)
    lesson = next((lesson for course in session["courses"] for lesson in course["lessons"]
                   if lesson["id"] == lesson_id), None)
    if not lesson:
        raise SessionError(404, "未找到该课时")
    selected_context = None
    selected_courses = None
    if session.get("context") and session["phase"] == "idle":
        token = _credential(session)
        if not token:
            raise SessionError(409, "启动令牌已失效，请从平台重新进入课程")
        selected_context = platform_access.platform_context(token, lesson_id)
        original = session["context"]
        if (str(selected_context.get("userId")) != str(original.get("userId"))
                or str(selected_context.get("courseId")) != str(original.get("courseId"))
                or str(selected_context.get("selectedLessonId")) != lesson_id
                or len(selected_context.get("lessons") or []) != 1):
            raise SessionError(409, "所选课时与课程不匹配，请重新进入课程")
        selected_courses = catalog(selected_context)
        original = selected_context
        lesson = next((item for item in selected_courses[0]["lessons"] if item["id"] == lesson_id), None)
        if not lesson or not lesson.get("playerUrl"):
            raise SessionError(409, "所选课时没有已发布的播放器")
        resumed = restore_lesson(selected_context, token, lesson_id)
        if resumed is not None:
            with resumed["lock"]:
                schedule_preparation(resumed, background_tasks)
                restored_state = state(resumed)
            with session_lock:
                sessions.pop(sid, None)
            schedule_progress_sync(resumed, "ended" if resumed["phase"] == "done" else "started", background_tasks)
            return restored_state
    with session["lock"]:
        if session["phase"] != "idle":
            if session["lessonId"] != lesson_id:
                raise SessionError(409, "请结束当前课时后再开始其他课时")
            refresh_lesson(session)
            schedule_preparation(session, background_tasks)
            schedule_progress_sync(session, "ended" if session["phase"] == "done" else "started", background_tasks)
            return state(session)
        context = selected_context or session["context"]
        materials = lesson_points(context, lesson_id) if context else [
            {"id": "demo", "title": lesson["title"], "content": lesson.get("summary") or lesson["title"],
             "source": "demo"}]
        commit(session, {"context": context, "courses": selected_courses or session["courses"],
                         **teaching.select_flow(context, lesson_id),
                         "videoRevision": video_revision(context, lesson_id) if context else None,
                         "lessonId": lesson_id, "classroomId": lesson.get("classroomId"),
                         "phase": "video", "dialogue": None,
                         "preparation": "pending", "preparationError": "",
                         "preparationErrorCode": "", "preparationRequestId": "",
                         "preparationCoverage": None,
                         "preparationMaterials": materials})
        schedule_preparation(session, background_tasks)
        sync_published_preparation(session)
        schedule_progress_sync(session, "started", background_tasks)
    return state(session)


def replay_playback(sid: str, launch_token: str) -> dict:
    """Resolve playback without changing the saved feedback or learning phase."""
    session = get_session(sid)
    with session["lock"]:
        lesson_id = session.get("lessonId")
        if not lesson_id or session["phase"] not in {"done", "replay", "postclass"}:
            raise SessionError(409, "请先结束本课，再回看视频")
        original = session.get("context")
        classroom_id = session.get("classroomId")
        token = _credential(session, launch_token)
        if not original:
            course = next((item for item in session["courses"]
                           if any(lesson["id"] == lesson_id for lesson in item["lessons"])), None)
            lesson = next((item for item in (course or {}).get("lessons", [])
                           if item["id"] == lesson_id), None)
            if not lesson or not lesson.get("playerUrl"):
                raise SessionError(409, "本课时暂时没有可播放的视频，请从课时列表重新进入")
            return {"courseId": course["id"], "lesson": lesson}
    if not token:
        raise SessionError(409, "启动令牌已失效，请从平台重新进入课程后回看")
    # The platform rechecks enrollment and publication. No /begin call or
    # persistence write is needed to recover a missing player URL.
    context = platform_access.platform_context(token, lesson_id)
    if (str(context.get("userId")) != str(original.get("userId"))
            or str(context.get("courseId")) != str(original.get("courseId"))
            or (context.get("publication") or {}) != (original.get("publication") or {})
            or str(context.get("selectedLessonId")) != lesson_id
            or len(context.get("lessons") or []) != 1
            or str(context["lessons"][0].get("id")) != lesson_id):
        raise SessionError(409, "播放信息与当前课时不匹配，请从平台重新进入课程")
    course = catalog(context)[0]
    lesson = next((item for item in course["lessons"] if item["id"] == lesson_id), None)
    if not lesson or not lesson.get("playerUrl"):
        raise SessionError(409, "本课时暂时没有已发布的播放器，请稍后重试或联系教师")
    if classroom_id and lesson.get("classroomId") != classroom_id:
        raise SessionError(409, "本课时的课堂内容已更新，暂时无法回看原课堂，请联系教师")
    return {"courseId": course["id"], "lesson": lesson}


def retry_preparation(sid: str, background_tasks: BackgroundWork) -> dict:
    session = get_session(sid)
    with session["lock"]:
        if session["phase"] != "video":
            raise SessionError(409, "当前不在视频阶段")
        if session.get("context"):
            context = session["context"]
            scope = (str(context["courseId"]), str(session["lessonId"]),
                     str(session["videoRevision"]))
            if not published_knowledge.retry(*scope) and published_knowledge.read(*scope) is None:
                raise SessionError(409, "当前课时尚未登记知识点准备任务，请从平台重新进入课程")
            session.update(preparation="pending", preparationError="", preparationErrorCode="")
            sync_published_preparation(session)
            return state(session)
        if session.get("preparation") in {"error", "partial"}:
            commit(session, {"preparation": "pending", "preparationError": "",
                             "preparationErrorCode": ""})
        schedule_preparation(session, background_tasks)
        return state(session)


def discussion(sid: str, background_tasks: BackgroundWork) -> dict:
    session = get_session(sid)
    with session["lock"]:
        if session["phase"] == "video":
            sync_published_preparation(session)
            if session.get("preparation") == "pending":
                schedule_preparation(session, background_tasks)
                return state(session)
            if session.get("preparation") == "error":
                raise SessionError(409, session["preparationError"])
            upgrade_curriculum(session)
            commit(session, teaching.start_discussion(session))
        elif session["phase"] != "discussion":
            raise SessionError(409, "请先开始上课")
        else:
            upgrade_curriculum(session)
    return state(session)


def message(sid: str, text: str) -> dict:
    session = get_session(sid)
    with session["lock"]:
        if session["phase"] != "discussion":
            raise SessionError(409, "当前不在复述与讨论阶段")
        upgrade_curriculum(session)
        commit(session, teaching.classroom_turn(session, text))
    return state(session)


def end(sid: str, background_tasks: BackgroundWork) -> dict:
    session = get_session(sid)
    with session["lock"]:
        changed = teaching.finish(session)
        if changed:
            commit(session, changed, cancel_pending=True)
            schedule_progress_sync(session, "ended", background_tasks)
    return state(session)


def reset_lesson(sid: str, launch_token: str, background_tasks: BackgroundWork) -> dict:
    session = get_session(sid)
    context = session.get("context") or {}
    lesson_id = session.get("lessonId")
    if not lesson_id:
        raise SessionError(409, "当前没有可重置的课时")
    token = _credential(session, launch_token)
    current = None
    if context:
        if not token:
            raise SessionError(401, "请从平台重新进入课程以重置学习记录")
        current = platform_access.platform_context(token, lesson_id, True)
        if (str(current.get("userId")) != str(context.get("userId"))
                or str(current.get("courseId")) != str(context.get("courseId"))):
            raise SessionError(403, "学习记录与当前用户或课程不匹配")
        if str(current.get("selectedLessonId")) != lesson_id:
            raise SessionError(409, "当前课时尚未发布")
    with session_lock:
        related = [item for item in sessions.values()
                   if item.get("lessonId") == lesson_id
                   and (item.get("context") or {}).get("userId") == context.get("userId")
                   and (item.get("context") or {}).get("courseId") == context.get("courseId")]
    if all(item is not session for item in related):
        related.append(session)
    with ExitStack() as locks:
        for item in sorted(related, key=lambda value: value["id"]):
            locks.enter_context(item["lock"])
        if session["phase"] != "done":
            raise SessionError(409, "请在本课结束页面重置学习进度")
        if context:
            try:
                deleted = persistence.reset_lesson(
                    str(context["userId"]), str(context["courseId"]), lesson_id, sid,
                    [item["id"] for item in related])
            except persistence.RecordConflict as error:
                from backend.session.command_runtime import conflict
                raise conflict(error) from error
            except Exception as error:
                logger.exception("Failed to reset student lesson progress: session=%s", sid)
                raise SessionError(503, "重置本课学习进度失败，请稍后重试") from error
        else:
            deleted = [sid]
        for item in related:
            if item["id"] in deleted:
                item["reset"] = True
                item["contentGeneration"] = item.get("contentGeneration", 0) + 1
        with session_lock:
            for key in deleted:
                sessions.pop(key, None)
    fresh_context = dict(current, selectedLessonId=None, lessons=[]) if current else None
    new_id = secrets.token_urlsafe(24)
    fresh = {"id": new_id, "context": fresh_context,
             "courses": catalog(fresh_context) if fresh_context else session["courses"],
             "launchToken": token if fresh_context else None,
             "phase": "idle", "lessonId": None, "messages": [],
             "dialogue": None, "lock": Lock()}
    with session_lock:
        sessions[new_id] = fresh
    if context:
        schedule_progress_sync(session, "reset", background_tasks)
    return state(fresh)


def feedback(sid: str) -> dict:
    session = get_session(sid)
    if not session.get("feedback"):
        raise SessionError(409, "本次课堂反馈尚未生成，请先结束本节课")
    return teaching.current_feedback(session)


def start_postclass(sid: str) -> dict:
    session = get_session(sid)
    with session["lock"]:
        changed = teaching.start_postclass(session)
        if changed:
            commit(session, changed)
    return state(session)


def postclass_message(sid: str, text: str) -> dict:
    session = get_session(sid)
    with session["lock"]:
        commit(session, teaching.postclass_turn(session, text))
    return state(session)
