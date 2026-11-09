"""Read-only internal dev console ("开发运维中心" data layer).

Answers developer questions, not table listings: is the system healthy
today, which courses/students need attention, and what exactly did a
student chat look like. Aggregates platform data with student-owned chat
records fetched through the student service, plus publication verdicts from
the teacher service. Everything is read-only and guarded by
``ObserverUser`` (role == "observer" or superuser); the student service is
only ever reached from this backend, never the browser. Responses carry no
ids beyond what the UI's own filters need — no hashes, tokens, or thread
internals.

Honesty rule: when a downstream service is unavailable the affected fields
degrade to ``None`` / "数据不可用" — never fabricated zeros.
"""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlmodel import Session

from app.api.deps import SessionDep, get_current_observer
from app.core.config import settings
from app.models import Course, Enrollment, User
from app.services import (
    student_analytics_client,
    student_chat_records_client,
    teacher_lesson_titles_client,
    teacher_publication_client,
)

# every endpoint is read-only and observer-guarded, so the boundary lives on
# the router; endpoints that don't need the user object just omit it
router = APIRouter(
    prefix="/dev-console",
    tags=["dev-console"],
    dependencies=[Depends(get_current_observer)],
)

# fan-out cap so an unfiltered "all courses" query can't stampede the
# student service on large deployments
MAX_COURSE_FANOUT = 50


def _resolve_course_targets(
    session: Session,
    course_id: uuid.UUID | None,
    student_id: uuid.UUID | None,
) -> list[tuple[Course, list[str]]]:
    """Map each course to the enrolled-student ids its chat query covers.

    course_id narrows to one course; student_id narrows to the courses that
    student is enrolled in (optionally within one course); neither fans out
    over all courses, capped at ``MAX_COURSE_FANOUT``.
    """
    if course_id is not None:
        course = session.get(Course, course_id)
        if not course:
            raise HTTPException(404, "课程不存在")
        statement = (
            select(Enrollment.student_id)
            .where(Enrollment.course_id == course.id)
        )
        if student_id is not None:
            statement = statement.where(Enrollment.student_id == student_id)
        student_ids = [
            str(row[0]) for row in session.execute(statement).all()
        ]
        return [(course, student_ids)] if student_ids else []

    course_statement = select(Course).order_by(Course.created_at.desc())
    if student_id is not None:
        course_statement = (
            select(Course)
            .join(Enrollment, Enrollment.course_id == Course.id)
            .where(Enrollment.student_id == student_id)
            .order_by(Course.created_at.desc())
        )
    # execute().scalars(), not session.exec(): SQLModel's exec assumes its
    # own typed selects and chokes on a plain entity select (KeyError: 'id')
    courses = session.execute(course_statement).scalars().all()[:MAX_COURSE_FANOUT]

    targets: list[tuple[Course, list[str]]] = []
    for course in courses:
        statement = select(Enrollment.student_id).where(
            Enrollment.course_id == course.id
        )
        if student_id is not None:
            statement = statement.where(Enrollment.student_id == student_id)
        student_ids = [str(row[0]) for row in session.execute(statement).all()]
        if student_ids:
            targets.append((course, student_ids))
    return targets


def _service_health() -> list[dict]:
    """Probe the two downstream services; platform itself is up if this runs."""
    results = []
    probes = [
        ("教师服务", f"{settings.TEACHER_URL}/api/health"),
        ("学生服务", f"{settings.STUDENT_URL}/api/session/health"),
    ]
    for name, url in probes:
        try:
            with httpx.Client(timeout=3, trust_env=False) as client:
                response = client.get(url)
            ok = response.status_code == 200
            detail = "" if ok else f"HTTP {response.status_code}"
        except httpx.HTTPError as error:
            ok = False
            detail = "连接失败"
            if isinstance(error, httpx.TimeoutException):
                detail = "超时"
        results.append({"name": name, "ok": ok, "detail": detail})
    return results


def _merged_chat_rows(
    session: Session,
    course_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    limit: int = 500,
) -> tuple[list[dict], list[str]]:
    """Fan out over courses and merge chat sessions with display names.

    Returns ``(rows, unavailable_course_titles)``; a course whose chat
    service call fails is skipped and reported by title.
    """
    merged: list[dict] = []
    unavailable: list[str] = []
    for course, student_ids in _resolve_course_targets(session, course_id, student_id):
        try:
            rows = student_chat_records_client.get_chat_sessions(
                course.id, student_ids, limit,
            )
        except student_chat_records_client.StudentChatUnavailable:
            unavailable.append(course.title)
            continue
        try:
            titles = teacher_lesson_titles_client.get_lesson_titles(
                course.id, course.owner_id,
            )
        except teacher_lesson_titles_client.TeacherLessonTitlesUnavailable:
            titles = {}
        students = {
            str(row[0]): (row[1], row[2])
            for row in session.execute(
                select(Enrollment.student_id, User.full_name, User.email)
                .join(User, User.id == Enrollment.student_id)
                .where(Enrollment.course_id == course.id)
            ).all()
        }
        for row in rows:
            row_student = row.get("studentId")
            owner_name, owner_email = students.get(row_student, (None, None))
            merged.append({
                **row,
                "courseId": str(course.id),
                "course": course.title,
                "student": owner_name or owner_email or row_student,
                "lesson": titles.get(str(row.get("lessonId")))
                or (f"课堂 {row['classroomId']}" if row.get("classroomId") else "未记录课时"),
            })
    merged.sort(key=lambda row: row.get("lastActiveAt") or "", reverse=True)
    return merged, unavailable


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# "在线"窗口:未过期会话且最近 N 分钟有请求(读会话时刷新 last_seen_at)
ONLINE_WINDOW_MINUTES = 5


def _online_counts(session: Session) -> dict:
    # 按人去重(一人多会话只算一次);超级管理员在用控制台,不算学生/教师在线
    rows = session.execute(text(
        'SELECT u.role, count(DISTINCT b.user_id) FROM browser_session b '
        'JOIN "user" u ON u.id = b.user_id '
        'WHERE b.expires_at > now() AND NOT u.is_superuser '
        'AND b.last_seen_at > now() - make_interval(mins => :mins) '
        'GROUP BY u.role'
    ), {"mins": ONLINE_WINDOW_MINUTES}).all()
    by_role = {row[0]: row[1] for row in rows}
    return {
        "students": by_role.get("student", 0),
        "teachers": by_role.get("teacher", 0),
        "windowMinutes": ONLINE_WINDOW_MINUTES,
    }


def _online_student_ids(session: Session) -> set[str]:
    rows = session.execute(text(
        'SELECT b.user_id FROM browser_session b '
        'JOIN "user" u ON u.id = b.user_id '
        "WHERE u.role = 'student' AND NOT u.is_superuser "
        'AND b.expires_at > now() '
        'AND b.last_seen_at > now() - make_interval(mins => :mins)'
    ), {"mins": ONLINE_WINDOW_MINUTES}).all()
    return {str(row[0]) for row in rows}


@router.get("/overview")
def overview(session: SessionDep) -> dict:
    """状态 + 待处理 + 趋势: the front page answers "is today OK?"."""
    users_by_role = dict(session.execute(
        select(User.role, func.count()).group_by(User.role)
    ).all())
    course_count = session.execute(
        select(func.count()).select_from(Course)
    ).scalar_one()
    enrollment_count = session.execute(
        select(func.count()).select_from(Enrollment)
    ).scalar_one()

    services = _service_health()
    now = datetime.now(UTC)

    # chat aggregate over all courses; degrades to None when student service is down
    chat: dict | None = None
    active_7d_ids: set[str] = set()
    active_24h_ids: set[str] = set()
    try:
        rows, unavailable = _merged_chat_rows(session)
        if not rows and unavailable:
            # every attempted course failed to read → the stats would be a
            # misleading all-zero; surface "unavailable" instead
            raise student_chat_records_client.StudentChatUnavailable(
                "all courses failed"
            )
        daily: dict[str, int] = {}
        total = 0
        last24h = 0
        for row in rows:
            total += 1
            student_id = str(row.get("studentId"))
            last_active = _parse_time(row.get("lastActiveAt"))
            if last_active:
                day = last_active.date().isoformat()
                daily[day] = daily.get(day, 0) + 1
                if now - last_active < timedelta(hours=24):
                    last24h += 1
                    active_24h_ids.add(student_id)
                if now - last_active < timedelta(days=7):
                    active_7d_ids.add(student_id)
        trend = [
            {"date": str((now - timedelta(days=offset)).date()),
             "count": daily.get(str((now - timedelta(days=offset)).date()), 0)}
            for offset in range(6, -1, -1)
        ]
        chat = {
            "total": total,
            "last24h": last24h,
            "activeStudents24h": len(active_24h_ids),
            "trend": trend,
        }
    except (student_chat_records_client.StudentChatUnavailable, HTTPException):
        chat = None

    # pending items — each derived from a checkable fact, never invented
    pending: list[dict] = []
    for service in services:
        if not service["ok"]:
            pending.append({
                "kind": "service",
                "severity": "critical",
                "text": f"{service['name']}不可用"
                + (f"({service['detail']})" if service["detail"] else ""),
                "count": None,
            })

    # enrolled-but-unpublished courses (teacher service down → unknown, skip)
    courses = session.execute(
        select(Course.id, Course.title).order_by(Course.created_at.desc())
    ).all()
    enrolled_counts = dict(session.execute(
        select(Enrollment.course_id, func.count())
        .group_by(Enrollment.course_id)
    ).all())
    unpublished_titles: list[str] = []
    for course_id, title in courses:
        if not enrolled_counts.get(course_id):
            continue
        try:
            verdict = teacher_publication_client.get_teacher_publication(
                course_id, session.get(Course, course_id).owner_id,
            )
        except teacher_publication_client.TeacherPublicationUnavailable:
            continue
        if verdict is None:
            unpublished_titles.append(title)
    if unpublished_titles:
        pending.append({
            "kind": "publication",
            "severity": "warning",
            "text": "已选课但未发布内容的课程:" + "、".join(unpublished_titles[:5])
            + ("等" if len(unpublished_titles) > 5 else ""),
            "count": len(unpublished_titles),
        })

    # students with enrollment but no 7-day chat activity (only when chat data exists)
    if chat is not None:
        enrolled_ids = {
            str(row[0]) for row in session.execute(
                select(func.distinct(Enrollment.student_id))
                .join(User, User.id == Enrollment.student_id)
                .where(User.role == "student")
                .where(User.is_superuser == False)  # noqa: E712
            ).all()
        }
        inactive = len(enrolled_ids - active_7d_ids)
        if inactive:
            pending.append({
                "kind": "inactive",
                "severity": "warning",
                "text": f"{inactive} 名学生近 7 天没有学习活动",
                "count": inactive,
            })

    return {
        "users": {
            "total": sum(users_by_role.values()),
            "teachers": users_by_role.get("teacher", 0),
            "students": users_by_role.get("student", 0),
        },
        "online": _online_counts(session),
        "courses": course_count,
        "enrollments": enrollment_count,
        "chat": chat,
        "services": services,
        "pending": pending,
    }


@router.get("/course-health")
def course_health(session: SessionDep) -> list[dict]:
    """课程健康度: publication + enrollment + learning activity + risk."""
    rows = session.execute(
        select(
            Course.id, Course.title, Course.created_at,
            User.full_name, User.email,
            func.count(Enrollment.id),
        )
        .join(User, User.id == Course.owner_id)
        .outerjoin(Enrollment, Enrollment.course_id == Course.id)
        .group_by(Course.id, User.full_name, User.email)
        .order_by(Course.created_at.desc())
    ).all()
    now = datetime.now(UTC)
    result: list[dict] = []
    for row in rows:
        course_id, title, created_at, full_name, email, students = row
        published: bool | None = None
        version: int | None = None
        publication_known = True
        try:
            verdict = teacher_publication_client.get_teacher_publication(
                course_id, session.get(Course, course_id).owner_id,
            )
            published = verdict is not None
            version = verdict["version"] if verdict else None
        except teacher_publication_client.TeacherPublicationUnavailable:
            publication_known = False

        session_count: int | None = None
        last_active: str | None = None
        active_7d: int | None = None
        try:
            student_ids = [
                str(r[0]) for r in session.execute(
                    select(Enrollment.student_id)
                    .where(Enrollment.course_id == course_id)
                ).all()
            ]
            if student_ids:
                learning = student_analytics_client.get_course_learning_data(
                    course_id, student_ids,
                )
                sessions = learning.get("sessions", [])
                session_count = len(sessions)
                latest: datetime | None = None
                active_ids: set[str] = set()
                for chat in sessions:
                    when = _parse_time(chat.get("lastActiveAt"))
                    if when:
                        latest = max(latest, when) if latest else when
                        if now - when < timedelta(days=7):
                            active_ids.add(str(chat.get("userId")))
                last_active = latest.isoformat() if latest else None
                active_7d = len(active_ids)
        except student_analytics_client.StudentAnalyticsUnavailable:
            pass

        if not publication_known:
            risk = "状态未知"
        elif students == 0:
            risk = "无学生"
        elif published is False:
            risk = "已选课未发布"
        elif session_count is None:
            risk = "数据不可用"
        elif session_count == 0:
            risk = "无会话"
        elif active_7d == 0:
            risk = "7天无活动"
        else:
            risk = "正常"
        result.append({
            "id": str(course_id),
            "title": title,
            "owner": full_name or email,
            "students": students,
            "published": published,
            "publicationVersion": version,
            "sessionCount": session_count,
            "lastActiveAt": last_active,
            "activeStudents7d": active_7d,
            "createdAt": created_at,
            "risk": risk,
        })
    return result


@router.get("/student-activity")
def student_activity(session: SessionDep) -> list[dict]:
    """学生学习活跃度: last activity, sessions, risk — across their courses."""
    students = session.execute(
        select(
            User.id, User.full_name, User.email, func.count(Enrollment.id),
        )
        .outerjoin(Enrollment, Enrollment.student_id == User.id)
        .where(User.role == "student")
        .where(User.is_superuser == False)  # noqa: E712 — 管理员不属于学生视图
        .group_by(User.id, User.full_name, User.email)
        .order_by(User.full_name)
    ).all()
    now = datetime.now(UTC)
    online_ids = _online_student_ids(session)
    last_by_student: dict[str, datetime] = {}
    count_by_student: dict[str, int] = {}
    chat_known = True
    try:
        for row in _merged_chat_rows(session)[0]:
            sid = str(row.get("studentId"))
            when = _parse_time(row.get("lastActiveAt"))
            count_by_student[sid] = count_by_student.get(sid, 0) + 1
            if when:
                current = last_by_student.get(sid)
                last_by_student[sid] = max(current, when) if current else when
    except (student_chat_records_client.StudentChatUnavailable, HTTPException):
        chat_known = False  # chat data missing → risk falls back to "数据不可用"

    result: list[dict] = []
    for student_id, full_name, email, courses in students:
        sid = str(student_id)
        online = sid in online_ids
        last = last_by_student.get(sid)
        if online:
            risk = "在线"
        elif courses == 0:
            risk = "无选课"
        elif not chat_known:
            risk = "数据不可用"
        elif last is None:
            risk = "从未学习"
        elif now - last > timedelta(days=7):
            risk = "7天未活跃"
        else:
            risk = "正常"
        result.append({
            "id": sid,
            "name": full_name or email,
            "email": email,
            "courses": courses,
            "sessionCount": count_by_student.get(sid, 0),
            "lastActiveAt": last.isoformat() if last else None,
            "risk": risk,
        })
    result.sort(key=lambda row: row.get("lastActiveAt") or "", reverse=True)
    return result


@router.get("/chat-sessions")
def list_chat_sessions(
    session: SessionDep,
    course_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=100),
    lesson: str | None = Query(default=None, max_length=100),
    ended: bool | None = None,
    active_days: int | None = Query(default=None, ge=1, le=365),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    """Chat sessions across courses, merged with student/course/lesson names.

    Each filter is a distinct field: ``q`` matches student/course metadata,
    ``lesson`` matches the lesson title, ``ended`` selects session state,
    ``active_days`` restricts to sessions active within the last N days.
    """
    merged, unavailable = _merged_chat_rows(
        session, course_id, student_id, limit,
    )
    if q:
        needle = q.strip().lower()
        if needle:
            merged = [
                row for row in merged
                if needle in (row.get("student") or "").lower()
                or needle in (row.get("course") or "").lower()
            ]
    if lesson:
        needle = lesson.strip().lower()
        if needle:
            merged = [
                row for row in merged
                if needle in (row.get("lesson") or "").lower()
            ]
    if ended is not None:
        merged = [row for row in merged if bool(row.get("ended")) == ended]
    if active_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=active_days)
        merged = [
            row for row in merged
            if (_parsed := _parse_time(row.get("lastActiveAt"))) and _parsed >= cutoff
        ]
    return {"sessions": merged, "unavailableCourses": unavailable}


@router.get("/courses")
def list_courses(session: SessionDep) -> list[dict]:
    """Light course list (no service fan-out) for filter dropdowns."""
    courses = session.execute(
        select(Course.id, Course.title).order_by(Course.created_at.desc())
    ).all()
    return [{"id": str(course_id), "title": title} for course_id, title in courses]


@router.get("/students")
def list_students(session: SessionDep) -> list[dict]:
    """Light student list (no service fan-out) for filter dropdowns."""
    students = session.execute(
        select(User.id, User.full_name, User.email)
        .where(User.role == "student")
        .order_by(User.full_name)
    ).all()
    return [{
        "id": str(student_id),
        "name": full_name or email,
    } for student_id, full_name, email in students]


@router.get("/courses/{course_id}/chat-sessions/{session_key}/messages")
def list_chat_messages(
    course_id: uuid.UUID,
    session_key: str,
    session: SessionDep,
    student_id: uuid.UUID | None = None,
    phase: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=1000, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(404, "课程不存在")
    statement = (
        select(Enrollment.student_id)
        .where(Enrollment.course_id == course.id)
    )
    if student_id is not None:
        statement = statement.where(Enrollment.student_id == student_id)
    student_ids = [str(row[0]) for row in session.execute(statement).all()]
    if not student_ids:
        raise HTTPException(404, "未找到该学生会话")
    try:
        return student_chat_records_client.get_chat_messages(
            course_id, session_key, student_ids, phase, limit, offset,
        )
    except student_chat_records_client.StudentChatMissing as error:
        raise HTTPException(404, "未找到该学生会话") from error
    except student_chat_records_client.StudentChatUnavailable as error:
        raise HTTPException(503, "聊天记录服务不可用") from error
