"""HTTP authorization checks using an isolated in-memory database."""

from datetime import timedelta
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.deps import get_db
from app.api.routes.teacher_chat_records import router
from app.core.security import create_access_token
from app.models import Course, User


def test_teacher_cannot_access_other_teachers_courses_or_student_accounts():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    SQLModel.metadata.create_all(engine, tables=[User.__table__, Course.__table__])
    with Session(engine) as session:
        teacher_a = User(email="teacher-a@example.com", hashed_password="unused", role="teacher")
        teacher_b = User(email="teacher-b@example.com", hashed_password="unused", role="teacher")
        student = User(email="student@example.com", hashed_password="unused", role="student")
        session.add_all([teacher_a, teacher_b, student])
        session.flush()
        course_a = Course(title="Course A", owner_id=teacher_a.id)
        course_b = Course(title="Course B", owner_id=teacher_b.id)
        session.add_all([course_a, course_b])
        session.commit()
        ids = (teacher_a.id, teacher_b.id, student.id, course_a.id, course_b.id)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    class SQLiteSession(Session):
        # PostgreSQL accepts JWT subject strings for UUID columns; SQLite's
        # emulated UUID type requires a UUID object for the same lookup.
        def get(self, entity, ident, **kwargs):
            if entity is User and isinstance(ident, str):
                ident = UUID(ident)
            return super().get(entity, ident, **kwargs)

    def test_db():
        with SQLiteSession(engine) as session:
            yield session
    app.dependency_overrides[get_db] = test_db
    def headers(user_id):
        token = create_access_token(str(user_id), timedelta(minutes=5))
        return {"Authorization": f"Bearer {token}"}

    teacher_a_id, teacher_b_id, student_id, course_a_id, course_b_id = ids
    base = "/api/v1/teacher-chat-records"
    with TestClient(app) as client:
        assert client.get(f"{base}/courses", headers={"Authorization": "Bearer invalid"}).status_code == 403
        assert client.get(f"{base}/courses", headers=headers(student_id)).status_code == 403
        own_courses = client.get(f"{base}/courses", headers=headers(teacher_a_id))
        assert own_courses.status_code == 200
        assert own_courses.json() == [{"id": str(course_a_id), "title": "Course A"}]
        assert client.get(f"{base}/courses/{course_b_id}/sessions", headers=headers(teacher_a_id)).status_code == 403
        assert client.get(f"{base}/courses/{course_a_id}/sessions", headers=headers(teacher_b_id)).status_code == 403
        assert client.get(f"{base}/courses/{course_a_id}/sessions/other/messages", headers=headers(student_id)).status_code == 403
        assert client.get(f"{base}/courses/{course_b_id}/sessions/other/messages", headers=headers(teacher_a_id)).status_code == 403
    engine.dispose()
