"""The platform's progress push uses the generated teacher API contract."""

import asyncio
import uuid
from types import SimpleNamespace

import httpx

from app.api.routes import student_bridge
from app.core.config import settings
from app.generated import platform_teacher_api


def test_progress_push_retries_course_alias_using_generated_client(monkeypatch):
    course_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    seen = []

    class Session:
        def execute(self, statement, _params):
            sql = str(statement)
            if "owner_id" in sql:
                return SimpleNamespace(first=lambda: (owner_id,))
            if "external_course_id" in sql:
                return SimpleNamespace(first=lambda: ("teacher-alias",))
            raise AssertionError(sql)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if f"/{course_id}/students" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200, json={
            "success": True, "studentCount": 1,
            "student": {"studentId": "student-1", "name": "Student",
                        "status": "learning"},
        })

    transport = httpx.MockTransport(handler)
    real_client = platform_teacher_api.AuthenticatedClient

    def client_with_transport(**kwargs):
        kwargs["httpx_args"] = {"transport": transport, "trust_env": False}
        return real_client(**kwargs)

    monkeypatch.setattr(platform_teacher_api, "AuthenticatedClient", client_with_transport)
    monkeypatch.setattr(settings, "TEACHER_SERVICE_KEY", "test-service-key")
    monkeypatch.setattr(settings, "TEACHER_URL", "http://teacher.test")
    state = {"studentId": "student-1", "name": "Student", "status": "learning",
             "progress": 50, "completedResourceIds": []}

    assert asyncio.run(student_bridge._push_student_state_to_teacher(
        Session(), course_id, state,
    ))
    assert [request.url.path for request in seen] == [
        f"/api/classes/{course_id}/students", "/api/classes/teacher-alias/students",
    ]
    assert all(request.headers["x-platform-service-key"] == "test-service-key"
               for request in seen)
    assert all(request.headers["x-platform-subject"] == str(owner_id) for request in seen)
    assert '"studentId":"student-1"' in seen[-1].content.decode()
