"""The platform keeps the old classroom read authoritative until API cutover."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import student_bridge
from app.generated.platform_teacher_api.models import GetTeacherLatestClassroomResponse200
from app.services import teacher_classroom_client

COURSE_ID = uuid.UUID(int=11)
OWNER_ID = uuid.UUID(int=12)


class Session:
    def __init__(self):
        self.queries = 0

    def get(self, _model, _id):
        return SimpleNamespace(owner_id=OWNER_ID)

    def execute(self, statement, _params):
        self.queries += 1
        assert "teacher.mentra_classrooms" in str(statement)
        return SimpleNamespace(first=lambda: ("old-room",))


def test_api_mode_uses_teacher_service_without_cross_schema_sql(monkeypatch):
    monkeypatch.setattr(student_bridge.settings, "TEACHER_CLASSROOM_READ_MODE", "api")
    monkeypatch.setattr(teacher_classroom_client, "get_latest_classroom",
                        lambda course, owner: "new-room" if (course, owner) == (COURSE_ID, OWNER_ID) else None)
    session = Session()
    assert student_bridge._published_classroom(session, COURSE_ID) == "new-room"
    assert session.queries == 0


def test_shadow_keeps_legacy_result_on_mismatch(monkeypatch):
    monkeypatch.setattr(student_bridge.settings, "TEACHER_CLASSROOM_READ_MODE", "shadow")
    monkeypatch.setattr(teacher_classroom_client, "get_latest_classroom", lambda *_: "new-room")
    session = Session()
    assert student_bridge._published_classroom(session, COURSE_ID) == "old-room"
    assert session.queries == 1


def test_shadow_keeps_legacy_result_during_teacher_outage(monkeypatch):
    monkeypatch.setattr(student_bridge.settings, "TEACHER_CLASSROOM_READ_MODE", "shadow")

    def unavailable(*_args):
        raise teacher_classroom_client.TeacherClassroomUnavailable()

    monkeypatch.setattr(teacher_classroom_client, "get_latest_classroom", unavailable)
    session = Session()
    assert student_bridge._published_classroom(session, COURSE_ID) == "old-room"
    assert session.queries == 1


def test_api_mode_fails_closed_when_teacher_unavailable(monkeypatch):
    monkeypatch.setattr(student_bridge.settings, "TEACHER_CLASSROOM_READ_MODE", "api")

    def unavailable(*_args):
        raise teacher_classroom_client.TeacherClassroomUnavailable()

    monkeypatch.setattr(teacher_classroom_client, "get_latest_classroom", unavailable)
    session = Session()
    with pytest.raises(HTTPException) as error:
        student_bridge._published_classroom(session, COURSE_ID)
    assert error.value.status_code == 503
    assert session.queries == 0


def test_generated_call_carries_service_key_and_course_owner(monkeypatch):
    captured = {}

    def generated_call(course_id, *, client):
        headers = client.get_httpx_client().headers
        captured.update(course_id=course_id, key=headers["X-Platform-Service-Key"],
                        subject=headers["X-Platform-Subject"])
        return SimpleNamespace(status_code=200,
                               parsed=GetTeacherLatestClassroomResponse200(classroom_id="room-1"))

    monkeypatch.setattr(teacher_classroom_client.settings, "TEACHER_SERVICE_KEY", "test-key")
    monkeypatch.setattr(teacher_classroom_client, "sync_detailed", generated_call)
    assert teacher_classroom_client.get_latest_classroom(COURSE_ID, OWNER_ID) == "room-1"
    assert captured == {"course_id": str(COURSE_ID), "key": "test-key",
                        "subject": str(OWNER_ID)}


def test_generated_call_rejects_http_failure_and_wrong_shape(monkeypatch):
    monkeypatch.setattr(teacher_classroom_client.settings, "TEACHER_SERVICE_KEY", "test-key")
    for response in (
        SimpleNamespace(status_code=503, parsed=None),
        SimpleNamespace(status_code=200,
                        parsed=GetTeacherLatestClassroomResponse200(classroom_id="")),
    ):
        monkeypatch.setattr(teacher_classroom_client, "sync_detailed",
                            lambda *_args, **_kwargs: response)
        with pytest.raises(teacher_classroom_client.TeacherClassroomUnavailable):
            teacher_classroom_client.get_latest_classroom(COURSE_ID, OWNER_ID)
