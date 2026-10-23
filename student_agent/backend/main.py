"""Student classroom API with lesson-scoped LangGraph discussion."""
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
import urllib.error
import urllib.request
from pathlib import Path
from threading import Lock

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent.context import classroom_materials, lesson_points
from agent.graph import dialogue_graph, initial_state, opening
from agent.knowledge import CURRICULUM_VERSION, KnowledgePreparationError, learning_points
from agent.progression import normalize, progress
from agent.feedback import lesson_feedback
from agent.postclass import pending_points, postclass_graph, postclass_stage
from agent import persistence

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "out"
app = FastAPI(title="Student Agent")
logger = logging.getLogger(__name__)
sessions: dict[str, dict] = {}
session_lock = Lock()
preparing: set[str] = set()


class StartRequest(BaseModel):
    launch_token: str = ""


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class BrowserRestoreRequest(BaseModel):
    snapshot: str = Field(min_length=1, max_length=4_000_000)
    launch_token: str = ""


def _browser_snapshot(session: dict) -> str:
    payload = {key: value for key, value in session.items()
               if key not in {"lock", "launchToken"}}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    secret = os.environ["STUDENT_SERVICE_KEY"].encode()
    signature = hmac.new(secret, b"browser-session:" + encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _restore_browser_snapshot(value: str) -> dict:
    encoded, separator, signature = value.partition(".")
    secret = os.environ.get("STUDENT_SERVICE_KEY", "").encode()
    expected = hmac.new(secret, b"browser-session:" + encoded.encode(), hashlib.sha256).hexdigest()
    if not secret or not separator or not hmac.compare_digest(signature, expected):
        raise HTTPException(400, "浏览器学习记录无效，请重新进入课程")
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        restored = json.loads(raw)
    except (ValueError, UnicodeError, TypeError) as error:
        raise HTTPException(400, "浏览器学习记录无效，请重新进入课程") from error
    if (not isinstance(restored, dict) or not isinstance(restored.get("id"), str)
            or not isinstance(restored.get("courses"), list)
            or not isinstance(restored.get("messages"), list)
            or restored.get("phase") not in {"idle", "video", "discussion", "done", "replay", "postclass"}):
        raise HTTPException(400, "浏览器学习记录不完整，请重新进入课程")
    restored["lock"] = Lock()
    return restored


def platform_context(token: str, lesson_id: str | None = None) -> dict:
    base = os.environ.get("PLATFORM_AUTH_URL", "").rstrip("/")
    key = os.environ.get("STUDENT_SERVICE_KEY", "")
    if not base or not key:
        raise HTTPException(503, "请配置 PLATFORM_AUTH_URL 和 STUDENT_SERVICE_KEY")
    # The teacher service shares PLATFORM_AUTH_URL but treats it as the host
    # base; the local student launcher may already include /api/v1.
    if not base.endswith("/api/v1"):
        base += "/api/v1"
    request = urllib.request.Request(
        base + "/internal/student/learning-context",
        data=json.dumps({"launch_token": token, "lesson_id": lesson_id}).encode(),
        headers={"Content-Type": "application/json", "X-Student-Service-Key": key},
        method="POST",
    )
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise HTTPException(error.code, "平台课堂读取失败或启动令牌已过期") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise HTTPException(503, "平台服务暂不可用") from error


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


def get_session(sid: str) -> dict:
    with session_lock:
        session = sessions.get(sid)
    if session is None:
        if persistence.fresh_session_mode():
            raise HTTPException(404, "浏览器学习会话已结束，请重新打开课程")
        try:
            session = persistence.restore(sid)
        except Exception as error:
            raise HTTPException(503, f"恢复课堂失败：{error}") from error
        if session:
            with session_lock:
                session = sessions.setdefault(sid, session)
        else:
            raise HTTPException(404, "会话不存在，请重新进入课堂")
    return session


def state(session: dict) -> dict:
    dialogue = normalize(session["dialogue"]) if session.get("dialogue") else None
    result = {"sessionId": session["id"], "phase": session["phase"], "lessonId": session.get("lessonId"),
            "messages": list(session["messages"]), "courses": session["courses"],
            "preparation": session.get("preparation", "ready" if session.get("dialogue") else "idle"),
            "preparationError": session.get("preparationError", ""),
            "preparationErrorCode": session.get("preparationErrorCode", ""),
            "preparationRequestId": session.get("preparationRequestId", ""),
            "preparationCoverage": session.get("preparationCoverage"),
            "feedback": session.get("feedback"),
            "agentStage": (dialogue or {}).get("stage"),
            "learningProgress": progress(dialogue) if dialogue else None,
            "postclassStage": session.get("postclassStage"),
            "postclassMessages": [item for item in session["messages"]
                                  if str(item.get("phase") or "").startswith("postclass-")]}
    if persistence.fresh_session_mode():
        context = session.get("context") or {}
        course_key = f"{context.get('userId')}:{context.get('courseId')}" if context else "demo"
        result["browserCourseKey"] = course_key
        result["browserKey"] = f"{course_key}:{session.get('lessonId') or 'catalog'}"
        result["browserSnapshot"] = _browser_snapshot(session)
    return result


def commit(session: dict, changed: dict) -> None:
    old_count = len(session["messages"])
    draft = {key: value for key, value in session.items() if key != "lock"}
    draft.update(changed)
    try:
        persistence.save(draft, old_count)
    except Exception as error:
        logger.exception("Failed to persist student learning record")
        raise HTTPException(503, "保存学习记录失败，请稍后重试") from error
    session.update(changed)


def prepared_dialogue(materials: list[dict]) -> tuple[dict, dict]:
    result = learning_points(materials)
    coverage = {"partial": result.partial, "acceptedCount": len(result.points),
                "rejectedCount": result.rejected_count,
                "candidateCount": result.candidate_count,
                "repairAttempted": result.repair_attempted}
    return dict(initial_state(result.points), curriculum_version=CURRICULUM_VERSION), coverage


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
    try:
        # The model must never hold the session lock while a video is playing.
        materials = current_materials(session)
        dialogue, coverage = prepared_dialogue(materials)
        logger.info("knowledge_preparation_completed request_id=%s elapsed_ms=%d accepted=%d rejected=%d repair=%s",
                    request_id, int((time.monotonic() - started) * 1000),
                    coverage["acceptedCount"], coverage["rejectedCount"], coverage["repairAttempted"])
        with session["lock"]:
            commit(session, {"dialogue": dialogue,
                             "preparation": "partial" if coverage["partial"] else "ready",
                             "preparationMaterials": materials,
                             "preparationError": "", "preparationErrorCode": "",
                             "preparationRequestId": request_id, "preparationCoverage": coverage})
    except Exception as error:
        code, message = _safe_failure(error, request_id, time.monotonic() - started)
        with session["lock"]:
            had_partial = bool(session.get("dialogue") and
                               (session.get("preparationCoverage") or {}).get("partial"))
            changed = {"preparation": "partial" if had_partial else "error",
                       "preparationError": message,
                       "preparationErrorCode": code, "preparationRequestId": request_id}
            try:
                commit(session, changed)
            except HTTPException:
                session.update(changed)
    finally:
        with session_lock:
            preparing.discard(session["id"])


def schedule_preparation(session: dict, tasks: BackgroundTasks) -> None:
    if session.get("preparation") != "pending":
        return
    with session_lock:
        if session["id"] in preparing:
            return
        preparing.add(session["id"])
    tasks.add_task(prepare_in_background, session)


def upgrade_curriculum(session: dict) -> None:
    """Rebuild old saved sessions from the exact classroom shown by the player."""
    previous = session.get("dialogue") or {}
    if previous.get("curriculum_version") == CURRICULUM_VERSION:
        return
    materials = current_materials(session)
    try:
        dialogue, coverage = prepared_dialogue(materials)
    except Exception as error:
        request_id = secrets.token_hex(8)
        code, message = _safe_failure(error, request_id, 0)
        raise HTTPException(409 if code == "no_content" else 503,
                            f"{message}（问题编号：{request_id}）") from error
    messages = list(session["messages"])
    if session["phase"] == "discussion":
        messages.append({"role": "assistant", "phase": "recall",
                         "text": "我已重新整理本课的学习内容，接下来以这份清单为准。\n\n"
                                 + opening(dialogue["points"])})
    commit(session, {"dialogue": dialogue, "preparationMaterials": materials,
                     "preparation": "partial" if coverage["partial"] else "ready",
                     "preparationCoverage": coverage, "preparationError": "",
                     "preparationErrorCode": "",
                     "messages": messages})


@app.post("/api/session/start")
def start(body: StartRequest) -> dict:
    if body.launch_token:
        context = platform_context(body.launch_token)
        courses = catalog(context)
    else:
        context = None
        demo = os.environ.get("STUDENT_NEW_DEMO_PLAYER_URL", "")
        if not demo:
            raise HTTPException(400, "请从课程平台进入课堂")
        courses = [{"id": "demo", "title": "演示课程", "lessons": [{
            "id": "demo-lesson", "title": "演示课时", "week": 1, "lessonNumber": 1,
            "summary": "本地流程预览", "playerUrl": demo, "segmentCount": 1}]}]
    sid = secrets.token_urlsafe(24)
    with session_lock:
        sessions[sid] = {"id": sid, "context": context, "courses": courses,
                         "launchToken": body.launch_token if context else None,
                         "phase": "idle", "lessonId": None, "messages": [],
                         "dialogue": None, "lock": Lock()}
    return state(sessions[sid])


@app.post("/api/session/browser-restore")
def browser_restore(body: BrowserRestoreRequest) -> dict:
    if not persistence.fresh_session_mode():
        raise HTTPException(404, "浏览器学习记录恢复未启用")
    restored = _restore_browser_snapshot(body.snapshot)
    restored["launchToken"] = body.launch_token or None
    with session_lock:
        session = sessions.setdefault(restored["id"], restored)
    if body.launch_token:
        with session["lock"]:
            session["launchToken"] = body.launch_token
    return state(session)


@app.get("/api/session/health")
def health() -> dict:
    if not (os.environ.get("PLATFORM_AUTH_URL") and os.environ.get("STUDENT_SERVICE_KEY")):
        raise HTTPException(503, "平台连接尚未配置")
    if not (os.environ.get("STUDENT_AGENT_API_KEY") or os.environ.get("LLM_API_KEY")):
        raise HTTPException(503, "课堂导师模型尚未配置")
    if not (os.environ.get("STUDENT_DATABASE_URL") or os.environ.get("DATABASE_URL")):
        raise HTTPException(503, "学习数据库尚未配置")
    return {"ok": True}


@app.get("/api/session/platform-entry")
def platform_entry() -> dict:
    return {
        "platformUrl": os.environ.get("FRONTEND_HOST", "http://localhost:8088").rstrip("/"),
        "demoEnabled": bool(os.environ.get("STUDENT_NEW_DEMO_PLAYER_URL")),
        "freshSessionMode": persistence.fresh_session_mode(),
    }


@app.get("/demo-player")
def demo_player():
    if not os.environ.get("STUDENT_NEW_DEMO_PLAYER_URL"):
        raise HTTPException(404)
    return HTMLResponse("""<!doctype html><html lang='zh-CN'><meta charset='utf-8'>
<body style='margin:0;display:grid;place-items:center;height:100vh;background:#18243b;color:white;font:20px sans-serif'>
<button style='padding:16px 24px;font:inherit' onclick="parent.postMessage({type:'PLAYBACK_ENDED'},location.origin)">模拟视频播放完成</button>
</body></html>""")


@app.get("/api/session/{sid}")
def read(sid: str, background_tasks: BackgroundTasks) -> dict:
    session = get_session(sid)
    with session["lock"]:
        schedule_preparation(session, background_tasks)
        return state(session)


@app.post("/api/session/{sid}/begin/{lesson_id}")
def begin(sid: str, lesson_id: str, background_tasks: BackgroundTasks) -> dict:
    session = get_session(sid)
    lesson = next((lesson for course in session["courses"] for lesson in course["lessons"]
                   if lesson["id"] == lesson_id), None)
    if not lesson:
        raise HTTPException(404, "未找到该课时")
    selected_context = None
    selected_courses = None
    if session.get("context") and session["phase"] == "idle":
        token = session.get("launchToken")
        if not token:
            raise HTTPException(409, "启动令牌已失效，请从平台重新进入课程")
        selected_context = platform_context(token, lesson_id)
        original = session["context"]
        if (str(selected_context.get("userId")) != str(original.get("userId"))
                or str(selected_context.get("courseId")) != str(original.get("courseId"))
                or str((selected_context.get("publication") or {}).get("id"))
                != str((original.get("publication") or {}).get("id"))
                or (selected_context.get("publication") or {}).get("version")
                != (original.get("publication") or {}).get("version")
                or str(selected_context.get("selectedLessonId")) != lesson_id
                or len(selected_context.get("lessons") or []) != 1):
            raise HTTPException(409, "所选课时与课程不匹配，请重新进入课程")
        selected_courses = catalog(selected_context)
        lesson = next((item for item in selected_courses[0]["lessons"] if item["id"] == lesson_id), None)
        if not lesson or not lesson.get("playerUrl"):
            raise HTTPException(409, "所选课时没有已发布的播放器")
        try:
            old_id = None if persistence.fresh_session_mode() else persistence.latest_session_key(
                str(original["userId"]), str(original["courseId"]),
                str((original.get("publication") or {})["id"]),
                int((original.get("publication") or {})["version"]),
                lesson_id, str(lesson["classroomId"]),
            )
        except Exception as error:
            logger.exception("Failed to find previous student lesson session")
            raise HTTPException(503, "读取上次课堂失败，请稍后重试") from error
        if old_id:
            resumed = get_session(old_id)
            saved_context = resumed.get("context") or {}
            if (str(saved_context.get("userId")) == str(original["userId"])
                    and str(saved_context.get("courseId")) == str(original["courseId"])
                    and str((saved_context.get("publication") or {}).get("id"))
                    == str((original.get("publication") or {}).get("id"))
                    and int((saved_context.get("publication") or {}).get("version") or 0)
                    == int((original.get("publication") or {}).get("version") or 0)
                    and resumed.get("lessonId") == lesson_id
                    and resumed.get("classroomId") == lesson["classroomId"]
                    and resumed.get("phase") in {"video", "discussion", "done"}):
                with resumed["lock"]:
                    resumed["context"] = selected_context
                    resumed["courses"] = selected_courses
                    schedule_preparation(resumed, background_tasks)
                    restored_state = state(resumed)
                with session_lock:
                    sessions.pop(sid, None)
                return restored_state
    with session["lock"]:
        if session["phase"] != "idle":
            if session["lessonId"] != lesson_id:
                raise HTTPException(409, "请结束当前课时后再开始其他课时")
            schedule_preparation(session, background_tasks)
            return state(session)
        context = selected_context or session["context"]
        materials = lesson_points(context, lesson_id) if context else [
            {"id": "demo", "title": lesson["title"], "content": lesson.get("summary") or lesson["title"],
             "source": "demo"}]
        commit(session, {"context": context, "courses": selected_courses or session["courses"],
                         "lessonId": lesson_id, "classroomId": lesson.get("classroomId"),
                         "phase": "video", "dialogue": None,
                         "preparation": "pending", "preparationError": "",
                         "preparationErrorCode": "", "preparationRequestId": "",
                         "preparationCoverage": None,
                         "preparationMaterials": materials})
        schedule_preparation(session, background_tasks)
    return state(session)


@app.post("/api/session/{sid}/prepare")
def retry_preparation(sid: str, background_tasks: BackgroundTasks) -> dict:
    session = get_session(sid)
    with session["lock"]:
        if session["phase"] != "video":
            raise HTTPException(409, "当前不在视频阶段")
        if session.get("preparation") in {"error", "partial"}:
            commit(session, {"preparation": "pending", "preparationError": "",
                             "preparationErrorCode": ""})
        schedule_preparation(session, background_tasks)
        return state(session)


@app.post("/api/session/{sid}/discussion")
def discussion(sid: str, background_tasks: BackgroundTasks) -> dict:
    session = get_session(sid)
    with session["lock"]:
        if session["phase"] == "video":
            if session.get("preparation") == "pending":
                schedule_preparation(session, background_tasks)
                return state(session)
            if session.get("preparation") == "error":
                raise HTTPException(409, session["preparationError"])
            upgrade_curriculum(session)
            first = {"role": "assistant", "text": opening(session["dialogue"]["points"]),
                     "phase": "recall"}
            commit(session, {"phase": "discussion", "messages": session["messages"] + [first]})
        elif session["phase"] != "discussion":
            raise HTTPException(409, "请先开始上课")
        else:
            upgrade_curriculum(session)
    return state(session)


@app.post("/api/session/{sid}/message")
def message(sid: str, body: MessageRequest) -> dict:
    session = get_session(sid)
    with session["lock"]:
        if session["phase"] != "discussion":
            raise HTTPException(409, "当前不在复述与讨论阶段")
        upgrade_curriculum(session)
        normalized = normalize(session["dialogue"])
        if normalized["stage"] == "wrapup":
            raise HTTPException(409, "课堂对话已完成，请结束本课并查看反馈；结束后可继续课后对话")
        student = {"role": "student", "text": body.text.strip(),
                   "phase": normalized["stage"]}
        dialogue = normalized
        dialogue["student_text"] = student["text"]
        dialogue["messages"] = session["messages"] + [student]
        try:
            dialogue = dialogue_graph.invoke(dialogue)
        except Exception as error:
            logger.exception("课堂导师对话失败：session=%s", sid)
            raise HTTPException(503, "课堂导师暂不可用，请稍后重试") from error
        assistant = {"role": "assistant", "text": dialogue["reply"],
                     "phase": dialogue["stage"]}
        commit(session, {"dialogue": dialogue,
                         "messages": session["messages"] + [student, assistant]})
    return state(session)


@app.post("/api/session/{sid}/end")
def end(sid: str) -> dict:
    session = get_session(sid)
    with session["lock"]:
        if session["phase"] == "done" and session.get("feedback"):
            return state(session)
        if session["phase"] not in {"discussion", "done"}:
            raise HTTPException(409, "请先进入复述与讨论")
        feedback = lesson_feedback(session)
        commit(session, {"phase": "done", "feedback": feedback})
    return state(session)


@app.get("/api/session/{sid}/feedback")
def feedback(sid: str) -> dict:
    session = get_session(sid)
    if not session.get("feedback"):
        raise HTTPException(409, "本次课堂反馈尚未生成，请先结束本节课")
    return session["feedback"]


@app.post("/api/session/{sid}/postclass/start")
def start_postclass(sid: str) -> dict:
    session = get_session(sid)
    with session["lock"]:
        if session["phase"] != "done" or not session.get("dialogue"):
            raise HTTPException(409, "请先结束本节课")
        if not session.get("postclassStage"):
            stage = postclass_stage(normalize(session["dialogue"])["points"])
            if stage == "remediation":
                focus = pending_points(session["dialogue"]["points"])[0]
                opening_text = f"我们先补完课堂上还没掌握的知识点。从「{focus['title']}」开始：你现在能用自己的话说说它吗？不记得可以直接问我。"
            else:
                opening_text = "课堂知识点已经完成了。现在可以自由向我提问其他问题。"
            first = {"role": "assistant", "text": opening_text, "phase": "postclass-" + stage}
            commit(session, {"postclassStage": stage, "classroomFeedback": session["feedback"],
                             "messages": session["messages"] + [first]})
    return state(session)


@app.post("/api/session/{sid}/postclass/message")
def postclass_message(sid: str, body: MessageRequest) -> dict:
    session = get_session(sid)
    with session["lock"]:
        stage = session.get("postclassStage")
        if session["phase"] != "done" or stage not in {"remediation", "open"}:
            raise HTTPException(409, "请先进入课后对话")
        student = {"role": "student", "text": body.text.strip(), "phase": "postclass-" + stage}
        history = [item for item in session["messages"]
                   if str(item.get("phase") or "").startswith("postclass-")]
        try:
            result = postclass_graph.invoke({
                "points": normalize(session["dialogue"])["points"],
                "messages": history + [student], "student_text": student["text"],
                "stage": stage, "assessment": {}, "transition": "continue", "reply": "",
            })
        except Exception as error:
            logger.exception("课后导师对话失败：session=%s", sid)
            raise HTTPException(503, "课后导师暂不可用，请稍后重试") from error
        assistant = {"role": "assistant", "text": result["reply"],
                     "phase": "postclass-" + result["stage"]}
        dialogue = dict(session["dialogue"], points=result["points"])
        messages = session["messages"] + [student, assistant]
        draft = dict(session, dialogue=dialogue, messages=messages,
                     postclassStage=result["stage"])
        updated_feedback = lesson_feedback(draft)
        commit(session, {"dialogue": dialogue, "messages": messages,
                         "postclassStage": result["stage"], "feedback": updated_feedback})
    return state(session)


if OUT.is_dir():
    app.mount("/app", StaticFiles(directory=OUT, html=True), name="student-frontend")


@app.get("/")
def index():
    if not OUT.is_dir():
        raise HTTPException(503, "请先构建前端：npm run build")
    return FileResponse(OUT / "index.html")
