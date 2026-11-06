"""Teacher chat record authorization using an isolated platform test database."""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.models import Course, Enrollment, UserCreate
from app.services import student_chat_records_client, teacher_lesson_titles_client
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

BASE = "/api/v1/teacher-chat-records"


def create_user(db: Session, role: str):
    email = random_email()
    password = random_lower_string()
    user = crud.create_user(session=db, user_create=UserCreate(email=email, password=password, role=role))
    return user, email, password


def test_teacher_chat_records_are_scoped_to_owned_courses(client: TestClient, db: Session, monkeypatch) -> None:
    teacher_a, email_a, password_a = create_user(db, "teacher")
    teacher_b, email_b, password_b = create_user(db, "teacher")
    student, student_email, student_password = create_user(db, "student")
    course_a = Course(title="Teacher A course", owner_id=teacher_a.id)
    course_b = Course(title="Teacher B course", owner_id=teacher_b.id)
    db.add_all([course_a, course_b])
    db.commit()
    db.refresh(course_a)
    db.refresh(course_b)
    db.add_all([
        Enrollment(course_id=course_a.id, student_id=student.id),
        Enrollment(course_id=course_b.id, student_id=student.id),
    ])
    db.commit()
    key_a, key_b = str(uuid.uuid4()), str(uuid.uuid4())
    revoked = False
    calls = []

    def sessions(course_id, user_ids, limit, offset=None, lesson_id=None, classroom_id=None):
        calls.append(("sessions", course_id, user_ids))
        if offset is not None:
            assert (offset, lesson_id, classroom_id) == (500, "lesson-a", "room-a")
        assert user_ids == [str(student.id)]
        if course_id == course_a.id and not revoked:
            return [{"sessionKey": key_a, "studentId": str(student.id), "classroomId": "room-a",
                     "startedAt": "2026-01-01T00:00:00", "lastActiveAt": "2026-01-01T00:00:00",
                     "ended": False, "lessonId": "lesson-a", "messageCount": 1}]
        return []

    def messages(course_id, session_key, user_ids, phase, limit, offset):
        calls.append(("messages", course_id, user_ids))
        assert user_ids == [str(student.id)]
        if course_id != course_a.id or session_key != key_a or revoked:
            raise student_chat_records_client.StudentChatMissing()
        if phase is not None and phase != "recall":
            return []
        return [{"seq": 1, "role": "student", "phase": "recall", "content": "student reply",
                 "createdAt": "2026-01-01T00:00:00"}]

    monkeypatch.setattr(student_chat_records_client, "get_chat_sessions", sessions)
    monkeypatch.setattr(student_chat_records_client, "pagination_available", lambda: True)
    monkeypatch.setattr(student_chat_records_client, "get_chat_messages", messages)
    monkeypatch.setattr(teacher_lesson_titles_client, "get_lesson_titles",
                        lambda course_id, owner_id: {"lesson-a": "Lesson A"})

    headers_a = user_authentication_headers(client=client, email=email_a, password=password_a)
    headers_b = user_authentication_headers(client=client, email=email_b, password=password_b)
    student_headers = user_authentication_headers(client=client, email=student_email, password=student_password)

    assert client.get(f"{BASE}/courses", headers={"Authorization": "Bearer invalid"}).status_code in (401, 403)
    assert client.get(f"{BASE}/courses", headers=student_headers).status_code == 403
    courses = client.get(f"{BASE}/courses", headers=headers_a)
    assert courses.status_code == 200
    assert str(course_a.id) in [row["id"] for row in courses.json()]
    assert str(course_b.id) not in [row["id"] for row in courses.json()]

    result = client.get(f"{BASE}/courses/{course_a.id}/sessions", headers=headers_a)
    assert result.status_code == 200
    assert [row["sessionKey"] for row in result.json()] == [key_a]
    assert result.json()[0]["lesson"] == "Lesson A"
    assert client.get(f"{BASE}/capabilities", headers=headers_a).json() == {"session_pagination": 1}
    assert client.get(f"{BASE}/courses/{course_a.id}/sessions", params={"offset": 500, "lesson_id": "lesson-a", "classroom_id": "room-a"}, headers=headers_a).status_code == 200
    assert client.get(f"{BASE}/courses/{course_a.id}/sessions", headers=headers_b).status_code == 403
    assert client.get(f"{BASE}/courses/{course_b.id}/sessions", headers=headers_a).status_code == 403

    path = f"{BASE}/courses/{course_a.id}/sessions/{key_a}/messages"
    assert client.get(path, headers=headers_a).json()[0]["content"] == "student reply"
    assert client.get(path, params={"phase": "reinforce"}, headers=headers_a).json() == []
    assert client.get(f"{BASE}/courses/{course_a.id}/sessions/{key_b}/messages", headers=headers_a).status_code == 404
    assert client.get(path, headers=student_headers).status_code == 403
    assert client.post(path, headers=headers_a).status_code == 405
    revoked = True
    assert client.get(path, headers=headers_a).status_code == 404
    assert client.get(f"{BASE}/courses/{course_a.id}/sessions", headers=headers_a).json() == []
    assert calls
