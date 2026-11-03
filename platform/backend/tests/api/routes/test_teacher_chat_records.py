"""Exercise chat record authorization through the actual HTTP endpoints.

These tests use the isolated app_test database from tests/conftest.py. Apply
the normal migrations to that test database before running them.
"""

import json
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app import crud
from app.models import Course, Enrollment, UserCreate
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

BASE = "/api/v1/teacher-chat-records"


def create_user(db: Session, role: str):
    email = random_email()
    password = random_lower_string()
    user = crud.create_user(session=db, user_create=UserCreate(email=email, password=password, role=role))
    return user, email, password


def test_teacher_chat_records_are_scoped_to_owned_courses(client: TestClient, db: Session) -> None:
    teacher_a, email_a, password_a = create_user(db, "teacher")
    teacher_b, email_b, password_b = create_user(db, "teacher")
    student, student_email, student_password = create_user(db, "student")
    course_a = Course(title="教师 A 的课程", owner_id=teacher_a.id)
    course_b = Course(title="教师 B 的课程", owner_id=teacher_b.id)
    db.add_all([course_a, course_b])
    db.commit()
    db.refresh(course_a)
    db.refresh(course_b)
    db.add_all([Enrollment(course_id=course_a.id, student_id=student.id),
                Enrollment(course_id=course_b.id, student_id=student.id)])
    db.commit()

    session_a, session_b = str(uuid.uuid4()), str(uuid.uuid4())
    keys = [session_a, session_b]
    try:
        for key, course in ((session_a, course_a), (session_b, course_b)):
            db.execute(text("""
                INSERT INTO student.student_sessions
                (session_key, user_id, course_id, publication_id, publication_version, classroom_id)
                VALUES (:key, :student, :course, 'test-publication', 1, 'test-classroom')
            """), {"key": key, "student": str(student.id), "course": str(course.id)})
            db.execute(text("""
                INSERT INTO student.student_messages
                (session_key, user_id, course_id, publication_id, seq, role, phase, content)
                VALUES (:key, :student, :course, 'test-publication', 1, 'student', 'recall', :content)
            """), {"key": key, "student": str(student.id), "course": str(course.id),
                    "content": "学生复述 A" if key == session_a else "学生复述 B"})
            db.execute(text("""
                INSERT INTO student.learning_events
                (session_key, user_id, course_id, publication_id, event_type, event_id, payload)
                VALUES (:key, :student, :course, 'test-publication', 'agent_state', 'test', CAST(:payload AS jsonb))
            """), {"key": key, "student": str(student.id), "course": str(course.id),
                    "payload": json.dumps({"lessonId": "lesson-test"})})
        db.commit()

        headers_a = user_authentication_headers(client=client, email=email_a, password=password_a)
        headers_b = user_authentication_headers(client=client, email=email_b, password=password_b)
        student_headers = user_authentication_headers(client=client, email=student_email, password=student_password)

        # Supplying an invalid bearer token forces authentication even if a test
        # client retained a browser cookie from the preceding login.
        assert client.get(f"{BASE}/courses", headers={"Authorization": "Bearer invalid"}).status_code in (401, 403)
        assert client.get(f"{BASE}/courses", headers=student_headers).status_code == 403
        courses = client.get(f"{BASE}/courses", headers=headers_a)
        assert courses.status_code == 200
        assert str(course_a.id) in [row["id"] for row in courses.json()]
        assert str(course_b.id) not in [row["id"] for row in courses.json()]

        sessions = client.get(f"{BASE}/courses/{course_a.id}/sessions", headers=headers_a)
        assert sessions.status_code == 200
        assert [row["sessionKey"] for row in sessions.json()] == [session_a]
        assert sessions.json()[0]["lessonId"] == "lesson-test"
        # Newer student sessions keep the authoritative lesson on the session
        # itself, while older records only have it in the event snapshot.
        db.execute(text("UPDATE student.student_sessions SET lesson_id = 'new-lesson' WHERE session_key = :key"), {"key": session_a})
        db.commit()
        assert client.get(f"{BASE}/courses/{course_a.id}/sessions", headers=headers_a).json()[0]["lessonId"] == "new-lesson"
        assert client.get(f"{BASE}/courses/{course_b.id}/sessions", headers=headers_a).status_code == 403
        assert client.get(f"{BASE}/courses/{course_a.id}/sessions", headers=headers_b).status_code == 403

        path = f"{BASE}/courses/{course_a.id}/sessions/{session_a}/messages"
        result = client.get(path, headers=headers_a)
        assert result.status_code == 200
        assert [(row["phase"], row["content"]) for row in result.json()] == [("recall", "学生复述 A")]
        assert client.get(path, params={"phase": "reinforce"}, headers=headers_a).json() == []
        assert client.get(f"{BASE}/courses/{course_a.id}/sessions/{session_b}/messages", headers=headers_a).status_code == 404
        assert client.get(path, headers=student_headers).status_code == 403
        assert client.post(path, headers=headers_a).status_code == 405
        db.execute(text("UPDATE student.student_sessions SET revoked_at = now() WHERE session_key = :key"), {"key": session_a})
        db.commit()
        assert client.get(path, headers=headers_a).status_code == 404
        assert client.get(f"{BASE}/courses/{course_a.id}/sessions", headers=headers_a).json() == []
    finally:
        for key in keys:
            for table in ("student_messages", "learning_events", "student_sessions"):
                db.execute(text(f"DELETE FROM student.{table} WHERE session_key = :key"), {"key": key})
        db.commit()
