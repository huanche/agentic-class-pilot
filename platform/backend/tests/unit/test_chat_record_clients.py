"""Generated HTTP clients preserve service identity and response shapes."""

import uuid
import json

import httpx
import pytest

from app.core.config import settings
from app.generated.platform_student_api import AuthenticatedClient as StudentClient
from app.generated.platform_teacher_api import AuthenticatedClient as TeacherClient
from app.services import student_chat_records_client, teacher_lesson_titles_client


def test_student_chat_client_sends_scoped_ids_and_handles_missing(monkeypatch):
    monkeypatch.setattr(settings, "STUDENT_SERVICE_KEY", "student-test-key")
    seen = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["X-Student-Service-Key"] == "student-test-key"
        assert request.method == "POST"
        assert json.loads(request.content)["userIds"] == ["student-a"]
        if request.url.path.endswith("/messages"):
            return httpx.Response(404, json={"detail": "missing"})
        return httpx.Response(200, json=[{"sessionKey": "session-a", "studentId": "student-a"}])

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(student_chat_records_client, "_client", lambda: StudentClient(
        base_url="http://student", token="student-test-key", prefix="",
        auth_header_name="X-Student-Service-Key",
        httpx_args={"transport": transport}, raise_on_unexpected_status=False,
    ))
    course_id = uuid.uuid4()
    assert student_chat_records_client.get_chat_sessions(course_id, ["student-a"], 10)[0]["sessionKey"] == "session-a"
    with pytest.raises(student_chat_records_client.StudentChatMissing):
        student_chat_records_client.get_chat_messages(course_id, "session-b", ["student-a"], None, 10, 0)
    assert len(seen) == 2


def test_teacher_lesson_titles_client_parses_scoped_response(monkeypatch):
    monkeypatch.setattr(settings, "TEACHER_SERVICE_KEY", "teacher-test-key")
    owner_id = uuid.uuid4()

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["X-Platform-Service-Key"] == "teacher-test-key"
        assert request.headers["X-Platform-Subject"] == str(owner_id)
        return httpx.Response(200, json={"titles": {"lesson-a": "Lesson A"}})

    transport = httpx.MockTransport(respond)
    real_client = TeacherClient
    monkeypatch.setattr(teacher_lesson_titles_client, "AuthenticatedClient", lambda **kwargs: real_client(
        **{**kwargs, "httpx_args": {"transport": transport}},
    ))
    assert teacher_lesson_titles_client.get_lesson_titles(uuid.uuid4(), owner_id) == {"lesson-a": "Lesson A"}
