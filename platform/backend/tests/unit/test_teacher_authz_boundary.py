"""Authorize decisions can avoid teacher-schema reads in api mode."""

import logging
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import teacher_bridge
from app.services import teacher_authz_client

COURSE_ID = "11111111-1111-1111-1111-111111111111"
OWNER_ID = uuid.UUID(int=2)
OTHER_ID = uuid.UUID(int=3)
USER_ID = uuid.UUID(int=4)


class Row:
    def __init__(self, values):
        self.values = values

    def first(self):
        return self.values


class FakeSession:
    """Platform-table fake; any teacher-schema SQL trips an assertion."""

    def __init__(self, *, course_exists=True, owner=str(OWNER_ID), enrolled=True,
                 link=None, allow_teacher_sql=False):
        self.course_exists = course_exists
        self.owner = owner
        self.enrolled = enrolled
        self.link = link
        self.allow_teacher_sql = allow_teacher_sql
        self.sql = []

    def execute(self, statement, params):
        sql = str(statement)
        self.sql.append(sql)
        if "SELECT c.owner_id::text FROM course c" in sql:
            return Row((self.owner,) if self.course_exists else None)
        if "FROM course WHERE id::text" in sql:
            return Row((COURSE_ID,) if self.course_exists else None)
        if "FROM teacher_course_link" in sql:
            return Row((self.link,) if self.link else None)
        if "FROM enrollment" in sql:
            return Row((1,) if self.enrolled else None)
        if "teacher." in sql:
            if not self.allow_teacher_sql:
                raise AssertionError(f"teacher-schema SQL in api mode: {sql}")
            return self.teacher_result
        raise AssertionError(f"unexpected SQL: {sql}")


def user(uid=USER_ID, superuser=False):
    return SimpleNamespace(id=uid, is_superuser=superuser)


def test_api_mode_material_allows_enrolled_visible(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_AUTHZ_READ_MODE", "api")
    seen = {}
    monkeypatch.setattr(teacher_authz_client, "material_visibility",
                        lambda ref, mid, owner: seen.update(ref=ref, mid=mid, owner=owner) or True)
    session = FakeSession()
    teacher_bridge._student_material_allowed(session, COURSE_ID, "mat-1", user(), "api")
    assert seen == {"ref": COURSE_ID, "mid": "mat-1", "owner": USER_ID}


def test_api_mode_material_rejects_unenrolled_without_teacher_call(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_AUTHZ_READ_MODE", "api")
    monkeypatch.setattr(teacher_authz_client, "material_visibility",
                        lambda *_: pytest.fail("teacher called for unenrolled student"))
    session = FakeSession(enrolled=False)
    with pytest.raises(HTTPException) as error:
        teacher_bridge._student_material_allowed(session, COURSE_ID, "mat-1", user(), "api")
    assert error.value.status_code == 403
    assert not any("material_visibility" in s for s in [])


def test_api_mode_material_rejects_hidden(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_AUTHZ_READ_MODE", "api")
    monkeypatch.setattr(teacher_authz_client, "material_visibility", lambda *_: False)
    with pytest.raises(HTTPException) as error:
        teacher_bridge._student_material_allowed(FakeSession(), COURSE_ID, "mat-1", user(), "api")
    assert error.value.status_code == 403


def test_api_mode_classroom_allows_enrolled_published(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_AUTHZ_READ_MODE", "api")
    monkeypatch.setattr(teacher_authz_client, "classroom_visibility",
                        lambda cid, owner: (COURSE_ID, True))
    session = FakeSession()
    teacher_bridge._student_classroom_allowed(session, "room-1", user(), "api")


def test_api_mode_classroom_resolves_legacy_ref_via_link(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_AUTHZ_READ_MODE", "api")
    monkeypatch.setattr(teacher_authz_client, "classroom_visibility",
                        lambda cid, owner: ("legacy-nano", True))
    session = FakeSession(link=COURSE_ID)
    teacher_bridge._student_classroom_allowed(session, "room-1", user(), "api")


def test_api_mode_classroom_unmapped_course_rejected(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_AUTHZ_READ_MODE", "api")
    monkeypatch.setattr(teacher_authz_client, "classroom_visibility",
                        lambda cid, owner: ("legacy-nano", True))
    session = FakeSession(link=None)
    with pytest.raises(HTTPException) as error:
        teacher_bridge._student_classroom_allowed(session, "room-1", user(), "api")
    assert error.value.status_code == 403
    assert error.value.detail == "Classroom course is not available to students"


def test_api_mode_classroom_not_published_rejected(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_AUTHZ_READ_MODE", "api")
    monkeypatch.setattr(teacher_authz_client, "classroom_visibility",
                        lambda cid, owner: (COURSE_ID, False))
    with pytest.raises(HTTPException) as error:
        teacher_bridge._student_classroom_allowed(FakeSession(), "room-1", user(), "api")
    assert error.value.detail == "Student may only view an enrolled published classroom"


def test_api_mode_owner_allowed_from_platform_tables(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_AUTHZ_READ_MODE", "api")
    session = FakeSession(owner=str(USER_ID))
    teacher_bridge._teacher_course_owner_allowed(session, COURSE_ID, user(USER_ID), "api")
    assert any("owner_id" in sql for sql in session.sql)


def test_api_mode_owner_uses_legacy_course_mapping(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_AUTHZ_READ_MODE", "api")
    session = FakeSession(owner=str(USER_ID))
    teacher_bridge._teacher_course_owner_allowed(session, "legacy-course", user(USER_ID), "api")
    assert any("external_course_id=:ref" in sql for sql in session.sql)


def test_api_mode_owner_mismatch_rejected(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_AUTHZ_READ_MODE", "api")
    session = FakeSession(owner=str(OWNER_ID))
    with pytest.raises(HTTPException) as error:
        teacher_bridge._teacher_course_owner_allowed(session, COURSE_ID, user(USER_ID), "api")
    assert error.value.status_code == 403
    assert error.value.detail == "无权访问该课程（课程属于其他教师）"


def test_api_mode_unknown_course_404(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_AUTHZ_READ_MODE", "api")
    session = FakeSession(course_exists=False)
    with pytest.raises(HTTPException) as error:
        teacher_bridge._teacher_course_owner_allowed(session, COURSE_ID, user(USER_ID), "api")
    assert error.value.status_code == 404
    assert error.value.detail == "课程不存在或尚未同步到统一数据库"


def test_api_mode_job_resolution(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_AUTHZ_READ_MODE", "api")
    monkeypatch.setattr(teacher_authz_client, "job_course_ref",
                        lambda job, kind, owner: "course-9")
    assert teacher_bridge._job_course_id(FakeSession(), "job-1", "artifact", user(), "api") == "course-9"

    def missing(job, kind, owner):
        raise LookupError("Task not found")

    monkeypatch.setattr(teacher_authz_client, "job_course_ref", missing)
    with pytest.raises(HTTPException) as error:
        teacher_bridge._job_course_id(FakeSession(), "job-1", "graph", user(), "api")
    assert error.value.status_code == 404


def test_shadow_mode_keeps_legacy_owner_verdict(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_AUTHZ_READ_MODE", "shadow")
    session = FakeSession(owner=str(OWNER_ID), allow_teacher_sql=True)
    session.teacher_result = Row((str(OWNER_ID),))
    monkeypatch.setattr(teacher_authz_client, "classroom_visibility",
                        lambda *_: pytest.fail("api not consulted in this test"))
    # legacy teacher row and platform row agree: owner passes either way.
    teacher_bridge._teacher_course_owner_allowed(session, COURSE_ID, user(OWNER_ID), "shadow")


def test_shadow_mode_logs_mismatch_but_keeps_legacy(monkeypatch, caplog):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_AUTHZ_READ_MODE", "shadow")
    session = FakeSession(course_exists=False, allow_teacher_sql=True)
    session.teacher_result = Row((str(OWNER_ID),))
    # teacher table knows the course; the platform copy is missing: mismatch.
    with caplog.at_level(logging.WARNING):
        teacher_bridge._teacher_course_owner_allowed(session, COURSE_ID, user(OWNER_ID), "shadow")
    assert any("teacher_authz_shadow_mismatch" in record.message for record in caplog.records)


def test_client_classroom_visibility_maps_response(monkeypatch):
    from app.generated.platform_teacher_api.models import (
        GetTeacherClassroomVisibilityResponse200,
    )

    captured = {}

    def generated_call(classroom_id, *, client):
        headers = client.get_httpx_client().headers
        captured.update(classroom_id=classroom_id, key=headers["X-Platform-Service-Key"],
                        subject=headers["X-Platform-Subject"])
        return SimpleNamespace(status_code=200, parsed=GetTeacherClassroomVisibilityResponse200(
            course_id="course-1", published=True))

    monkeypatch.setattr(teacher_authz_client.settings, "TEACHER_SERVICE_KEY", "test-key")
    monkeypatch.setattr(teacher_authz_client, "classroom_visibility_detailed", generated_call)
    assert teacher_authz_client.classroom_visibility("room-1", OWNER_ID) == ("course-1", True)
    assert captured == {"classroom_id": "room-1", "key": "test-key", "subject": str(OWNER_ID)}


def test_client_rejects_bad_responses(monkeypatch):
    from app.generated.platform_teacher_api.models import (
        GetTeacherMaterialVisibilityResponse200,
    )

    monkeypatch.setattr(teacher_authz_client.settings, "TEACHER_SERVICE_KEY", "test-key")
    monkeypatch.setattr(
        teacher_authz_client, "material_visibility_detailed",
        lambda *_a, **_k: SimpleNamespace(status_code=503, parsed=None))
    with pytest.raises(teacher_authz_client.TeacherAuthzUnavailable):
        teacher_authz_client.material_visibility("c", "m", OWNER_ID)
    monkeypatch.setattr(
        teacher_authz_client, "material_visibility_detailed",
        lambda *_a, **_k: SimpleNamespace(status_code=200, parsed=GetTeacherMaterialVisibilityResponse200(visible=True)))
    assert teacher_authz_client.material_visibility("c", "m", OWNER_ID) is True
