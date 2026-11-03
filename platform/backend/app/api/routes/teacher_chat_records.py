"""Teacher access to student-owned chat records via the student service."""

import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from sqlmodel import select

from app.api.deps import SessionDep, TeacherUser
from app.models import Course
from app.services.course_access import get_owned_course
from app.services import student_chat_records_client, teacher_lesson_titles_client

router = APIRouter(prefix="/teacher-chat-records", tags=["teacher-chat-records"])


def _enrolled_students(session: SessionDep, course_id: uuid.UUID, student_id: uuid.UUID | None = None) -> dict[str, str]:
    params = {"course": course_id}
    clause = ""
    if student_id is not None:
        params["student"] = student_id
        clause = " AND e.student_id = :student"
    rows = session.execute(text(
        'SELECT e.student_id::text, u.full_name, u.email FROM enrollment e '
        'JOIN "user" u ON u.id=e.student_id WHERE e.course_id=:course' + clause
    ), params).all()
    return {row[0]: row[1] or row[2] for row in rows}


@router.get("/courses")
def list_courses(session: SessionDep, user: TeacherUser) -> list[dict]:
    statement = select(Course).order_by(Course.title)
    if not user.is_superuser:
        statement = statement.where(Course.owner_id == user.id)
    return [{"id": str(course.id), "title": course.title} for course in session.exec(statement).all()]


@router.get("/courses/{course_id}/sessions")
def list_sessions(
    course_id: uuid.UUID, session: SessionDep, user: TeacherUser,
    student_id: uuid.UUID | None = None,
    limit: int = Query(default=300, ge=1, le=500),
) -> list[dict]:
    course = get_owned_course(session, user, course_id)
    students = _enrolled_students(session, course_id, student_id)
    if not students:
        return []
    try:
        rows = student_chat_records_client.get_chat_sessions(course_id, list(students), limit)
        titles = teacher_lesson_titles_client.get_lesson_titles(course_id, course.owner_id)
    except (student_chat_records_client.StudentChatUnavailable,
            teacher_lesson_titles_client.TeacherLessonTitlesUnavailable) as error:
        raise HTTPException(503, "Chat records unavailable") from error
    return [{
        **row,
        "student": students[row["studentId"]],
        "lesson": titles.get(str(row.get("lessonId"))) or row.get("lessonId")
        or (f"课堂 {row['classroomId']}" if row.get("classroomId") else "未记录课时"),
    } for row in rows if row.get("studentId") in students]


@router.get("/courses/{course_id}/sessions/{session_key}/messages")
def list_messages(
    course_id: uuid.UUID, session_key: str, session: SessionDep, user: TeacherUser,
    phase: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=1000, ge=1, le=5000), offset: int = Query(default=0, ge=0),
) -> list[dict]:
    get_owned_course(session, user, course_id)
    students = _enrolled_students(session, course_id)
    if not students:
        raise HTTPException(404, "未找到该学生会话")
    try:
        return student_chat_records_client.get_chat_messages(
            course_id, session_key, list(students), phase, limit, offset,
        )
    except student_chat_records_client.StudentChatMissing as error:
        raise HTTPException(404, "未找到该学生会话") from error
    except student_chat_records_client.StudentChatUnavailable as error:
        raise HTTPException(503, "Chat records unavailable") from error
