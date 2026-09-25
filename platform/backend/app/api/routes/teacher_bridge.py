"""Authenticated bridge to the independent teacher service.

The teacher service asks this endpoint to validate each request. User supplied
teacher IDs are never used as an authorization decision.
"""
import hmac
import uuid
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import CurrentUser, SessionDep, TeacherUser
from app.core.config import settings
from app.models import Course
from app.api.routes.student_bridge import is_published_classroom
from app.services.browser_sessions import user_for_cookie
from app.services.course_access import get_accessible_course, get_owned_course

router = APIRouter(tags=["teacher-bridge"])

# API prefixes a teacher (not only an admin) may call on the teacher service.
# Each of them carries an explicit scope check (course or classroom ownership)
# before this list is consulted.
TEACHER_SCOPED_API_PREFIXES = {"course-space", "classes", "classroom", "classroom-media"}
# Unscoped API prefixes that stay reachable to any authenticated teacher role.
TEACHER_OPEN_API_PREFIXES = {"health", "server-providers", "access-code"}
# Exact capability probes needed by the hidden teacher settings page. Keep this
# narrow: opening the entire generate prefix would expose unrelated costly APIs.
TEACHER_OPEN_API_PATHS = {"/api/generate/tts"}


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
    source = session.execute(text("SELECT teacher_id,title,payload FROM teacher.mentra_courses WHERE id=:id"), {"id": str(body.course_id)}).first()
    if not source or source[0] != str(body.teacher_id):
        raise HTTPException(409, "Teacher course ownership mismatch")
    teacher = session.get(User, body.teacher_id)
    if not teacher or not teacher.is_active or (teacher.role != "teacher" and not teacher.is_superuser):
        raise HTTPException(403, "Invalid teacher")
    course = session.get(Course, body.course_id)
    if course and course.owner_id != body.teacher_id:
        raise HTTPException(409, "Course belongs to another teacher")
    if course:
        course.title = source[1]
        course.description = source[2].get("description")
    else:
        course = Course(id=body.course_id, owner_id=body.teacher_id, title=source[1], description=source[2].get("description"))
        session.add(course)
    session.flush()
    session.execute(text("INSERT INTO teacher_course_link(course_id,external_course_id) VALUES (:id,:external) ON CONFLICT (course_id) DO UPDATE SET external_course_id=EXCLUDED.external_course_id"), {"id": body.course_id, "external": str(body.course_id)})
    session.commit()
    session.refresh(course)
    return {"id": str(course.id)}


@router.post("/internal/teacher/authorize")
def authorize_teacher_request(body: TeacherAuthorization, session: SessionDep,
                              x_teacher_service_key: str | None = Header(default=None)):
    try:
        return _authorize_teacher_request(body, session, x_teacher_service_key)
    except HTTPException:
        raise
    except Exception as error:  # database unreachable: fail closed with a distinct 503
        raise HTTPException(503, "平台数据库暂不可用，请稍后重试") from error


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
    # Students may only read the published player belonging to a course in
    # which they are currently enrolled. All editing and generation routes
    # remain teacher-only below.
    if user.role == "student" and body.method in {"GET", "HEAD", "OPTIONS"}:
        classroom_id: str | None = None
        if parts[:1] in (["classroom-player"], ["classroom"]) and len(parts) > 1:
            classroom_id = parts[1]
        elif parts[:2] == ["api", "classroom-media"] and len(parts) > 2:
            classroom_id = parts[2]
        elif parts[:2] == ["api", "classroom"]:
            classroom_id = (parse_qs(split.query).get("id") or [None])[0]
        if classroom_id:
            course_id = classroom_course_id(session, classroom_id)
            if not course_id:
                raise HTTPException(403, "Classroom is not attached to a course")
            try:
                platform_course_id = uuid.UUID(course_id)
            except ValueError:
                # Legacy courses keep their nanoid in the teacher schema; the
                # platform UUID comes from the mapping table.
                link = session.execute(
                    text("SELECT course_id::text FROM teacher_course_link WHERE external_course_id=:external"),
                    {"external": course_id}).first()
                if not link:
                    raise HTTPException(403, "Classroom course is not available to students")
                platform_course_id = uuid.UUID(str(link[0]))
            enrolled = session.execute(
                text("SELECT 1 FROM enrollment WHERE course_id=:course AND student_id=:student"),
                {"course": platform_course_id, "student": user.id},
            ).first()
            if not enrolled or not is_published_classroom(
                    session, platform_course_id, classroom_id):
                raise HTTPException(403, "Student may only view an enrolled published classroom")
            return {"userId": str(user.id), "role": user.role, "isAdmin": False}
    if user.role != "teacher" and not user.is_superuser:
        raise HTTPException(403, "Teacher role required")
    course_id: str | None = None
    if parts[:2] == ["api", "course-space"] and len(parts) > 2:
        if parts[2] == "jobs" and len(parts) > 3:
            row = session.execute(text("SELECT course_id FROM teacher.mentra_artifact_jobs WHERE id=:id"), {"id": parts[3]}).first()
            if not row:
                raise HTTPException(404, "Task not found")
            course_id = row[0]
        elif parts[2:4] == ["knowledge-graph", "jobs"] and len(parts) > 4:
            row = session.execute(text("SELECT course_id FROM teacher.mentra_course_graph_jobs WHERE id=:id"), {"id": parts[4]}).first()
            if not row:
                raise HTTPException(404, "Task not found")
            course_id = row[0]
        else:
            course_id = parts[2]
    elif parts[:2] == ["api", "classes"] and len(parts) > 2:
        course_id = parts[2]
    elif parts[:2] == ["api", "classroom-media"] and len(parts) > 2:
        course_id = classroom_course_id(session, parts[2])
    elif parts[:2] == ["api", "classroom"]:
        # `GET /api/classroom?id=...` carries the classroom id in the query.
        query_id = (parse_qs(split.query).get("id") or [None])[0]
        if query_id:
            course_id = classroom_course_id(session, query_id)
    elif parts[:1] == ["course-space"] and len(parts) > 1:
        course_id = parts[1]
    elif parts[:1] in (["classroom-player"], ["classroom"]) and len(parts) > 1:
        course_id = classroom_course_id(session, parts[1])
    if course_id:
        row = session.execute(text("SELECT teacher_id FROM teacher.mentra_courses WHERE id=:id"), {"id": course_id}).first()
        if not row:
            raise HTTPException(404, "课程不存在或尚未同步到统一数据库")
        if row[0] != str(user.id) and not user.is_superuser:
            raise HTTPException(403, "无权访问该课程（课程属于其他教师）")
    # Legacy unscoped classroom/editing APIs have no complete owner model yet.
    # They remain admin-only until their ownership migration is complete.
    if (
        parts[:1] == ["api"]
        and parts[1:2]
        and parts[1] not in TEACHER_SCOPED_API_PREFIXES | TEACHER_OPEN_API_PREFIXES
        and split.path not in TEACHER_OPEN_API_PATHS
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


@router.get("/courses/{course_id}/published-content")
def published_content(course_id: uuid.UUID, session: SessionDep, user: CurrentUser):
    get_accessible_course(session, user, course_id)
    row = session.execute(text("SELECT p.payload FROM teacher.mentra_knowledge_packages p JOIN teacher_course_link l ON l.external_course_id=p.course_id WHERE l.course_id=:id AND p.status='published' ORDER BY p.version DESC LIMIT 1"), {"id": course_id}).first()
    # Reading a published knowledge package does not require a player. Keep
    # this separate from Classroom availability so students see real material
    # while the teacher is still preparing interactive courseware.
    return {"knowledgePackage": row[0] if row else None,
            "classroomAvailable": bool(_published_classroom(session, course_id))}


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

    user = session.get(User, uuid.UUID(x_platform_subject)) if x_platform_subject else None
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
