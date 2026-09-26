"""Student bridge: trusted entry into the independent student agent service.

Two surfaces:
- POST /api/v1/internal/student/authorize — the student agent validates each
  request (session cookie or launch token) against the platform.
- POST /api/v1/courses/{course_id}/student-workspace — an enrolled student of a
  published course receives a short-lived launch token plus the entry URL.
  Identity is carried inside the signed token; caller-supplied student ids are
  never trusted.
"""
import hashlib
import hmac
import json
import secrets
import base64
import time
import uuid
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import Enrollment
from app.services.browser_sessions import user_for_cookie
from app.services.course_access import get_accessible_course

router = APIRouter(tags=["student-bridge"])


def check_student_service_key(value: str | None) -> None:
    if not settings.STUDENT_SERVICE_KEY or not hmac.compare_digest(value or "", settings.STUDENT_SERVICE_KEY):
        raise HTTPException(403, "Invalid service credentials")


# --- launch tokens: HMAC-signed, self-contained, short-lived -----------------

def _launch_signature(payload_json: str) -> str:
    key = (settings.STUDENT_SERVICE_KEY or "").encode()
    return hmac.new(key, payload_json.encode(), hashlib.sha256).hexdigest()


def issue_launch_token(user_id: uuid.UUID, course_id: uuid.UUID, classroom_id: str,
                       publication: dict) -> str:
    payload = {
        "uid": str(user_id),
        "cid": str(course_id),
        "rid": classroom_id,
        "pub": publication,
        "exp": int(time.time()) + settings.STUDENT_LAUNCH_TOKEN_TTL_SECONDS,
        "nonce": secrets.token_urlsafe(12),
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    encoded = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    return f"{encoded}.{_launch_signature(payload_json)}"


def verify_launch_token(token: str) -> dict:
    """Validate signature and expiry; raise 401 on any mismatch."""
    encoded, _, signature = token.partition(".")
    if not signature:
        raise HTTPException(401, "Invalid launch token")
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        payload_json = base64.urlsafe_b64decode(padded).decode()
        payload = json.loads(payload_json)
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(401, "Invalid launch token") from error
    if not hmac.compare_digest(signature, _launch_signature(payload_json)):
        raise HTTPException(401, "Invalid launch token")
    if int(payload.get("exp", 0)) < time.time():
        raise HTTPException(401, "Launch token expired")
    return payload


# --- published-content resolution (read-only cross-schema queries) ------------

def _latest_publication(session: SessionDep, course_id: uuid.UUID) -> dict | None:
    row = session.execute(
        text("SELECT p.payload->>'version', p.payload->>'id' FROM teacher.mentra_knowledge_packages p "
             "JOIN teacher_course_link l ON l.external_course_id = p.course_id "
             "WHERE l.course_id=:id AND p.status='published' ORDER BY p.version DESC LIMIT 1"),
        {"id": course_id}).first()
    if not row:
        return None
    return {"publicationId": row[1], "version": int(row[0])}


def _published_classroom(session: SessionDep, course_id: uuid.UUID) -> str | None:
    row = session.execute(
        text("SELECT c.id FROM teacher.mentra_classrooms c "
             "JOIN teacher.mentra_course_artifacts a ON a.payload->>'classroomId' = c.id "
             "JOIN teacher_course_link l ON l.external_course_id = a.course_id "
             "WHERE l.course_id=:id AND a.payload->>'classPublicationId' IS NOT NULL "
             "ORDER BY (a.payload->>'classPublishedAt')::bigint DESC NULLS LAST LIMIT 1"),
        {"id": course_id}).first()
    return row[0] if row else None


class StudentAuthorization(BaseModel):
    cookie: str | None = None
    launch_token: str | None = None
    course_id: uuid.UUID | None = None
    classroom_id: str | None = None


def _resolve_launch_context(session: SessionDep, payload: dict) -> None:
    """Re-check enrollment + publication for a launch token at authorize time."""
    course_id = payload.get("cid")
    user_id = payload.get("uid")
    enrolled = session.execute(
        text("SELECT 1 FROM enrollment WHERE course_id=:c AND student_id=:u"),
        {"c": course_id, "u": user_id}).first()
    if not enrolled:
        raise HTTPException(403, "Launch token no longer matches an active enrollment")


@router.post("/internal/student/authorize")
def authorize_student_request(body: StudentAuthorization, session: SessionDep,
                              x_student_service_key: str | None = Header(default=None)):
    """Student-agent request validation: browser cookie or one-time launch context."""
    check_student_service_key(x_student_service_key)
    try:
        if body.launch_token:
            payload = verify_launch_token(body.launch_token)
            _resolve_launch_context(session, payload)
            return {"userId": payload["uid"], "courseId": payload["cid"],
                    "classroomId": payload.get("rid"), "publication": payload.get("pub"),
                    "source": "launch_token"}
        user = user_for_cookie(session, body.cookie)
        if user.role != "student" and not user.is_superuser:
            raise HTTPException(403, "Student role required")
        return {"userId": str(user.id), "source": "session"}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(503, "平台数据库暂不可用，请稍后重试") from error


@router.post("/courses/{course_id}/student-workspace")
def open_student_workspace(course_id: uuid.UUID, session: SessionDep, user: CurrentUser):
    """Trusted student entry: enrolled + published => short-lived launch URL."""
    if user.role == "teacher" and not user.is_superuser:
        raise HTTPException(403, "教师账号不能通过学生接口创建学习会话")
    get_accessible_course(session, user, course_id)
    if not user.is_superuser:
        enrolled = session.exec(
            select(Enrollment).where(
                Enrollment.course_id == course_id, Enrollment.student_id == user.id)
        ).first()
        if not enrolled:
            raise HTTPException(403, "尚未选课，无法进入学习")
    publication = _latest_publication(session, course_id)
    if not publication:
        raise HTTPException(409, "课程尚未发布，请等待教师发布后进入学习")
    # Classroom is optional: a published package alone supports text learning.
    # The player is an add-on; issue_launch_token tolerates classroom_id=None.
    classroom_id = _published_classroom(session, course_id)
    token = issue_launch_token(user.id, course_id, classroom_id or "none", publication)
    player_url = (f"{settings.TEACHER_PUBLIC_URL.rstrip('/')}/classroom-player/"
                  f"{quote(classroom_id)}") if classroom_id else None
    entry = f"{settings.STUDENT_PUBLIC_URL.rstrip('/')}/app?launch_token={quote(token)}"
    return {"url": entry, "playerUrl": player_url, "launchToken": token,
            "publication": publication, "classroomId": classroom_id}


# --- learning context (student agent data plane, schemaVersion 1) -------------

SCHEMA_VERSION = 1


class LearningContextRequest(BaseModel):
    launch_token: str


def _published_package_payload(session: SessionDep, course_id: uuid.UUID) -> dict | None:
    row = session.execute(
        text("SELECT p.payload FROM teacher.mentra_knowledge_packages p "
             "JOIN teacher_course_link l ON l.external_course_id = p.course_id "
             "WHERE l.course_id = :id AND p.status = 'published' "
             "ORDER BY p.version DESC LIMIT 1"),
        {"id": course_id}).first()
    return row[0] if row else None


def _classroom_view(session: SessionDep, classroom_id: str) -> dict:
    row = session.execute(
        text("SELECT stage, scenes FROM teacher.mentra_classrooms WHERE id = :id"),
        {"id": classroom_id}).first()
    if not row:
        raise HTTPException(404, "课堂不存在或尚未发布")
    scenes = []
    for scene in (row[1] or []):
        scenes.append({
            "id": scene.get("id"),
            "type": scene.get("type", "slide"),
            "order": int(scene.get("order") or 1),
            "title": scene.get("title", ""),
            # speech texts only: the student agent segments need narration;
            # canvas internals stay in the player's own data channel
            "actions": [
                {"id": action.get("id"), "type": action.get("type", "speech"),
                 "text": action.get("text")}
                for action in (scene.get("actions") or [])
                if isinstance(action, dict)
            ],
        })
    scenes.sort(key=lambda item: item["order"])
    return {
        "id": classroom_id,
        "title": (row[0] or {}).get("name", ""),
        "scenes": scenes,
        "playerUrl": f"{settings.TEACHER_PUBLIC_URL.rstrip('/')}/classroom-player/{classroom_id}",
    }


def _published_lessons(session: SessionDep, course_id: uuid.UUID,
                       user_id: uuid.UUID) -> list[dict]:
    """Return every published classroom for the course as a selectable lesson."""
    rows = session.execute(
        text("SELECT a.id, a.payload->>'title', a.payload->>'classroomId', "
             "a.payload->>'classPublishedAt' "
             "FROM teacher.mentra_course_artifacts a "
             "JOIN teacher_course_link l ON l.external_course_id = a.course_id "
             "WHERE l.course_id=:id AND a.status='published' "
             "AND a.payload->>'classPublicationId' IS NOT NULL "
             "AND a.payload->>'classroomId' IS NOT NULL "
             "ORDER BY (a.payload->>'classPublishedAt')::bigint ASC NULLS LAST, a.created_at ASC"),
        {"id": course_id}).all()
    lessons = []
    for order, row in enumerate(rows, start=1):
        classroom = _classroom_view(session, row[2])
        classroom["playbackToken"] = _issue_playback_grant(user_id, course_id, row[2])
        lessons.append({
            "id": f"lesson-{row[0]}",
            "title": row[1] or classroom["title"] or f"第 {order} 章",
            "order": order,
            "publishedAt": int(row[3]) if row[3] else None,
            "classroom": classroom,
        })
    return lessons


def _grounding_context(session: SessionDep, course_id: uuid.UUID) -> dict:
    """Course grounding for better student guidance: material excerpts and
    published-graph knowledge points. Queries join teacher_course_link so
    legacy nanoid courses resolve. Published graphs only; excerpts capped."""
    excerpts = []
    for row in session.execute(
        text("SELECT e.payload->'chunks' FROM teacher.mentra_material_extractions e "
             "JOIN teacher_course_link l ON l.external_course_id = e.course_id "
             "WHERE l.course_id = :id"), {"id": course_id}).fetchall():
        for chunk in (row[0] or [])[:6]:
            text_value = (chunk or {}).get("text", "")
            if text_value.strip():
                excerpts.append({"source": (chunk or {}).get("source") or "",
                                 "page": (chunk or {}).get("page"),
                                 "text": text_value[:600]})
            if len(excerpts) >= 12:
                break
        if len(excerpts) >= 12:
            break

    concepts = []
    graph_row = session.execute(
        text("SELECT g.version FROM teacher.mentra_course_graph_versions g "
             "JOIN teacher_course_link l ON l.external_course_id = g.course_id "
             "WHERE l.course_id = :id AND g.status = 'published' ORDER BY g.version DESC LIMIT 1"),
        {"id": course_id}).first()
    if graph_row:
        for node in session.execute(
            text("SELECT n.id, n.title, n.description FROM teacher.mentra_course_graph_nodes n "
                 "JOIN teacher_course_link l ON l.external_course_id = n.course_id "
                 "WHERE l.course_id = :id AND n.graph_version = :v AND n.node_type = 'knowledge-point'"),
            {"id": course_id, "v": graph_row[0]}).fetchall():
            concepts.append({"id": node[0], "title": node[1], "description": (node[2] or "")[:400]})
    return {"materialExcerpts": excerpts, "knowledgePoints": concepts}


@router.post("/internal/student/learning-context")
def student_learning_context(body: LearningContextRequest, session: SessionDep,
                             x_student_service_key: str | None = Header(default=None)):
    """Versioned learning context for a verified launch token.

    Returns published content only. The classroom is optional: text-only
    courses still start the student agent; the player is an add-on.
    """
    check_student_service_key(x_student_service_key)
    try:
        payload = verify_launch_token(body.launch_token)
        _resolve_launch_context(session, payload)  # enrollment re-check
        user_id = uuid.UUID(payload["uid"])
        course_id = uuid.UUID(payload["cid"])

        course = session.execute(
            text("SELECT title FROM public.course WHERE id = :id"), {"id": course_id}
        ).first()
        if not course:
            raise HTTPException(404, "课程不存在")
        package_payload = _published_package_payload(session, course_id)
        if not package_payload:
            raise HTTPException(409, "课程尚未发布学习内容")

        classroom_id = _published_classroom(session, course_id)
        lessons = _published_lessons(session, course_id, user_id)
        context = {
            "schemaVersion": SCHEMA_VERSION,
            "userId": str(user_id),
            "courseId": str(course_id),
            "courseTitle": course[0],
            "publication": {"id": package_payload.get("id"), "version": int(package_payload.get("version") or 1)},
            "knowledgePackage": {
                "title": package_payload.get("title") or course[0],
                "summary": package_payload.get("summary") or "",
                "entries": package_payload.get("entries") or [],
            },
            "classroom": _classroom_view(session, classroom_id) if classroom_id else None,
            "lessons": lessons,
            "grounding": _grounding_context(session, course_id),
        }
        grant = _issue_playback_grant(user_id, course_id, classroom_id) if classroom_id else None
        if grant:
            context["classroom"]["playbackToken"] = grant
        return context
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(503, "平台数据库暂不可用，请稍后重试") from error


def _issue_playback_grant(user_id: uuid.UUID, course_id: uuid.UUID, classroom_id: str) -> str:
    """Short-lived playback authorization bound to user+course+classroom.

    The teacher-side authorize hook validates it (stage 5); students cannot
    open other classrooms by editing URLs.
    """
    import time as _time
    payload = {
        "kind": "playback", "uid": str(user_id), "cid": str(course_id), "rid": classroom_id,
        "exp": int(_time.time()) + 1800, "nonce": secrets.token_urlsafe(9),
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    encoded = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    return f"{encoded}.{_launch_signature(payload_json)}"



@router.get("/courses/{course_id}/learning-data")
def course_learning_data(course_id: uuid.UUID, session: SessionDep, user: CurrentUser):
    """Teacher-facing per-course learning data from the student schema.

    Real persisted rows only — no fabricated aggregates. Students see their
    own rows; teachers see rows for their enrolled students."""
    get_accessible_course(session, user, course_id)
    if user.role == "student" and not user.is_superuser:
        learner = str(user.id)
    else:
        learner = None  # teacher: all enrolled students of this course
    enrolled_ids = [
        str(row[0]) for row in session.execute(
            text("SELECT student_id::text FROM enrollment WHERE course_id = :c"),
            {"c": course_id}).fetchall()]
    if learner:
        enrolled_ids = [i for i in enrolled_ids if i == learner]

    if not enrolled_ids:
        return {"sessions": [], "mastery": [], "events": []}

    id_list = tuple(enrolled_ids)
    placeholders = ", ".join(f":u{i}" for i in range(len(id_list)))
    params = {"course": course_id}
    for i, value in enumerate(id_list):
        params[f"u{i}"] = value

    published_row = session.execute(
        text("SELECT count(*) FROM teacher.mentra_course_artifacts a "
             "JOIN teacher_course_link l ON l.external_course_id = a.course_id "
             "WHERE l.course_id=:course AND a.status='published' "
             "AND a.payload->>'classroomId' IS NOT NULL"),
        {"course": course_id}).first()
    published_lessons = int(published_row[0]) if published_row else 0

    sessions = session.execute(
        text(f"SELECT session_key, user_id, publication_version, classroom_id, "
             f"started_at, last_active_at, ended_at IS NOT NULL AS ended "
             f"FROM student.student_sessions WHERE user_id IN ({placeholders}) "
             f"AND course_id = CAST(:course AS text) ORDER BY started_at DESC LIMIT 50"), params).fetchall()
    mastery = session.execute(
        text(f"SELECT user_id, knowledge_point_id, stars, status, evidence, updated_at "
             f"FROM student.knowledge_mastery WHERE user_id IN ({placeholders}) "
             f"AND course_id = CAST(:course AS text) ORDER BY updated_at DESC LIMIT 100"), params).fetchall()
    events = session.execute(
        text(f"SELECT event_type, count(*) FROM student.learning_events "
             f"WHERE user_id IN ({placeholders}) AND course_id = CAST(:course AS text) "
             f"GROUP BY event_type"), params).fetchall()

    return {
        "publishedLessons": published_lessons,
        "sessions": [{"sessionKey": r[0], "userId": r[1], "publicationVersion": r[2],
                      "classroomId": r[3], "startedAt": str(r[4]), "lastActiveAt": str(r[5]),
                      "ended": bool(r[6])} for r in sessions],
        "mastery": [{"userId": r[0], "knowledgePointId": r[1], "stars": r[2],
                     "status": r[3], "evidence": r[4], "updatedAt": str(r[5])} for r in mastery],
        "eventSummary": {r[0]: r[1] for r in events},
    }


@router.get("/student/status")
async def student_status(current_user: CurrentUser):
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.get(f"{settings.STUDENT_URL}/api/session/health")
            ready = response.status_code == 200
    except httpx.HTTPError:
        ready = False
    return {"studentAgentReady": ready, "studentUrl": settings.STUDENT_PUBLIC_URL}


# --- learning progress sync (student agent → platform → teacher service) ----
#
# 学生端每节课开始/结束时把事件报到这里（service-key 认证）。平台侧据此：
# 1. 计算该生在该课程的真实课堂进度（已学课时 / 已发布课时，全部基于
#    student.student_sessions 落库数据，不造数）；
# 2. 尽力推送一份学生状态到教师服务已有的
#    PUT /api/classes/{course_id}/students，授课管理的「学生与学习状态」
#    页面即会同步更新。推送失败不影响课堂，只留痕。


class LearningProgressReport(BaseModel):
    user_id: uuid.UUID
    course_id: uuid.UUID
    session_key: str | None = None
    classroom_id: str | None = None
    event: str  # "started" | "ended"


def _course_learning_progress(session, user_id: uuid.UUID, course_id: uuid.UUID) -> dict:
    """Real per-course classroom progress from the student schema only."""
    total_row = session.execute(
        text("SELECT count(*) FROM teacher.mentra_course_artifacts a "
             "JOIN teacher_course_link l ON l.external_course_id = a.course_id "
             "WHERE l.course_id=:id AND a.status='published' "
             "AND a.payload->>'classroomId' IS NOT NULL"),
        {"id": str(course_id)}).first()
    total = int(total_row[0]) if total_row else 0
    learned_row = session.execute(
        text("SELECT count(DISTINCT classroom_id), max(last_active_at), count(*) "
             "FROM student.student_sessions "
             "WHERE user_id=:u AND course_id=:c"),
        {"u": str(user_id), "c": str(course_id)}).first()
    learned = int(learned_row[0]) if learned_row and learned_row[0] else 0
    last_active = learned_row[1] if learned_row else None
    session_count = int(learned_row[2]) if learned_row else 0
    ended_row = session.execute(
        text("SELECT count(*) FROM student.student_sessions "
             "WHERE user_id=:u AND course_id=:c AND ended_at IS NOT NULL"),
        {"u": str(user_id), "c": str(course_id)}).first()
    ended = int(ended_row[0]) if ended_row else 0
    stars_row = session.execute(
        text("SELECT coalesce(sum(stars),0) FROM student.knowledge_mastery "
             "WHERE user_id=:u AND course_id=:c"),
        {"u": str(user_id), "c": str(course_id)}).first()
    stars = int(stars_row[0]) if stars_row else 0
    percent = min(100, round(learned / total * 100)) if total else 0
    return {
        "totalLessons": total,
        "learnedLessons": learned,
        "sessionCount": session_count,
        "endedSessions": ended,
        "lastActiveAt": str(last_active) if last_active else None,
        "stars": stars,
        "percent": percent,
    }


def _teacher_course_owner(session, course_id: uuid.UUID) -> str | None:
    row = session.execute(
        text("SELECT teacher_id FROM teacher.mentra_courses WHERE id=:id"),
        {"id": str(course_id)}).first()
    if row:
        return str(row[0])
    row = session.execute(
        text("SELECT owner_id FROM course WHERE id=:id"),
        {"id": str(course_id)}).first()
    return str(row[0]) if row else None


async def _push_student_state_to_teacher(session, course_id: uuid.UUID,
                                         state: dict) -> bool:
    """Best-effort: update 授课管理's 学生与学习状态 via the teacher service."""
    owner = _teacher_course_owner(session, course_id)
    headers = {
        "x-platform-service-key": settings.TEACHER_SERVICE_KEY,
        "x-platform-subject": owner or "",
    }
    candidates = [str(course_id)]
    link = session.execute(
        text("SELECT external_course_id FROM teacher_course_link WHERE course_id=:id"),
        {"id": str(course_id)}).first()
    if link and str(link[0]) not in candidates:
        candidates.append(str(link[0]))
    base = settings.TEACHER_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
        for course_ref in candidates:
            try:
                response = await client.put(
                    f"{base}/api/classes/{course_ref}/students",
                    json=state, headers=headers)
                if response.status_code < 300:
                    return True
                print(f"[learning-progress] 推送教师服务失败 "
                      f"course={course_ref} HTTP {response.status_code}: "
                      f"{response.text[:120]}")
            except httpx.HTTPError as error:
                print(f"[learning-progress] 推送教师服务异常 "
                      f"course={course_ref}: {type(error).__name__}: {error}")
    return False


@router.post("/internal/student/learning-progress")
async def report_learning_progress(body: LearningProgressReport,
                                   session: SessionDep,
                                   x_student_service_key: str | None = Header(default=None)):
    """学生端上报课堂进度事件；平台计算真实进度并同步到教师端授课管理。"""
    check_student_service_key(x_student_service_key)
    if body.event not in ("started", "ended"):
        raise HTTPException(400, "event 仅支持 started / ended")
    from app.models import User
    student = session.get(User, body.user_id)
    if not student:
        raise HTTPException(404, "学生不存在")
    progress = _course_learning_progress(session, body.user_id, body.course_id)
    state = {
        "studentId": str(student.id),
        "name": student.full_name or student.email,
        "status": "completed" if (progress["totalLessons"] and
                                  progress["learnedLessons"] >= progress["totalLessons"]) else "learning",
        "progress": progress["percent"],
        "completedResourceIds": [],
        "lastActiveAt": int(time.time() * 1000),
        # 学情明细：教师端镜像更新后，授课管理卡片会直接渲染这些字段
        "learnedLessons": progress["learnedLessons"],
        "totalLessons": progress["totalLessons"],
        "sessionCount": progress["sessionCount"],
        "endedCount": progress["endedSessions"],
        "stars": progress["stars"],
    }
    pushed = await _push_student_state_to_teacher(session, body.course_id, state)
    return {"ok": True, "progress": progress, "pushedToTeacher": pushed}


@router.get("/users/me/learning-summary")
def my_learning_summary(session: SessionDep, user: CurrentUser):
    """学生「我的课程」用的课堂学习概览（全部来自 student schema 落库数据）。"""
    rows = session.execute(
        text("SELECT c.id::text, c.title FROM enrollment e "
             "JOIN course c ON c.id = e.course_id "
             "WHERE e.student_id=:u ORDER BY c.title"),
        {"u": str(user.id)}).all()
    courses = []
    for course_id, title in rows:
        progress = _course_learning_progress(session, user.id, uuid.UUID(course_id))
        progress.update({"courseId": course_id, "courseTitle": title})
        courses.append(progress)
    return {"courses": courses}
