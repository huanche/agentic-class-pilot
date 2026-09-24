import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep, TeacherUser
from app.models import (
    Chapter,
    ChapterCreate,
    ChapterProgress,
    ChapterPublic,
    ChaptersPublic,
    ChapterUpdate,
    Course,
    CourseCreate,
    CourseMemberPublic,
    CourseMembersPublic,
    CoursePublic,
    CoursesPublic,
    CourseUpdate,
    Enrollment,
    Message,
    User,
    new_enroll_code,
)
from app.services import agent_sessions
from app.services.course_access import (
    get_accessible_course as _get_accessible_course,
)
from app.services.course_access import (
    get_owned_course as _get_owned_course,
)

router = APIRouter(prefix="/courses", tags=["courses"])


# ----- Courses -----


@router.get("/", response_model=CoursesPublic)
def read_courses(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    if current_user.is_superuser:
        count_statement = select(func.count()).select_from(Course)
        statement = select(Course)
    else:
        count_statement = (
            select(func.count())
            .select_from(Course)
            .where(Course.owner_id == current_user.id)
        )
        statement = select(Course).where(Course.owner_id == current_user.id)
    count = session.exec(count_statement).one()
    courses = session.exec(
        statement.order_by(Course.created_at.desc()).offset(skip).limit(limit)  # type: ignore
    ).all()
    return CoursesPublic(data=courses, count=count)


@router.post("/", response_model=CoursePublic)
def create_course(
    *, session: SessionDep, current_user: TeacherUser, course_in: CourseCreate
) -> Any:
    """Create a course. Teachers only — students get 403."""
    course = Course.model_validate(course_in, update={"owner_id": current_user.id})
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


@router.get("/{course_id}", response_model=CoursePublic)
def read_course(
    session: SessionDep, current_user: CurrentUser, course_id: uuid.UUID
) -> Any:
    return _get_accessible_course(session, current_user, course_id)


@router.patch("/{course_id}", response_model=CoursePublic)
def update_course(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    course_id: uuid.UUID,
    course_in: CourseUpdate,
) -> Any:
    course = _get_owned_course(session, current_user, course_id)
    # exclude_none: an explicit null must not write NULL into non-nullable columns
    course.sqlmodel_update(course_in.model_dump(exclude_unset=True, exclude_none=True))
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


@router.post("/{course_id}/enroll-code/rotate", response_model=CoursePublic)
def rotate_enroll_code(session: SessionDep, current_user: TeacherUser, course_id: uuid.UUID) -> Any:
    course = _get_owned_course(session, current_user, course_id)
    course.enroll_code = new_enroll_code()
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


@router.get("/{course_id}/members", response_model=CourseMembersPublic)
def read_course_members(session: SessionDep, current_user: TeacherUser, course_id: uuid.UUID) -> Any:
    """A teacher sees only their own roster and aggregate chapter progress."""
    _get_owned_course(session, current_user, course_id)
    total = session.exec(select(func.count()).select_from(Chapter).where(Chapter.course_id == course_id)).one()
    rows = session.exec(select(Enrollment, User).join(User, Enrollment.student_id == User.id).where(Enrollment.course_id == course_id).order_by(Enrollment.created_at.desc())).all()  # type: ignore[arg-type]
    members = []
    for enrollment, student in rows:
        completed = session.exec(select(func.count()).select_from(ChapterProgress).join(Chapter, ChapterProgress.chapter_id == Chapter.id).where(Chapter.course_id == course_id, ChapterProgress.student_id == student.id)).one()  # type: ignore[arg-type]
        members.append(CourseMemberPublic(id=student.id, email=student.email, full_name=student.full_name, enrolled_at=enrollment.created_at, completed_chapters=completed, total_chapters=total))
    return CourseMembersPublic(data=members, count=len(members))


@router.delete("/{course_id}/members/{student_id}")
def remove_course_member(session: SessionDep, current_user: TeacherUser, course_id: uuid.UUID, student_id: uuid.UUID) -> Message:
    _get_owned_course(session, current_user, course_id)
    enrollment = session.exec(select(Enrollment).where(Enrollment.course_id == course_id, Enrollment.student_id == student_id)).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Student is not enrolled in this course")
    session.delete(enrollment)
    session.commit()
    return Message(message="Student removed from course")


@router.delete("/{course_id}")
async def delete_course(
    session: SessionDep, current_user: CurrentUser, course_id: uuid.UUID
) -> Message:
    course = _get_owned_course(session, current_user, course_id)
    # Agent sessions bind via generic scope ids with no FK cascade — purge
    # their checkpoints explicitly before the business rows go (plan §12.11).
    chapters = session.exec(
        select(Chapter).where(Chapter.course_id == course_id)
    ).all()
    await agent_sessions.purge_scope_sessions(
        session, "chapter", [str(c.id) for c in chapters]
    )
    await agent_sessions.purge_scope_sessions(session, "course", [str(course_id)])
    session.delete(course)
    session.commit()
    return Message(message="Course deleted successfully")


# ----- Chapters (nested under a course) -----


@router.get("/{course_id}/chapters", response_model=ChaptersPublic)
def read_chapters(
    session: SessionDep,
    current_user: CurrentUser,
    course_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    _get_accessible_course(session, current_user, course_id)
    count_statement = (
        select(func.count()).select_from(Chapter).where(Chapter.course_id == course_id)
    )
    statement = (
        select(Chapter)
        .where(Chapter.course_id == course_id)
        .order_by(Chapter.order_index)  # type: ignore
        .offset(skip)
        .limit(limit)
    )
    count = session.exec(count_statement).one()
    chapters = session.exec(statement).all()

    # Mark which chapters the current user (as a student) has completed
    completed_ids: set[uuid.UUID] = set()
    if chapters:
        rows = session.exec(
            select(ChapterProgress.chapter_id).where(
                ChapterProgress.student_id == current_user.id,
                ChapterProgress.chapter_id.in_([c.id for c in chapters]),  # type: ignore
            )
        ).all()
        completed_ids = set(rows)

    data = [
        ChapterPublic.model_validate(c, update={"completed": c.id in completed_ids})
        for c in chapters
    ]
    return ChaptersPublic(data=data, count=count)


@router.post("/{course_id}/chapters", response_model=ChapterPublic)
def create_chapter(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    course_id: uuid.UUID,
    chapter_in: ChapterCreate,
) -> Any:
    _get_owned_course(session, current_user, course_id)
    chapter = Chapter.model_validate(chapter_in, update={"course_id": course_id})
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter


@router.patch("/chapters/{chapter_id}", response_model=ChapterPublic)
def update_chapter(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    chapter_id: uuid.UUID,
    chapter_in: ChapterUpdate,
) -> Any:
    chapter = session.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    _get_owned_course(session, current_user, chapter.course_id)
    # exclude_none: an explicit null must not write NULL into non-nullable columns
    chapter.sqlmodel_update(
        chapter_in.model_dump(exclude_unset=True, exclude_none=True)
    )
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter


@router.delete("/chapters/{chapter_id}")
async def delete_chapter(
    session: SessionDep, current_user: CurrentUser, chapter_id: uuid.UUID
) -> Message:
    chapter = session.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    _get_owned_course(session, current_user, chapter.course_id)
    # purge chapter-scoped agent sessions (checkpoints included) before the
    # chapter row goes — the generic scope column has no FK cascade (§12.11)
    await agent_sessions.purge_scope_sessions(session, "chapter", [str(chapter_id)])
    session.delete(chapter)
    session.commit()
    return Message(message="Chapter deleted successfully")


# ----- Learning progress (students) -----


@router.post("/chapters/{chapter_id}/complete", response_model=ChapterPublic)
def complete_chapter(
    session: SessionDep, current_user: CurrentUser, chapter_id: uuid.UUID
) -> Any:
    chapter = session.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    _get_accessible_course(session, current_user, chapter.course_id)
    existing = session.exec(
        select(ChapterProgress).where(
            ChapterProgress.chapter_id == chapter_id,
            ChapterProgress.student_id == current_user.id,
        )
    ).first()
    if not existing:
        session.add(ChapterProgress(chapter_id=chapter_id, student_id=current_user.id))
        session.commit()
    return ChapterPublic.model_validate(chapter, update={"completed": True})


@router.delete("/chapters/{chapter_id}/complete", response_model=ChapterPublic)
def uncomplete_chapter(
    session: SessionDep, current_user: CurrentUser, chapter_id: uuid.UUID
) -> Any:
    chapter = session.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    _get_accessible_course(session, current_user, chapter.course_id)
    existing = session.exec(
        select(ChapterProgress).where(
            ChapterProgress.chapter_id == chapter_id,
            ChapterProgress.student_id == current_user.id,
        )
    ).first()
    if existing:
        session.delete(existing)
        session.commit()
    return ChapterPublic.model_validate(chapter, update={"completed": False})
