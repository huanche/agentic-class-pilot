"""Authenticated bridge to the independent teacher service.

The teacher service asks this endpoint to validate each request. User supplied
teacher IDs are never used as an authorization decision.
"""
import hmac
import logging
import time
import uuid
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import CurrentUser, SessionDep, TeacherUser
from app.core.config import settings
from app.models import Course
from app.api.routes.student_bridge import (_classroom_view, _content_from_teacher_snapshot,
    _published_classroom, _published_package_payload, ensure_published_knowledge_job)
from app.services.browser_sessions import user_for_cookie
from app.services.course_access import get_accessible_course, get_owned_course
from app.services.teacher_course_client import (
    TeacherCourseConflict,
    TeacherCourseUnavailable,
    provision_teacher_course,
)

router = APIRouter(tags=["teacher-bridge"])


class PublishedLessonPreparation(BaseModel):
    course_id: str
    artifact_id: str


@router.post("/internal/teacher/published-lesson-knowledge")
def enqueue_published_lesson_knowledge(
    body: PublishedLessonPreparation, session: SessionDep,
    x_teacher_service_key: str | None = Header(default=None),
):
    """Record the verified published video; student workers do the model work."""
    check_service_key(x_teacher_service_key)
    mode = settings.TEACHER_LEARNING_CONTENT_READ_MODE
    owner_row = None
    if mode != "legacy":
        owner_row = session.execute(
            text("SELECT owner_id::text FROM course WHERE id::text=:id"),
            {"id": str(body.course_id)}).first()

    def legacy_lesson():
        row = session.execute(text(
            "SELECT l.course_id, a.payload FROM teacher.mentra_course_artifacts a "
            "JOIN teacher_course_link l ON l.external_course_id=a.course_id "
            "WHERE a.id=:artifact AND a.course_id=:course AND a.status='published' "
            "AND a.payload->>'classVisible'='true' "
            "AND a.payload->>'classPublicationId' IS NOT NULL"
        ), {"artifact": body.artifact_id, "course": body.course_id}).first()
        if not row:
            raise HTTPException(409, "未找到已发布的教学视频")
        course_id, artifact = row
        placement = artifact.get("publicationPlacement") or {}
        lesson_id = placement.get("lessonId")
        classroom_id = artifact.get("classroomId")
        if not lesson_id or not classroom_id:
            raise HTTPException(409, "已发布内容不是课时教学视频")
        classroom = _classroom_view(session, classroom_id)
        return {"course_id": course_id, "lesson_id": lesson_id,
                "classroom_id": classroom_id, "classroom": classroom,
                "published_at": artifact.get("classPublishedAt")}

    if mode == "legacy":
        lesson = legacy_lesson()
    else:
        from app.services.teacher_learning_content_client import (
            TeacherLearningContentUnavailable, get_teacher_published_lesson,
        )

        def fetch():
            lesson, reason = get_teacher_published_lesson(
                body.artifact_id,
                uuid.UUID(str(owner_row[0])) if owner_row else None)
            if lesson is None:
                if reason == "classroom-missing":
                    raise HTTPException(404, "课堂不存在或尚未发布")
                if reason == "not-a-lesson-video":
                    raise HTTPException(409, "已发布内容不是课时教学视频")
                raise HTTPException(409, "未找到已发布的教学视频")
            return lesson

        if mode == "shadow":
            started = time.monotonic()
            try:
                proposed = fetch()
                legacy = legacy_lesson()
                if (proposed["lessonId"] != legacy["lesson_id"] or
                        proposed["classroomId"] != legacy["classroom_id"] or
                        proposed.get("publishedAt") != legacy["published_at"]):
                    logging.getLogger(__name__).warning(
                        "teacher_lesson_shadow_mismatch artifact=%s legacy=%s/%s api=%s/%s elapsed_ms=%d",
                        body.artifact_id, legacy["lesson_id"], legacy["classroom_id"],
                        proposed["lessonId"], proposed["classroomId"],
                        int((time.monotonic() - started) * 1000))
                else:
                    logging.getLogger(__name__).debug(
                        "teacher_lesson_shadow_match artifact=%s elapsed_ms=%d",
                        body.artifact_id, int((time.monotonic() - started) * 1000))
            except HTTPException:
                raise
            except Exception as error:  # noqa: BLE001 - shadow never changes the verdict
                logging.getLogger(__name__).warning(
                    "teacher_lesson_shadow_unavailable artifact=%s error=%s",
                    body.artifact_id, type(error).__name__)
            lesson = legacy_lesson()
        else:
            try:
                lesson = fetch()
            except HTTPException:
                raise
            except TeacherLearningContentUnavailable as error:
                raise HTTPException(503, "教师服务暂不可用，请稍后重试") from error
            platform_course = _platform_course_id(session, lesson["courseId"])
            if not platform_course:
                raise HTTPException(409, "未找到已发布的教学视频")
            lesson = {
                "course_id": uuid.UUID(platform_course),
                "lesson_id": lesson["lessonId"],
                "classroom": lesson["classroom"].to_dict(),
                "published_at": lesson.get("publishedAt"),
            }
    revision = ensure_published_knowledge_job(
        session, lesson["course_id"], lesson["lesson_id"],
        lesson["classroom"], lesson["published_at"])
    return {"lessonId": lesson["lesson_id"], "videoRevision": revision}

# API prefixes a teacher (not only an admin) may call on the teacher service.
# Each of them carries an explicit scope check (course or classroom ownership)
# before this list is consulted.
TEACHER_SCOPED_API_PREFIXES = {"course-space", "classes", "classroom", "classroom-media"}
# Unscoped API prefixes that stay reachable to any authenticated teacher role.
TEACHER_OPEN_API_PREFIXES = {"health", "server-providers", "access-code"}
# Exact capability probes needed by the hidden teacher settings page. Keep this
# narrow: opening the entire generate prefix would expose unrelated costly APIs.
TEACHER_OPEN_API_PATHS = {"/api/generate/tts"}

# Stateless text-generation steps used by the teacher preparation workflow.
# These consume caller-supplied outlines/content; they neither read nor mutate
# stored courses. Persisting/attaching the result still uses the scoped APIs.
# Permit only these exact POST endpoints, not the entire /api/generate prefix.
TEACHER_GENERATION_POST_PATHS = {
    "/api/generate/scene-outlines-stream",
    "/api/generate/scene-content",
    "/api/generate/scene-actions",
    "/api/generate/agent-profiles",
}


def teacher_write_origins() -> set[str]:
    """FRONTEND_HOST plus locally configured teacher service origins."""
    extra = {origin.strip() for origin in settings.TEACHER_ALLOWED_ORIGINS.split(",") if origin.strip()}
    return {settings.FRONTEND_HOST} | extra


class TeacherAuthorization(BaseModel):
    cookie: str | None = None
    path: str = Field(max_length=2048)
    method: str = Field(max_length=10)
    origin: str | None = None
    service_user_id: str | None = None


def check_service_key(value: str | None) -> None:
    if not settings.TEACHER_SERVICE_KEY or not hmac.compare_digest(value or "", settings.TEACHER_SERVICE_KEY):
        raise HTTPException(403, "Invalid service credentials")


def classroom_course_id(session: SessionDep, classroom_id: str) -> str | None:
    """Resolve a classroom to its course for ownership checks.

    Standalone classrooms (persisted before being attached to a course) have no
    course linkage yet; the caller treats them like unscoped resources.
    """
    row = session.execute(
        text("SELECT course_id FROM teacher.mentra_classrooms WHERE id=:id"), {"id": classroom_id}
    ).first()
    if not row:
        raise HTTPException(404, "Classroom not found")
    return row[0]


class TeacherCourseRegistration(BaseModel):
    course_id: uuid.UUID
    teacher_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


@router.post("/internal/teacher/courses")
def register_teacher_course(
    body: TeacherCourseRegistration,
    session: SessionDep,
    x_teacher_service_key: str | None = Header(default=None),
):
    """Create/update the platform management record for a teacher-created course.

    The teacher service remains the sole creation UI.  This endpoint only
    records the identical UUID in ``public.course`` for enrollment and roster
    management; it never creates a teacher workspace itself.
    """
    check_service_key(x_teacher_service_key)
    from app.models import User
    if settings.TEACHER_COURSE_REGISTRATION_MODE == "legacy":
        source = session.execute(text("SELECT teacher_id,title,payload FROM teacher.mentra_courses WHERE id=:id"), {"id": str(body.course_id)}).first()
        if not source or source[0] != str(body.teacher_id):
            raise HTTPException(409, "Teacher course ownership mismatch")
        title = source[1]
        description = source[2].get("description")
    else:
        # The service key authenticates the teacher service. Its registration
        # request is the course snapshot; platform owns only the enrollment copy.
        title = body.title
        description = body.description
    teacher = session.get(User, body.teacher_id)
    if not teacher or not teacher.is_active or (teacher.role != "teacher" and not teacher.is_superuser):
        raise HTTPException(403, "Invalid teacher")
    course = session.get(Course, body.course_id)
    if course and course.owner_id != body.teacher_id:
        raise HTTPException(409, "Course belongs to another teacher")
    if course:
        course.title = title
        if description is not None:
            # A registration without a description refreshes the title only:
            # teacher payloads may omit it, and wiping the platform copy would
            # make a retried registration destroy existing metadata.
            course.description = description
    else:
        course = Course(id=body.course_id, owner_id=body.teacher_id, title=title, description=description)
        session.add(course)
    session.flush()
    session.execute(text("INSERT INTO teacher_course_link(course_id,external_course_id) VALUES (:id,:external) ON CONFLICT (course_id) DO UPDATE SET external_course_id=EXCLUDED.external_course_id"), {"id": body.course_id, "external": str(body.course_id)})
    session.commit()
    session.refresh(course)
    return {"id": str(course.id)}


@router.get("/internal/teacher/course-alias/{course_id}")
def resolve_course_alias(
    course_id: str,
    session: SessionDep,
    x_teacher_service_key: str | None = Header(default=None),
):
    """Map a platform course UUID to the teacher service's own course id.

    Courses created before the integration keep their legacy nanoid inside the
    teacher service; only this mapping table links the two. The teacher service
    calls this when a UUID matches no local course so read paths can retry
    under the legacy id instead of failing with 404.
    """
    check_service_key(x_teacher_service_key)
    link = session.execute(
        text("SELECT course_id::text, external_course_id FROM teacher_course_link "
             "WHERE course_id::text=:pid OR external_course_id=:ext"),
        {"pid": course_id, "ext": course_id},
    ).first()
    if not link:
        raise HTTPException(404, "课程映射不存在")
    platform_id, legacy_id = str(link[0]), str(link[1])
    return {
        "platformCourseId": platform_id,
        "legacyCourseId": legacy_id if legacy_id != course_id else None,
    }


@router.post("/internal/teacher/authorize")
def authorize_teacher_request(body: TeacherAuthorization, session: SessionDep,
                              x_teacher_service_key: str | None = Header(default=None)):
    try:
        return _authorize_teacher_request(body, session, x_teacher_service_key)
    except HTTPException:
        raise
    except Exception as error:  # database unreachable: fail closed with a distinct 503
        raise HTTPException(503, "平台数据库暂不可用，请稍后重试") from error


def _shadow_verdict(name: str, legacy, api_callable) -> None:
    """Log a shadow comparison; the legacy verdict stays authoritative."""
    started = time.monotonic()
    try:
        proposed = api_callable()
    except Exception as error:  # noqa: BLE001 - shadow must never affect the verdict
        logging.getLogger(__name__).warning(
            "teacher_authz_shadow_unavailable check=%s error=%s elapsed_ms=%d",
            name, type(error).__name__, int((time.monotonic() - started) * 1000))
        return
    if proposed != legacy:
        logging.getLogger(__name__).warning(
            "teacher_authz_shadow_mismatch check=%s legacy=%s api=%s elapsed_ms=%d",
            name, legacy, proposed, int((time.monotonic() - started) * 1000))
    else:
        logging.getLogger(__name__).debug(
            "teacher_authz_shadow_match check=%s elapsed_ms=%d",
            name, int((time.monotonic() - started) * 1000))


def _platform_course_id(session: SessionDep, ref: str) -> str | None:
    """Resolve a platform UUID or legacy teacher id to the platform course UUID.

    Both sources are platform-owned tables: the course record and the
    registration mapping. Returns None when no platform course exists.
    """
    row = session.execute(
        text("SELECT id::text FROM course WHERE id::text=:ref"), {"ref": ref}).first()
    if row:
        return str(row[0])
    link = session.execute(
        text("SELECT course_id::text FROM teacher_course_link "
             "WHERE course_id::text=:ref OR external_course_id=:ref"),
        {"ref": ref}).first()
    return str(link[0]) if link else None


def _platform_course_owner(session: SessionDep, ref: str) -> str | None:
    """Resolve a teacher course reference to its owner in platform-owned data."""
    row = session.execute(
        text("SELECT c.owner_id::text FROM course c "
             "LEFT JOIN teacher_course_link l ON l.course_id=c.id "
             "WHERE c.id::text=:ref OR l.external_course_id=:ref LIMIT 1"),
        {"ref": ref},
    ).first()
    return str(row[0]) if row else None


def _job_course_id(session: SessionDep, job_id: str, kind: str, user, mode: str) -> str:
    """Resolve a background job to its owning course reference."""
    if mode == "legacy":
        table = ("teacher.mentra_course_graph_jobs" if kind == "graph"
                 else "teacher.mentra_artifact_jobs")
        row = session.execute(text(f"SELECT course_id FROM {table} WHERE id=:id"),
                              {"id": job_id}).first()
        if not row:
            raise HTTPException(404, "Task not found")
        return row[0]
    from app.services.teacher_authz_client import TeacherAuthzUnavailable, job_course_ref

    def fetch():
        try:
            return job_course_ref(job_id, kind, user.id)
        except LookupError as error:
            raise HTTPException(404, "Task not found") from error

    if mode == "shadow":
        table = ("teacher.mentra_course_graph_jobs" if kind == "graph"
                 else "teacher.mentra_artifact_jobs")
        row = session.execute(text(f"SELECT course_id FROM {table} WHERE id=:id"),
                              {"id": job_id}).first()
        legacy = row[0] if row else None
        _shadow_verdict(f"job_course:{kind}", legacy, lambda: fetch() if row else _noop_job(job_id, kind, user))
        if not row:
            raise HTTPException(404, "Task not found")
        return legacy
    try:
        return fetch()
    except HTTPException:
        raise
    except TeacherAuthzUnavailable as error:
        raise HTTPException(503, "教师服务暂不可用，请稍后重试") from error


def _noop_job(job_id, kind, user):
    from app.services.teacher_authz_client import TeacherAuthzUnavailable, job_course_ref
    try:
        return job_course_ref(job_id, kind, user.id)
    except Exception as error:  # noqa: BLE001
        raise RuntimeError("shadow probe failed") from error


def _student_material_allowed(session: SessionDep, course_ref: str, material_id: str,
                              user, mode: str) -> None:
    """Student may read only enrolled, explicitly published materials."""
    def legacy_verdict():
        row = session.execute(text(
            "SELECT c.payload FROM teacher.mentra_courses c "
            "JOIN teacher_course_link l ON l.external_course_id=c.id "
            "JOIN enrollment e ON e.course_id=l.course_id "
            "WHERE (c.id=:ref OR l.course_id::text=:ref) AND e.student_id=:uid AND c.status='active'"
        ), {"ref": course_ref, "uid": user.id}).first()
        material = next((m for m in (row[0].get("materials", []) if row else [])
                         if m.get("id") == material_id), None)
        return bool(material and material.get("classVisible") is True
                    and material.get("classPublicationId"))

    from app.services.teacher_authz_client import material_visibility

    def api_verdict():
        # Only ask the teacher service once enrolled; the enrollment check via
        # the platform's own tables already rejects unenrolled students.
        if not _enrolled(session, course_ref, user):
            return False
        return material_visibility(course_ref, material_id, user.id)

    if mode == "shadow":
        _shadow_verdict("student_material", legacy_verdict(), api_verdict)
        if not legacy_verdict():
            raise HTTPException(403, "Student may only read enrolled published materials")
        return
    verdict = legacy_verdict() if mode == "legacy" else api_verdict()
    if not verdict:
        raise HTTPException(403, "Student may only read enrolled published materials")


def _enrolled(session: SessionDep, course_ref: str, user) -> bool:
    """Enrollment check using only platform-owned tables."""
    platform_course_id = _platform_course_id(session, course_ref)
    if not platform_course_id:
        return False
    return bool(session.execute(
        text("SELECT 1 FROM enrollment WHERE course_id=:cid AND student_id=:uid"),
        {"cid": platform_course_id, "uid": user.id},
    ).first())


def _student_classroom_allowed(session: SessionDep, classroom_id: str, user,
                               mode: str) -> None:
    """Student may view only the current published classroom of an enrolled course."""
    def legacy_verdict():
        course_id = classroom_course_id(session, classroom_id)
        if not course_id:
            return (False, "Classroom is not attached to a course")
        try:
            platform_course_id = uuid.UUID(course_id)
        except ValueError:
            # Legacy courses keep their nanoid in the teacher schema; the
            # platform UUID comes from the mapping table.
            link = session.execute(
                text("SELECT course_id::text FROM teacher_course_link WHERE external_course_id=:external"),
                {"external": course_id}).first()
            if not link:
                return (False, "Classroom course is not available to students")
            platform_course_id = uuid.UUID(str(link[0]))
        enrolled = session.execute(
            text("SELECT 1 FROM enrollment WHERE course_id=:course AND student_id=:student"),
            {"course": platform_course_id, "student": user.id},
        ).first()
        published = session.execute(text(
            "SELECT 1 FROM teacher.mentra_course_artifacts a "
            "JOIN teacher_course_link l ON l.external_course_id=a.course_id "
            "JOIN teacher.mentra_courses c ON c.id=a.course_id "
            "WHERE l.course_id=:cid AND c.status='active' AND a.status='published' "
            "AND a.payload->>'classVisible'='true' AND a.payload->>'classPublicationId' IS NOT NULL "
            "AND a.payload->>'classroomId'=:rid"
        ), {"cid": platform_course_id, "rid": classroom_id}).first()
        return (bool(enrolled and published),
                "Student may only view an enrolled published classroom")

    from app.services.teacher_authz_client import classroom_visibility

    def api_verdict():
        course_ref, published = classroom_visibility(classroom_id, user.id)
        if not course_ref:
            # The legacy query raised 404 for a missing classroom row and 403
            # for a detached one; both now fail closed as 403.
            return (False, "Classroom is not attached to a course")
        try:
            platform_course_id = uuid.UUID(course_ref)
        except ValueError:
            link = session.execute(
                text("SELECT course_id::text FROM teacher_course_link WHERE external_course_id=:external"),
                {"external": course_ref}).first()
            if not link:
                return (False, "Classroom course is not available to students")
            platform_course_id = uuid.UUID(str(link[0]))
        enrolled = session.execute(
            text("SELECT 1 FROM enrollment WHERE course_id=:course AND student_id=:student"),
            {"course": platform_course_id, "student": user.id},
        ).first()
        return (bool(enrolled and published),
                "Student may only view an enrolled published classroom")

    if mode == "shadow":
        legacy = legacy_verdict()
        _shadow_verdict("student_classroom", legacy[0], lambda: api_verdict()[0])
        if not legacy[0]:
            raise HTTPException(403, legacy[1])
        return
    verdict = legacy_verdict() if mode == "legacy" else api_verdict()
    if not verdict[0]:
        raise HTTPException(403, verdict[1])


def _classroom_course_scoped(session: SessionDep, classroom_id: str, user,
                             mode: str) -> str | None:
    """Classroom→course mapping for teacher-side ownership checks.

    Returns the teacher course reference (None when detached, like the legacy
    lookup); raises 404 for a classroom that does not exist.
    """
    from app.services.teacher_authz_client import classroom_visibility

    def legacy_ref():
        row = session.execute(
            text("SELECT course_id FROM teacher.mentra_classrooms WHERE id=:id"),
            {"id": classroom_id}).first()
        return row[0] if row else None

    def api_ref():
        course_ref, _published = classroom_visibility(classroom_id, user.id)
        return course_ref

    if mode == "api":
        course_ref = api_ref()
        if not course_ref:
            raise HTTPException(404, "Classroom not found")
        return course_ref
    legacy = legacy_ref()
    if mode == "shadow":
        _shadow_verdict("classroom_course", legacy, api_ref)
    if not legacy:
        raise HTTPException(404, "Classroom not found")
    return legacy


def _teacher_course_owner_allowed(session: SessionDep, course_ref: str, user,
                                  mode: str) -> None:
    """Only the owning teacher (or a superuser) may touch a course.

    api mode reads ownership from the platform's own ``course.owner_id``
    recorded at registration; no teacher table is consulted.
    """
    if mode != "api":
        row = session.execute(
            text("SELECT teacher_id FROM teacher.mentra_courses WHERE id=:id"), {"id": course_ref}).first()
        if not row:
            # Platform entry points (建设概览, roster links) carry the platform
            # UUID; pre-integration courses live under their legacy teacher-agent
            # id, so resolve through the mapping table before rejecting.
            link = session.execute(
                text("SELECT external_course_id FROM teacher_course_link WHERE course_id::text=:pid"),
                {"pid": course_ref},
            ).first()
            if link and link[0] != course_ref:
                row = session.execute(
                    text("SELECT teacher_id FROM teacher.mentra_courses WHERE id=:id"), {"id": link[0]}
                ).first()
        legacy_owner = row[0] if row else None
        if mode == "shadow":
            _shadow_verdict("course_owner", legacy_owner,
                            lambda: _platform_course_owner(session, course_ref))
        if legacy_owner is None:
            raise HTTPException(404, "课程不存在或尚未同步到统一数据库")
        if legacy_owner != str(user.id) and not user.is_superuser:
            raise HTTPException(403, "无权访问该课程（课程属于其他教师）")
        return
    owner = _platform_course_owner(session, course_ref)
    if owner is None:
        raise HTTPException(404, "课程不存在或尚未同步到统一数据库")
    if owner != str(user.id) and not user.is_superuser:
        raise HTTPException(403, "无权访问该课程（课程属于其他教师）")


def _authorize_teacher_request(body: TeacherAuthorization, session: SessionDep,
                               x_teacher_service_key: str | None) -> dict:
    check_service_key(x_teacher_service_key)
    if body.service_user_id:
        from app.models import User
        try:
            user = session.get(User, uuid.UUID(body.service_user_id))
        except ValueError:
            user = None
        if not user or not user.is_active:
            raise HTTPException(401, "Invalid delegated user")
    else:
        user = user_for_cookie(session, body.cookie)
        if body.method not in {"GET", "HEAD", "OPTIONS"}:
            if body.origin not in teacher_write_origins():
                raise HTTPException(403, "Invalid request origin")
    split = urlsplit(body.path)
    parts = [unquote(p) for p in split.path.split('/') if p]
    authz_mode = settings.TEACHER_AUTHZ_READ_MODE
    # Students may only read the published player belonging to a course in
    # which they are currently enrolled. All editing and generation routes
    # remain teacher-only below.
    if user.role == "student" and body.method in {"GET", "HEAD", "OPTIONS"}:
        # A resource URL is readable only after explicit publication in an enrolled active course.
        if parts[:2] == ["api", "course-space"] and len(parts) == 5 and parts[3] == "materials":
            _student_material_allowed(session, parts[2], parts[4], user, authz_mode)
            return {"userId": str(user.id), "role": user.role, "isAdmin": False}
        classroom_id: str | None = None
        if parts[:1] in (["classroom-player"], ["classroom"]) and len(parts) > 1:
            classroom_id = parts[1]
        elif parts[:2] == ["api", "classroom-media"] and len(parts) > 2:
            classroom_id = parts[2]
        elif parts[:2] == ["api", "classroom"]:
            classroom_id = (parse_qs(split.query).get("id") or [None])[0]
        if classroom_id:
            _student_classroom_allowed(session, classroom_id, user, authz_mode)
            return {"userId": str(user.id), "role": user.role, "isAdmin": False}
    if user.role != "teacher" and not user.is_superuser:
        raise HTTPException(403, "Teacher role required")
    course_id: str | None = None
    if parts[:2] == ["api", "course-space"] and len(parts) > 2:
        if parts[2] == "jobs" and len(parts) > 3:
            course_id = _job_course_id(session, parts[3], "artifact", user, authz_mode)
        elif parts[2:4] == ["knowledge-graph", "jobs"] and len(parts) > 4:
            course_id = _job_course_id(session, parts[4], "graph", user, authz_mode)
        else:
            course_id = parts[2]
    elif parts[:2] == ["api", "classes"] and len(parts) > 2:
        course_id = parts[2]
    elif parts[:2] == ["api", "classroom-media"] and len(parts) > 2:
        course_id = _classroom_course_scoped(session, parts[2], user, authz_mode)
    elif parts[:2] == ["api", "classroom"]:
        # `GET /api/classroom?id=...` carries the classroom id in the query.
        query_id = (parse_qs(split.query).get("id") or [None])[0]
        if query_id:
            course_id = _classroom_course_scoped(session, query_id, user, authz_mode)
    elif parts[:1] == ["course-space"] and len(parts) > 1:
        course_id = parts[1]
    elif parts[:1] in (["classroom-player"], ["classroom"]) and len(parts) > 1:
        course_id = _classroom_course_scoped(session, parts[1], user, authz_mode)
    if course_id:
        _teacher_course_owner_allowed(session, course_id, user, authz_mode)
    # Legacy unscoped classroom/editing APIs have no complete owner model yet.
    # They remain admin-only until their ownership migration is complete.
    if (
        parts[:1] == ["api"]
        and parts[1:2]
        and parts[1] not in TEACHER_SCOPED_API_PREFIXES | TEACHER_OPEN_API_PREFIXES
        and split.path not in TEACHER_OPEN_API_PATHS
        and not (body.method == "POST" and split.path in TEACHER_GENERATION_POST_PATHS)
    ):
        if not user.is_superuser and not body.service_user_id:
            raise HTTPException(403, "This legacy operation requires an administrator")
    return {"userId": str(user.id), "role": user.role, "isAdmin": user.is_superuser}


@router.get("/platform/status")
async def platform_status(current_user: CurrentUser):
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.get(f"{settings.TEACHER_URL}/api/health")
            teacher_ready = response.status_code == 200
    except httpx.HTTPError:
        teacher_ready = False
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.get(f"{settings.STUDENT_URL}/api/session/health")
            student_ready = response.status_code == 200
    except httpx.HTTPError:
        student_ready = False
    return {"teacherReady": teacher_ready, "studentAgentReady": student_ready,
            "teacherUrl": settings.TEACHER_PUBLIC_URL, "studentUrl": settings.STUDENT_PUBLIC_URL}


@router.post("/courses/{course_id}/teacher-workspace")
async def open_teacher_workspace(course_id: uuid.UUID, session: SessionDep, user: TeacherUser):
    course = get_owned_course(session, user, course_id)
    # Serialize workspace provisioning per course across workers.
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:id))"), {"id": str(course_id)})
    row = session.execute(text("SELECT external_course_id FROM teacher_course_link WHERE course_id=:id"), {"id": course_id}).first()
    if settings.TEACHER_COURSE_PROVISION_MODE == "legacy":
        if row and session.execute(text("SELECT 1 FROM teacher.mentra_courses WHERE id=:id AND teacher_id=:owner"), {"id": row[0], "owner": str(course.owner_id)}).first():
            external_id = row[0]
        else:
            existing = session.execute(text("SELECT teacher_id FROM teacher.mentra_courses WHERE id=:id"), {"id": str(course.id)}).first()
            if existing and existing[0] != str(course.owner_id):
                raise HTTPException(409, "课程归属不一致，请联系管理员修复")
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                try:
                    response = await client.post(f"{settings.TEACHER_URL}/api/course-space", json={"id": str(course.id), "title": course.title, "description": course.description},
                        headers={"X-Platform-Service-Key": settings.TEACHER_SERVICE_KEY, "X-Platform-Subject": str(course.owner_id)})
                    response.raise_for_status()
                    external_id = response.json()["course"]["id"]
                except (httpx.HTTPError, KeyError, ValueError) as error:
                    session.rollback()
                    raise HTTPException(502, "教师服务暂不可用，请稍后重试") from error
            session.execute(text("INSERT INTO teacher_course_link(course_id,external_course_id) VALUES (:id,:external) ON CONFLICT (course_id) DO UPDATE SET external_course_id=EXCLUDED.external_course_id"), {"id": course_id, "external": external_id})
            session.commit()
        return {"url": f"{settings.TEACHER_PUBLIC_URL.rstrip('/')}/teacher-workspace?workspace={external_id}"}
    requested_id = str(row[0]) if row else str(course.id)
    try:
        external_id = await provision_teacher_course(
            requested_id, course.owner_id, course.title, course.description
        )
    except TeacherCourseConflict as error:
        session.rollback()
        raise HTTPException(409, "课程归属不一致，请联系管理员修复") from error
    except TeacherCourseUnavailable as error:
        session.rollback()
        raise HTTPException(502, "教师服务暂不可用，请稍后重试") from error
    if not row:
        session.execute(text("INSERT INTO teacher_course_link(course_id,external_course_id) VALUES (:id,:external) ON CONFLICT (course_id) DO UPDATE SET external_course_id=EXCLUDED.external_course_id"), {"id": course_id, "external": external_id})
        session.commit()
    return {"url": f"{settings.TEACHER_PUBLIC_URL.rstrip('/')}/teacher-workspace?workspace={external_id}"}


@router.get("/courses/{course_id}/published-content")
def published_content(course_id: uuid.UUID, session: SessionDep, user: CurrentUser):
    get_accessible_course(session, user, course_id)
    mode = settings.TEACHER_LEARNING_CONTENT_READ_MODE

    def legacy_response():
        row = session.execute(text("SELECT p.payload FROM teacher.mentra_knowledge_packages p JOIN teacher_course_link l ON l.external_course_id=p.course_id WHERE l.course_id=:id AND p.status='published' ORDER BY p.version DESC LIMIT 1"), {"id": course_id}).first()
        # Reading a published knowledge package does not require a player. Keep
        # this separate from Classroom availability so students see real material
        # while the teacher is still preparing interactive courseware.
        return {"knowledgePackage": _published_package_payload(session, course_id) if row else None,
                "classroomAvailable": bool(_published_classroom(session, course_id))}

    if mode == "legacy":
        return legacy_response()
    from app.services.teacher_learning_content_client import (
        TeacherLearningContentUnavailable, TeacherLearningContentMissing,
        get_teacher_published_content,
    )
    course = session.get(Course, course_id)
    if course is None:
        return {"knowledgePackage": None, "classroomAvailable": False}

    def api_response():
        snapshot = get_teacher_published_content(course_id, course.owner_id)
        if snapshot is None:
            return {"knowledgePackage": None, "classroomAvailable": False}
        # Playback grants are irrelevant to this summary; the snapshot helper
        # issues them anyway, so reuse it instead of duplicating projection.
        package, lessons = _content_from_teacher_snapshot(snapshot, user.id, course_id)
        return {"knowledgePackage": package, "classroomAvailable": bool(lessons)}

    if mode == "shadow":
        legacy = legacy_response()
        started = time.monotonic()
        try:
            proposed = api_response()
            legacy_key = ((legacy["knowledgePackage"] or {}).get("id"),
                          (legacy["knowledgePackage"] or {}).get("version"),
                          legacy["classroomAvailable"])
            proposed_key = ((proposed["knowledgePackage"] or {}).get("id"),
                            (proposed["knowledgePackage"] or {}).get("version"),
                            proposed["classroomAvailable"])
            if legacy_key != proposed_key:
                logging.getLogger(__name__).warning(
                    "published_content_shadow_mismatch course_id=%s legacy=%s api=%s elapsed_ms=%d",
                    course_id, legacy_key, proposed_key, int((time.monotonic() - started) * 1000))
        except Exception as error:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "published_content_shadow_unavailable course_id=%s error=%s",
                course_id, type(error).__name__)
        return legacy
    try:
        return api_response()
    except (TeacherLearningContentUnavailable, TeacherLearningContentMissing) as error:
        raise HTTPException(503, "教师服务暂不可用，请稍后重试") from error


def resolve_platform_course_id(session: SessionDep, course_id: str) -> uuid.UUID:
    """Platform UUID for a course reference; legacy nanoid ids resolve
    through teacher_course_link (the platform/teacher id bridge)."""
    try:
        return uuid.UUID(course_id)
    except ValueError:
        link = session.execute(
            text("SELECT course_id::text FROM teacher_course_link WHERE external_course_id=:e"),
            {"e": course_id}).first()
        if not link:
            raise HTTPException(404, "课程不存在")
        return uuid.UUID(str(link[0]))


@router.get("/internal/teacher/courses/{course_id}/enrollment")
def teacher_enrollment_code(course_id: str, session: SessionDep,
                            x_teacher_service_key: str | None = Header(default=None),
                            x_platform_subject: str | None = Header(default=None)):
    """A code is shared only by its authenticated teacher after publication."""
    check_service_key(x_teacher_service_key)
    from app.models import User
    from app.services.course_publication import require_published_course
    user = session.get(User, uuid.UUID(x_platform_subject)) if x_platform_subject else None
    if not user or not user.is_active:
        raise HTTPException(401, "教师身份无效")
    course_uuid = resolve_platform_course_id(session, course_id)
    course = get_owned_course(session, user, course_uuid)
    require_published_course(session, course_uuid)
    return {"courseId": str(course.id), "enrollCode": course.enroll_code}


@router.get("/internal/teacher/courses/{course_id}/members")
def teacher_course_members(
    course_id: str,
    session: SessionDep,
    x_teacher_service_key: str | None = Header(default=None),
    x_platform_subject: str | None = Header(default=None),
):
    """Trusted roster read for the independent teacher service.

    Enrollment is platform-owned. The teacher service receives a read-only
    projection rather than maintaining a second, eventually-stale roster.
    """
    check_service_key(x_teacher_service_key)
    from app.models import User

    try:
        user = session.get(User, uuid.UUID(x_platform_subject)) if x_platform_subject else None
    except (ValueError, TypeError):
        user = None
    if not user or not user.is_active:
        raise HTTPException(401, "教师身份无效")
    course_uuid = resolve_platform_course_id(session, course_id)
    get_owned_course(session, user, course_uuid)
    rows = session.execute(text("""
        SELECT u.id, u.full_name, u.email, e.created_at
        FROM enrollment e JOIN "user" u ON u.id=e.student_id
        WHERE e.course_id=:course_id
        ORDER BY e.created_at DESC
    """), {"course_id": course_uuid}).all()
    return {
        "courseId": str(course_uuid),
        "members": [
            {"studentId": str(row[0]), "name": row[1] or row[2],
             "email": row[2], "enrolledAt": row[3].isoformat() if row[3] else None}
            for row in rows
        ],
    }
