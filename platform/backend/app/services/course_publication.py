"""Publication gates shared by enrollment and agent entry.

The teacher service owns publication state. Platform checks its own course
record for ownership and asks the teacher API for the current publication.
"""
import uuid

from fastapi import HTTPException
from sqlmodel import Session

from app.models import Course
from app.services.teacher_publication_client import (
    TeacherPublicationUnavailable,
    get_teacher_publication,
)


def latest_publication(
    session: Session, course_id: uuid.UUID
) -> dict[str, str | int] | None:
    """Resolve the identity included in student launch tokens."""
    course = session.get(Course, course_id)
    if course is None:
        return None
    try:
        return get_teacher_publication(course_id, course.owner_id)
    except TeacherPublicationUnavailable as error:
        raise HTTPException(503, "教师发布状态暂不可用，请稍后重试") from error


def require_published_course(session: Session, course_id: uuid.UUID) -> None:
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(409, "课程尚未发布，暂不开放选课")
    try:
        published = get_teacher_publication(course_id, course.owner_id) is not None
    except TeacherPublicationUnavailable as error:
        raise HTTPException(503, "教师发布状态暂不可用，请稍后重试") from error
    if not published:
        raise HTTPException(409, "课程尚未发布，暂不开放选课")
