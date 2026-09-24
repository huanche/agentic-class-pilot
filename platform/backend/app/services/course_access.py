"""Course-level access checks, shared by routes and the agent-session service.

Moved out of ``app/api/routes/courses.py`` when the unified agent-session
service needed them too — importing route modules from services created an
import cycle. Behaviour is unchanged; the route module re-exports the
underscore aliases for its own call sites.
"""

import uuid

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import Course, Enrollment, User


def get_owned_course(session: Session, current_user: User, course_id: uuid.UUID) -> Course:
    """Write access: course owner, or teacher role plus ownership (superuser passes)."""
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if not current_user.is_superuser:
        if current_user.role != "teacher":
            raise HTTPException(status_code=403, detail="仅教师角色可以执行此操作")
        if course.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
    return course


def get_accessible_course(
    session: Session, current_user: User, course_id: uuid.UUID
) -> Course:
    """Read access: course owner, superuser, or an enrolled student."""
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if current_user.is_superuser or course.owner_id == current_user.id:
        return course
    enrolled = session.exec(
        select(Enrollment).where(
            Enrollment.course_id == course_id,
            Enrollment.student_id == current_user.id,
        )
    ).first()
    if not enrolled:
        raise HTTPException(status_code=403, detail="Not enrolled in this course")
    return course
