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
import logging
import re
import secrets
import base64
import time
import uuid
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import Course, Enrollment
from app.services.browser_sessions import user_for_cookie
from app.services.course_access import get_accessible_course
from app.services.course_publication import require_published_course

router = APIRouter(tags=["student-bridge"])


def check_student_service_key(value: str | None) -> None:
    if not settings.STUDENT_SERVICE_KEY or not hmac.compare_digest(value or "", settings.STUDENT_SERVICE_KEY):
        raise HTTPException(403, "Invalid service credentials")


# --- launch tokens: HMAC-signed, self-contained, short-lived -----------------

def _token_signing_key() -> str:
    """凭证签名密钥：优先用独立的 STUDENT_TOKEN_SIGNING_KEY（问题6.3）。

    未配置时回落到通道密钥 STUDENT_SERVICE_KEY（过渡兼容，不中断现有部署），
    并记录告警——生产环境应显式配置独立签名密钥。"""
    if settings.STUDENT_TOKEN_SIGNING_KEY:
        return settings.STUDENT_TOKEN_SIGNING_KEY
    logging.getLogger(__name__).warning(
        "STUDENT_TOKEN_SIGNING_KEY 未配置，凭证签名回落使用通道密钥"
        "（建议在 .env 中配置独立签名密钥，实现通道认证与凭证签名分离）")
    return settings.STUDENT_SERVICE_KEY


def _launch_signature(payload_json: str) -> str:
    key = (_token_signing_key() or "").encode()
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


def verify_launch_token(token: str, *, refresh_session: bool = False) -> dict:
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
    # Previously issued launch tokens have no kind. A signed playback grant
    # must not be accepted as a student-workspace launch credential.
    if payload.get("kind") not in (None, "launch"):
        raise HTTPException(401, "Invalid launch token purpose")
    if not refresh_session and int(payload.get("exp", 0)) < time.time():
        raise HTTPException(401, "Launch token expired")
    return payload


# --- published-content resolution ---------------------------------------------

def _latest_publication(session: SessionDep, course_id: uuid.UUID) -> dict | None:
    from app.services.course_publication import latest_publication

    return latest_publication(session, course_id)


def _published_classroom(session: SessionDep, course_id: uuid.UUID) -> str | None:
    course = session.get(Course, course_id)
    if course is None:
        return None
    from app.services.teacher_classroom_client import (
        TeacherClassroomUnavailable, get_latest_classroom,
    )
    try:
        return get_latest_classroom(course_id, course.owner_id)
    except TeacherClassroomUnavailable as error:
        raise HTTPException(503, "教师课堂服务暂不可用，请稍后重试") from error


def _knowledge_points_from_markdown(content: str) -> list[dict]:
    """知识点工件（markdown）→ rubric 条目。纯函数，供单测共用。

    二级到六级标题都可承载知识点；有子标题的周次/章节是分组，
    只将末级标题登记为知识点，避免整周内容挤成一项。该标题自己的
    列表是应会要点，代码围栏内的示例忽略。剥除中文及阿拉伯序号，
    同标题只保留第一份；ID 按规范后的标题哈希，调整标题层级不改 ID。
    """
    sections: list[dict] = []
    stack: list[dict] = []
    fence = ""
    for line in (content or "").splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = ""
            continue
        if marker:
            fence = marker[1]
            continue
        heading = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$", line)
        if heading:
            level = len(heading[1])
            while stack and stack[-1]["level"] >= level:
                stack.pop()
            if stack:
                stack[-1]["has_children"] = True
            section = {"level": level, "title": heading[2], "lines": [], "has_children": False}
            sections.append(section)
            stack.append(section)
        elif stack:
            stack[-1]["lines"].append(line)

    points: list[dict] = []
    seen_titles: set[str] = set()
    for section in sections:
        if section["level"] < 2 or section["has_children"]:
            continue
        title = re.sub(r"\s+#+\s*$", "", section["title"]).strip()
        title = re.sub(r"^(?:[一二三四五六七八九十百]+、\s*|\d+(?:\.\d+)*[、.)．]?[ \t]+)", "", title).strip()
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        bullets = []
        for line in section["lines"]:
            m = re.match(r"^[-*][ \t]+(.+)$", line.strip())
            if m and m.group(1).strip():
                bullets.append(m.group(1).strip()[:200])
        points.append({
            "id": "kp-" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:10],
            "title": title,
            "expectedConcepts": bullets,
        })
    return points


def _knowledge_artifact_rubric(entries: list[dict], lesson_id: str | None) -> dict | None:
    """已发布条目里的「知识点」工件 → rubric（学生端知识点的唯一来源）。

    只取课时归属匹配 lesson_id 的文件，禁止跨课时或无归属兜底。
    没有 knowledge-points 工件 → None：学生端开场会明说「没有登记知识点」，
    按视频内容复习（2026-10-21 与用户对齐的决策：不做其他兜底）。
    """
    if not lesson_id:
        return None
    docs = [entry for entry in entries
            if entry.get("resourceType") == "knowledge-points"]
    if not docs:
        return None
    chosen = next((entry for entry in docs
                   if (entry.get("scope") or {}).get("lessonId") == lesson_id), None)
    if chosen is None:
        return None
    points = _knowledge_points_from_markdown(str(chosen.get("content") or ""))
    return {"knowledgePoints": points} if points else None


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
    require_published_course(session, uuid.UUID(course_id))


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
    lesson_id: str | None = None
    # Only the authenticated student service may refresh an already established
    # session. Signature and current enrollment are still checked below.
    refresh_session: bool = False


def ensure_published_knowledge_job(session: SessionDep, course_id: uuid.UUID,
                                   lesson_id: str, classroom: dict,
                                   published_at: int | None) -> str:
    """Idempotent publication job, also backfilling lessons published earlier."""
    scenes = classroom.get("scenes") or []
    revision = hashlib.sha256(json.dumps(
        [classroom["id"], published_at, scenes],
        sort_keys=True, ensure_ascii=False,
    ).encode()).hexdigest()
    from app.services.student_knowledge_client import (
        StudentKnowledgeUnavailable, enqueue_student_knowledge,
    )
    try:
        enqueue_student_knowledge(
            str(course_id), lesson_id, revision, classroom["id"], scenes,
        )
    except StudentKnowledgeUnavailable as error:
        raise HTTPException(503, "学生知识准备服务暂不可用，请稍后重试") from error
    return revision


def _content_from_teacher_snapshot(snapshot, user_id: uuid.UUID,
                                   course_id: uuid.UUID) -> tuple[dict, list[dict]]:
    """Project the teacher content snapshot into the legacy in-memory shapes.

    Returns (package_payload, published_lessons). The platform keeps the parts
    it owns: playback grants, player URLs and every enrollment decision.
    """
    from app.generated.platform_teacher_api.types import UNSET

    def scope_of(entry):
        if entry.scope is UNSET or entry.scope is None:
            return None
        return entry.scope.to_dict() if hasattr(entry.scope, "to_dict") else entry.scope

    def citation_of(citation):
        return citation.to_dict() if hasattr(citation, "to_dict") else citation

    package = {
        "id": snapshot.publication.publication_id,
        "version": int(snapshot.publication.version),
        "entries": [
            {
                "id": entry.id,
                "title": entry.title,
                "content": entry.content,
                "citations": [citation_of(citation) for citation in entry.citations]
                if entry.citations is not UNSET else [],
                "scope": scope_of(entry),
                "kind": str(entry.kind),
                "resourceType": entry.resource_type
                if entry.resource_type is not UNSET else None,
                "publicationId": entry.publication_id,
                **({"url": f"{settings.TEACHER_PUBLIC_URL.rstrip('/')}{entry.url}"}
                   if entry.url is not UNSET else {}),
            }
            for entry in snapshot.entries
        ],
    }

    teacher_base = settings.TEACHER_PUBLIC_URL.rstrip("/")
    lessons = []
    for item in snapshot.lessons:
        classroom = item.classroom
        classroom_view = {
            "id": classroom.id,
            "title": classroom.title,
            "scenes": [
                {
                    "id": scene.id,
                    "type": scene.type_,
                    "order": int(scene.order),
                    "title": scene.title,
                    "visibleText": list(scene.visible_text),
                    "actions": [
                        {
                            "id": action.id,
                            "type": action.type_ if action.type_ is not UNSET else "speech",
                            "text": action.text if action.text is not UNSET else None,
                        }
                        for action in scene.actions
                    ],
                }
                for scene in classroom.scenes
            ],
            "playerUrl": f"{teacher_base}/classroom-player/{classroom.id}",
        }
        classroom_view["playbackToken"] = _issue_playback_grant(
            user_id, course_id, classroom.id)
        lessons.append({
            "id": item.id,
            "title": item.title,
            "order": item.order,
            "week": item.week if item.week is not UNSET else None,
            "lessonNumber": item.lesson_number if item.lesson_number is not UNSET else None,
            "teachingHours": item.teaching_hours if item.teaching_hours is not UNSET else None,
            "publishedAt": item.published_at if item.published_at is not UNSET else None,
            "classroom": classroom_view,
        })
    return package, lessons


def _load_published_content(session: SessionDep, course_id: uuid.UUID,
                            user_id: uuid.UUID) -> tuple[dict | None, list[dict]]:
    """Read one teacher-owned published-content snapshot."""
    course = session.get(Course, course_id)
    if course is None:
        return None, []
    from app.services.teacher_learning_content_client import (
        TeacherLearningContentMissing, TeacherLearningContentUnavailable,
        get_teacher_published_content,
    )
    try:
        snapshot = get_teacher_published_content(course_id, course.owner_id)
        if snapshot is None:
            return None, []
        return _content_from_teacher_snapshot(snapshot, user_id, course_id)
    except TeacherLearningContentUnavailable as error:
        raise HTTPException(503, "教师学习内容服务暂不可用，请稍后重试") from error
    except TeacherLearningContentMissing as error:
        raise HTTPException(404, "课堂不存在或尚未发布") from error


@router.post("/internal/student/learning-context")
def student_learning_context(body: LearningContextRequest, session: SessionDep,
                             x_student_service_key: str | None = Header(default=None)):
    """Versioned learning context for a verified launch token.

    Returns published content only. The classroom is optional: text-only
    courses still start the student agent; the player is an add-on.
    """
    check_student_service_key(x_student_service_key)
    try:
        payload = verify_launch_token(body.launch_token, refresh_session=body.refresh_session)
        _resolve_launch_context(session, payload)  # enrollment re-check
        user_id = uuid.UUID(payload["uid"])
        course_id = uuid.UUID(payload["cid"])

        course = session.execute(
            text("SELECT title FROM public.course WHERE id = :id"), {"id": course_id}
        ).first()
        if not course:
            raise HTTPException(404, "课程不存在")
        package_payload, published_lessons = _load_published_content(
            session, course_id, user_id)
        if not package_payload:
            raise HTTPException(409, "课程尚未发布学习内容")
        # 目录只含摘要。未选课时不下发任何课堂正文、材料或知识点。
        lesson_catalog = [
            {**{key: lesson.get(key) for key in (
                "id", "title", "order", "week", "lessonNumber", "teachingHours")},
             "segmentCount": len(lesson["classroom"].get("scenes") or [])}
            for lesson in published_lessons
        ]
        selected = next((lesson for lesson in published_lessons if lesson["id"] == body.lesson_id), None)
        if body.lesson_id and selected is None:
            raise HTTPException(404, "所选课时不存在或尚未发布")
        if selected:
            ensure_published_knowledge_job(session, course_id, selected["id"],
                                           selected["classroom"], selected.get("publishedAt"))
        lessons = [selected] if selected else []
        classroom_id = selected["classroom"]["id"] if selected else None
        entries = []
        if selected:
            for entry in package_payload.get("entries") or []:
                scope = entry.get("scope") or {}
                if (scope.get("lessonId") == selected["id"] or
                        (scope.get("type") == "course" and not scope.get("lessonId")
                         and entry.get("resourceType") != "knowledge-points")):
                    entries.append(entry)
        knowledge_package = {
            "title": package_payload.get("title") or course[0],
            "summary": package_payload.get("summary") or "",
            "entries": entries,
        }
        # 知识点只来自教师发布的「知识点」文件（markdown：末级标题=知识点，
        # 其下列表=应会要点），以 rubric 结构化下发（学生端 evaluation 优先读
        # rubric）。没有工件 → 不下发 rubric，学生端开场明说「没有登记知识
        # 点」，按视频内容复习——不做场景大纲/知识图谱等其他兜底
        # 知识点与所选课时严格同源，目录请求不解析知识点。
        rubric = _knowledge_artifact_rubric(
            entries, selected["id"]) if selected else None
        if rubric:
            knowledge_package["rubric"] = rubric
        context = {
            "schemaVersion": SCHEMA_VERSION,
            "userId": str(user_id),
            "courseId": str(course_id),
            "courseTitle": course[0],
            "publication": {"id": package_payload.get("id"), "version": int(package_payload.get("version") or 1)},
            "knowledgePackage": knowledge_package,
            "selectedLessonId": selected["id"] if selected else None,
            "lessonCatalog": lesson_catalog,
            "classroom": selected["classroom"] if selected else None,
            "lessons": lessons,
            # 课程级grounding尚未接入学生端，也不能夹带其他课时正文。
            "grounding": {},
        }
        grant = _issue_playback_grant(user_id, course_id, classroom_id) if classroom_id else None
        if grant:
            context["classroom"]["playbackToken"] = grant
        return context
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(503, "平台数据库暂不可用，请稍后重试") from error


class ClassroomViewRequest(BaseModel):
    classroom_id: str = Field(min_length=1)


@router.post("/internal/student/classroom-view")
def student_classroom_view(body: ClassroomViewRequest, session: SessionDep,
                           x_student_service_key: str | None = Header(default=None)):
    """Old-session replay scenes via the teacher-owned classroom API."""
    check_student_service_key(x_student_service_key)
    from app.services.teacher_learning_content_client import (
        TeacherLearningContentUnavailable, get_teacher_classroom_view,
    )
    try:
        view = get_teacher_classroom_view(body.classroom_id)
        if view is None:
            return {"classroomId": body.classroom_id, "scenes": []}
        return {"classroomId": view.id, "scenes": view.to_dict()["scenes"]}
    except HTTPException:
        raise
    except TeacherLearningContentUnavailable as error:
        raise HTTPException(503, "教师学习内容服务暂不可用，请稍后重试") from error


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
    """Teacher-facing per-course learning data from the student service.

    Real persisted rows only — no fabricated aggregates. Students see their
    own rows; teachers see rows for their enrolled students."""
    course = get_accessible_course(session, user, course_id)
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

    from app.services.teacher_analytics_client import (
        TeacherAnalyticsUnavailable, get_teacher_publication_counts,
    )
    try:
        published_lessons = get_teacher_publication_counts(
            course_id, course.owner_id,
        )["distinctClassrooms"]
    except TeacherAnalyticsUnavailable as error:
        raise HTTPException(503, "教师发布统计暂不可用，请稍后重试") from error
    from app.services.student_analytics_client import (
        StudentAnalyticsUnavailable, get_course_learning_data,
    )
    try:
        data = get_course_learning_data(course_id, enrolled_ids)
    except StudentAnalyticsUnavailable as error:
        raise HTTPException(503, "学生学情服务暂不可用，请稍后重试") from error
    return {"publishedLessons": published_lessons, **data}


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
    event: str  # "started" | "ended" | "reset"


def _course_learning_progress(session, user_id: uuid.UUID, course_id: uuid.UUID) -> dict:
    """Real per-course classroom progress from the student service."""
    from app.services.teacher_analytics_client import (
        TeacherAnalyticsUnavailable, get_teacher_publication_counts,
    )
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(404, "课程不存在")
    try:
        total = get_teacher_publication_counts(
            course_id, course.owner_id,
        )["publishedArtifactsWithClassroom"]
    except TeacherAnalyticsUnavailable as error:
        raise HTTPException(503, "教师发布统计暂不可用，请稍后重试") from error
    from app.services.student_analytics_client import (
        StudentAnalyticsUnavailable, get_user_course_progress,
    )
    try:
        student_metrics = get_user_course_progress(course_id, user_id)
    except StudentAnalyticsUnavailable as error:
        raise HTTPException(503, "学生学情服务暂不可用，请稍后重试") from error
    learned = student_metrics["learnedLessons"]
    return {
        "totalLessons": total,
        **student_metrics,
        "percent": min(100, round(learned / total * 100)) if total else 0,
    }


def _teacher_course_owner(session, course_id: uuid.UUID) -> str | None:
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
    if body.event not in ("started", "ended", "reset"):
        raise HTTPException(400, "event 仅支持 started / ended / reset")
    from app.models import User
    student = session.get(User, body.user_id)
    if not student:
        raise HTTPException(404, "学生不存在")
    progress = _course_learning_progress(session, body.user_id, body.course_id)
    state = {
        "studentId": str(student.id),
        "name": student.full_name or student.email,
        "status": ("completed" if (progress["totalLessons"] and
                                   progress["learnedLessons"] >= progress["totalLessons"])
                   else "learning" if progress["sessionCount"] else "not-started"),
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
