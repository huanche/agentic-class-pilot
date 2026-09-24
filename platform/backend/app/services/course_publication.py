"""Publication gates shared by enrollment and agent entry."""
import uuid
from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session

def require_published_course(session: Session, course_id: uuid.UUID) -> None:
    published = session.execute(text("""
        SELECT 1 FROM teacher.mentra_knowledge_packages p
        JOIN teacher_course_link l ON l.external_course_id=p.course_id
        JOIN teacher.mentra_courses c ON c.id=p.course_id
        WHERE l.course_id=:id AND p.status='published' AND c.status='active'
        LIMIT 1
    """), {"id": course_id}).first()
    if not published:
        raise HTTPException(409, "课程尚未发布，暂不开放选课")
