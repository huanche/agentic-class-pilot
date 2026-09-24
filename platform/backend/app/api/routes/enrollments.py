import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Chapter,
    ChapterProgress,
    Course,
    EnrollByCode,
    EnrolledCoursePublic,
    EnrolledCoursesPublic,
    Enrollment,
    Message,
)

router = APIRouter(prefix="/enrollments", tags=["enrollments"])


@router.post("/join", response_model=EnrolledCoursePublic)
def join_course(
    *, session: SessionDep, current_user: CurrentUser, body: EnrollByCode
) -> Any:
    """Join a course with its enroll code."""
    if current_user.role != "student" and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only student accounts can join a course")
    code = body.code.strip().upper()
    course = session.exec(select(Course).where(Course.enroll_code == code)).first()
    if not course:
        raise HTTPException(status_code=404, detail="选课码无效")
    if course.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能加入自己创建的课程")
    existing = session.exec(
        select(Enrollment).where(
            Enrollment.course_id == course.id,
            Enrollment.student_id == current_user.id,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="你已加入该课程")
    from app.services.course_publication import require_published_course
    require_published_course(session, course.id)
    enrollment = Enrollment(course_id=course.id, student_id=current_user.id)
    session.add(enrollment)
    session.commit()
    return EnrolledCoursePublic.model_validate(course)


@router.get("/my-courses", response_model=EnrolledCoursesPublic)
def read_my_courses(session: SessionDep, current_user: CurrentUser) -> Any:
    """Courses the current student has joined, with chapter progress."""
    enrollments = session.exec(
        select(Enrollment).where(Enrollment.student_id == current_user.id)
    ).all()
    result: list[EnrolledCoursePublic] = []
    for enrollment in enrollments:
        course = session.get(Course, enrollment.course_id)
        if not course:
            continue
        total = session.exec(
            select(func.count())
            .select_from(Chapter)
            .where(Chapter.course_id == course.id)
        ).one()
        completed = session.exec(
            select(func.count())
            .select_from(ChapterProgress)
            .join(Chapter, ChapterProgress.chapter_id == Chapter.id)  # type: ignore
            .where(
                Chapter.course_id == course.id,
                ChapterProgress.student_id == current_user.id,
            )
        ).one()
        result.append(
            EnrolledCoursePublic.model_validate(
                course,
                update={
                    "total_chapters": total,
                    "completed_chapters": completed,
                },
            )
        )
    return EnrolledCoursesPublic(data=result, count=len(result))


@router.delete("/{course_id}")
def leave_course(
    session: SessionDep, current_user: CurrentUser, course_id: uuid.UUID
) -> Message:
    enrollment = session.exec(
        select(Enrollment).where(
            Enrollment.course_id == course_id,
            Enrollment.student_id == current_user.id,
        )
    ).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="未加入该课程")
    session.delete(enrollment)
    session.commit()
    return Message(message="已退出课程")
