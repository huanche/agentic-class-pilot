"""Publication gates shared by enrollment and agent entry."""
import logging
import uuid

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.models import Course
from app.services.teacher_publication_client import (
    TeacherPublicationUnavailable,
    get_teacher_publication,
)

log = logging.getLogger(__name__)


def _legacy_publication(session: Session, course_id: uuid.UUID) -> bool:
    return bool(session.execute(text("""
        SELECT 1 FROM teacher.mentra_knowledge_packages p
        JOIN teacher_course_link l ON l.external_course_id=p.course_id
        JOIN teacher.mentra_courses c ON c.id=p.course_id
        WHERE l.course_id=:id AND p.status='published' AND c.status='active'
        LIMIT 1
    """), {"id": course_id}).first())


def _legacy_latest_publication(
    session: Session, course_id: uuid.UUID
) -> dict[str, str | int] | None:
    row = session.execute(text(
        "SELECT p.payload->>'version', p.payload->>'id' "
        "FROM teacher.mentra_knowledge_packages p "
        "JOIN teacher_course_link l ON l.external_course_id=p.course_id "
        "JOIN teacher.mentra_courses c ON c.id=p.course_id AND c.status='active' "
        "WHERE l.course_id=:id AND p.status='published' "
        "ORDER BY p.version DESC LIMIT 1"
    ), {"id": course_id}).first()
    return {"publicationId": row[1], "version": int(row[0])} if row else None


def latest_publication(
    session: Session, course_id: uuid.UUID
) -> dict[str, str | int] | None:
    """Resolve the identity included in student launch tokens."""
    mode = settings.TEACHER_PUBLICATION_READ_MODE
    if mode == "legacy":
        return _legacy_latest_publication(session, course_id)
    course = session.get(Course, course_id)
    if course is None:
        return None
    if mode == "shadow":
        existing = _legacy_latest_publication(session, course_id)
        try:
            proposed = get_teacher_publication(course_id, course.owner_id)
            if proposed != existing:
                log.warning("Teacher publication identity differs from legacy query")
        except TeacherPublicationUnavailable:
            log.warning("Teacher publication identity shadow comparison unavailable")
        return existing
    try:
        return get_teacher_publication(course_id, course.owner_id)
    except TeacherPublicationUnavailable as error:
        raise HTTPException(503, "教师发布状态暂不可用，请稍后重试") from error

def require_published_course(session: Session, course_id: uuid.UUID) -> None:
    mode = settings.TEACHER_PUBLICATION_READ_MODE
    if mode == "legacy":
        published = _legacy_publication(session, course_id)
    else:
        course = session.get(Course, course_id)
        if course is None:
            raise HTTPException(409, "课程尚未发布，暂不开放选课")
        if mode == "shadow":
            published = _legacy_publication(session, course_id)
            try:
                proposed = get_teacher_publication(course_id, course.owner_id) is not None
                if proposed != published:
                    log.warning("Teacher publication shadow verdict differs from legacy query")
            except TeacherPublicationUnavailable:
                log.warning("Teacher publication shadow comparison unavailable")
        else:
            try:
                published = get_teacher_publication(course_id, course.owner_id) is not None
            except TeacherPublicationUnavailable as error:
                raise HTTPException(503, "教师发布状态暂不可用，请稍后重试") from error
    if not published:
        raise HTTPException(409, "课程尚未发布，暂不开放选课")
