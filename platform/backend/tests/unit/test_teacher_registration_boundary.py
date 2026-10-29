"""Teacher registration can use the authenticated service request without teacher-table reads."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import teacher_bridge
from app.models import Course, User


OWNER_ID = uuid.UUID(int=2)
COURSE_ID = uuid.UUID(int=3)


class Session:
    def __init__(self, *, existing=None, teacher=None):
        self.existing = existing
        self.teacher = teacher or SimpleNamespace(is_active=True, role="teacher", is_superuser=False)
        self.statements = []
        self.added = []

    def get(self, model, identifier):
        if model is User:
            return self.teacher
        if model is Course:
            return self.existing
        raise AssertionError(model)

    def execute(self, statement, parameters):
        sql = str(statement)
        self.statements.append(sql)
        assert "teacher." not in sql
        assert "teacher_course_link" in sql
        return None

    def add(self, course):
        self.added.append(course)

    def flush(self):
        pass

    def commit(self):
        pass

    def refresh(self, course):
        pass


class Row:
    def __init__(self, values):
        self.values = values

    def first(self):
        return self.values


class LegacySession(Session):
    """legacy 模式：允许教师表交叉检查查询，其余约束与 api 模式相同。"""

    def __init__(self, source, **kwargs):
        super().__init__(**kwargs)
        self.source = source

    def execute(self, statement, parameters):
        sql = str(statement)
        self.statements.append(sql)
        if "teacher.mentra_courses" in sql:
            return Row(self.source)
        assert "teacher_course_link" in sql
        return None


def body(teacher_id=OWNER_ID):
    return teacher_bridge.TeacherCourseRegistration(
        course_id=COURSE_ID, teacher_id=teacher_id,
        title="接口课程", description="由教师服务提交",
    )


def test_authenticated_registration_avoids_teacher_tables(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_COURSE_REGISTRATION_MODE", "api")
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_SERVICE_KEY", "test-key")
    session = Session()

    assert teacher_bridge.register_teacher_course(body(), session, "test-key") == {"id": str(COURSE_ID)}
    assert len(session.added) == 1
    assert session.added[0].title == "接口课程"
    assert session.added[0].description == "由教师服务提交"


@pytest.mark.parametrize("key, existing_owner, status", [
    ("bad-key", None, 403),
    ("test-key", uuid.UUID(int=4), 409),
])
def test_registration_still_rejects_invalid_service_or_owner(monkeypatch, key, existing_owner, status):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_COURSE_REGISTRATION_MODE", "api")
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_SERVICE_KEY", "test-key")
    existing = SimpleNamespace(owner_id=existing_owner) if existing_owner else None
    session = Session(existing=existing)

    with pytest.raises(HTTPException) as error:
        teacher_bridge.register_teacher_course(body(), session, key)
    assert error.value.status_code == status
    assert not session.statements


def test_legacy_mode_still_crosschecks_teacher_tables(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_COURSE_REGISTRATION_MODE", "legacy")
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_SERVICE_KEY", "test-key")
    session = LegacySession(source=(str(OWNER_ID), "库内标题", {"description": "库内描述"}))

    assert teacher_bridge.register_teacher_course(body(), session, "test-key") == {"id": str(COURSE_ID)}
    assert any("teacher.mentra_courses" in sql for sql in session.statements)
    assert session.added[0].title == "库内标题"
    assert session.added[0].description == "库内描述"
    assert any("teacher_course_link" in sql for sql in session.statements)


def test_legacy_mode_rejects_ownership_mismatch(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_COURSE_REGISTRATION_MODE", "legacy")
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_SERVICE_KEY", "test-key")
    session = LegacySession(source=(str(uuid.UUID(int=9)), "库内标题", {}))

    with pytest.raises(HTTPException) as error:
        teacher_bridge.register_teacher_course(body(), session, "test-key")
    assert error.value.status_code == 409


def test_re_registration_without_description_keeps_existing_copy(monkeypatch):
    """api 模式重登记缺 description 时不得清空平台已有描述。"""
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_COURSE_REGISTRATION_MODE", "api")
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_SERVICE_KEY", "test-key")
    existing = SimpleNamespace(id=COURSE_ID, owner_id=OWNER_ID, title="旧标题", description="已有描述")
    session = Session(existing=existing)

    teacher_bridge.register_teacher_course(
        teacher_bridge.TeacherCourseRegistration(
            course_id=COURSE_ID, teacher_id=OWNER_ID, title="新标题"),
        session, "test-key")
    assert existing.title == "新标题"
    assert existing.description == "已有描述"
