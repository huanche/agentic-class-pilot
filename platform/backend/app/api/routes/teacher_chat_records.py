"""Teacher-only, read-only access to persisted student and AI messages."""

import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from sqlmodel import select

from app.api.deps import SessionDep, TeacherUser
from app.models import Course
from app.services.course_access import get_owned_course

router = APIRouter(prefix="/teacher-chat-records", tags=["teacher-chat-records"])


def _lesson_titles(session: SessionDep, course_id: uuid.UUID) -> dict[str, str]:
    """Resolve a saved lesson id to its current teacher-facing title.

    Older sessions can lack ``lessonId``; callers use classroom id as a fallback.
    """
    row = session.execute(text("""
        SELECT c.payload FROM teacher.mentra_courses c
        JOIN teacher_course_link l ON l.external_course_id = c.id
        WHERE l.course_id = :course
        ORDER BY c.updated_at DESC
        LIMIT 1
    """), {"course": course_id}).first()
    if not row:
        return {}
    return {
        str(lesson.get("id")): str(lesson.get("title") or lesson.get("id"))
        for module in (row[0] or {}).get("modules", [])
        for lesson in module.get("lessons", [])
        if lesson.get("id")
    }


@router.get("/courses")
def list_courses(session: SessionDep, user: TeacherUser) -> list[dict]:
    """List only courses owned by the signed-in teacher (superusers see all)."""
    statement = select(Course).order_by(Course.title)
    if not user.is_superuser:
        statement = statement.where(Course.owner_id == user.id)
    return [{"id": str(course.id), "title": course.title} for course in session.exec(statement).all()]


@router.get("/courses/{course_id}/sessions")
def list_sessions(
    course_id: uuid.UUID,
    session: SessionDep,
    user: TeacherUser,
    student_id: uuid.UUID | None = None,
    limit: int = Query(default=300, ge=1, le=500),
) -> list[dict]:
    """List saved conversations for enrolled students in one owned course."""
    get_owned_course(session, user, course_id)
    params = {"course": str(course_id), "course_uuid": course_id, "limit": limit}
    student_filter = ""
    if student_id:
        student_filter = " AND s.user_id = :student_id"
        params["student_id"] = str(student_id)
    rows = session.execute(text(f"""
        SELECT s.session_key, s.user_id, s.classroom_id, s.started_at,
               s.last_active_at, s.ended_at,
               u.full_name, u.email,
               COALESCE(s.lesson_id, s.snapshot->>'lessonId', state.payload->>'lessonId') AS lesson_id,
               (SELECT count(*) FROM student.student_messages m
                WHERE m.session_key = s.session_key) AS message_count
        FROM student.student_sessions s
        JOIN enrollment e ON e.student_id::text = s.user_id
                         AND e.course_id = :course_uuid
        JOIN \"user\" u ON u.id = e.student_id
        LEFT JOIN LATERAL (
            SELECT event.payload FROM student.learning_events event
            WHERE event.session_key = s.session_key
              AND event.event_type = 'agent_state'
            ORDER BY event.created_at DESC, event.id DESC
            LIMIT 1
        ) state ON true
        WHERE s.course_id = :course AND s.revoked_at IS NULL{student_filter}
        ORDER BY s.last_active_at DESC, s.session_key DESC
        LIMIT :limit
    """), params).all()
    titles = _lesson_titles(session, course_id)
    return [{
        "sessionKey": row[0],
        "studentId": row[1],
        "student": row[6] or row[7],
        "classroomId": row[2],
        "startedAt": row[3].isoformat(),
        "lastActiveAt": row[4].isoformat(),
        "ended": row[5] is not None,
        "lessonId": row[8],
        "lesson": titles.get(str(row[8])) or row[8] or (f"课堂 {row[2]}" if row[2] else "未记录课时"),
        "messageCount": row[9],
    } for row in rows]


@router.get("/courses/{course_id}/sessions/{session_key}/messages")
def list_messages(
    course_id: uuid.UUID,
    session_key: str,
    session: SessionDep,
    user: TeacherUser,
    phase: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=1000, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """Return ordered messages for one enrolled student's owned-course session."""
    get_owned_course(session, user, course_id)
    allowed = session.execute(text("""
        SELECT 1
        FROM student.student_sessions s
        JOIN enrollment e ON e.student_id::text = s.user_id
                         AND e.course_id = :course_uuid
        WHERE s.session_key = :session_key AND s.course_id = :course AND s.revoked_at IS NULL
    """), {"session_key": session_key, "course": str(course_id),
           "course_uuid": course_id}).first()
    if not allowed:
        # Do not disclose whether an unrelated session key exists.
        raise HTTPException(404, "未找到该学生会话")
    params = {"session_key": session_key, "course": str(course_id),
              "phase": phase, "limit": limit, "offset": offset}
    phase_filter = " AND phase = :phase" if phase is not None else ""
    rows = session.execute(text(f"""
        SELECT seq, role, phase, content, created_at
        FROM student.student_messages
        WHERE session_key = :session_key AND course_id = :course{phase_filter}
        ORDER BY seq
        LIMIT :limit OFFSET :offset
    """), params).all()
    return [{"seq": row[0], "role": row[1], "phase": row[2],
             "content": row[3], "createdAt": row[4].isoformat()} for row in rows]
