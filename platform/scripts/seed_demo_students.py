"""Create local-only sample students, a demo course, enrollments, and progress."""
from sqlmodel import Session, select
from app import crud
from app.core.db import engine
from app.core.config import settings
from app.models import Chapter, ChapterProgress, Course, Enrollment, User, UserCreate

STUDENTS = [("li.ming@demo-agentedu.com", "李明"), ("wang.fang@demo-agentedu.com", "王芳"), ("chen.yu@demo-agentedu.com", "陈宇")]

with Session(engine) as session:
    teacher = session.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).first()
    if not teacher:
        raise SystemExit("Run database initialization first.")
    course = session.exec(select(Course).where(Course.title == "演示课程：AI 学习基础")).first()
    if not course:
        course = Course(title="演示课程：AI 学习基础", description="仅用于本机验证教师学生管理", owner_id=teacher.id)
        session.add(course); session.commit(); session.refresh(course)
    chapters = session.exec(select(Chapter).where(Chapter.course_id == course.id)).all()
    if not chapters:
        for index, title in enumerate(["认识人工智能", "提示词基础", "课堂实践"]):
            session.add(Chapter(course_id=course.id, title=title, order_index=index))
        session.commit(); chapters = session.exec(select(Chapter).where(Chapter.course_id == course.id)).all()
    for index, (email, name) in enumerate(STUDENTS):
        student = session.exec(select(User).where(User.email == email)).first()
        if not student:
            student = crud.create_user(session=session, user_create=UserCreate(email=email, full_name=name, password="LocalDemoOnly!2026", role="student"))
        if not session.exec(select(Enrollment).where(Enrollment.course_id == course.id, Enrollment.student_id == student.id)).first():
            session.add(Enrollment(course_id=course.id, student_id=student.id)); session.commit()
        for chapter in chapters[:index + 1]:
            if not session.exec(select(ChapterProgress).where(ChapterProgress.chapter_id == chapter.id, ChapterProgress.student_id == student.id)).first():
                session.add(ChapterProgress(chapter_id=chapter.id, student_id=student.id))
        session.commit()
print("Demo course and three demo students are ready. Password: LocalDemoOnly!2026")
