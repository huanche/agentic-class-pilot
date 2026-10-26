"""The platform's teacher publication adapter fails closed on bad responses."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import teacher_bridge
from app.generated.platform_teacher_api.models import (
    GetTeacherPublicationVerdictResponse200,
    GetTeacherPublicationVerdictResponse200PublicationType1,
    ProvisionTeacherCourseResponse200,
    ProvisionTeacherCourseResponse200Course,
)
from app.services import (
    course_publication,
    teacher_course_client,
    teacher_publication_client,
)

COURSE_ID = uuid.UUID(int=1)
OWNER_ID = uuid.UUID(int=2)


def test_generated_client_reads_delegated_publication(monkeypatch):
    captured = {}

    def generated_call(course_id, *, client):
        captured["course_id"] = course_id
        http_client = client.get_httpx_client()
        captured["service_key"] = http_client.headers["X-Platform-Service-Key"]
        captured["subject"] = http_client.headers["X-Platform-Subject"]
        return SimpleNamespace(
            status_code=200,
            parsed=GetTeacherPublicationVerdictResponse200(
                published=True,
                publication=GetTeacherPublicationVerdictResponse200PublicationType1(
                    publication_id="package-3", version=3
                ),
            ),
        )

    monkeypatch.setattr(teacher_publication_client.settings, "TEACHER_SERVICE_KEY", "test-key")
    monkeypatch.setattr(teacher_publication_client, "sync_detailed", generated_call)
    assert teacher_publication_client.get_teacher_publication(COURSE_ID, OWNER_ID) == {
        "publicationId": "package-3", "version": 3
    }
    assert captured == {
        "course_id": str(COURSE_ID),
        "service_key": "test-key",
        "subject": str(OWNER_ID),
    }


@pytest.mark.parametrize("status, published, publication", [
    (200, False, None),
    (403, False, None),
    (200, True, None),
])
def test_unpublished_and_invalid_responses_are_distinct(
    monkeypatch, status, published, publication
):
    monkeypatch.setattr(teacher_publication_client.settings, "TEACHER_SERVICE_KEY", "test-key")
    monkeypatch.setattr(
        teacher_publication_client,
        "sync_detailed",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=status,
            parsed=GetTeacherPublicationVerdictResponse200(
                published=published, publication=publication
            ),
        ),
    )
    if status == 200 and not published:
        assert teacher_publication_client.get_teacher_publication(COURSE_ID, OWNER_ID) is None
    else:
        with pytest.raises(teacher_publication_client.TeacherPublicationUnavailable):
            teacher_publication_client.get_teacher_publication(COURSE_ID, OWNER_ID)


class FakeSession:
    def __init__(self, legacy_published, legacy_identity=None):
        self.legacy_published = legacy_published
        self.legacy_identity = legacy_identity
        self.queries = 0

    def get(self, model, course_id):
        assert course_id == COURSE_ID
        return SimpleNamespace(owner_id=OWNER_ID)

    def execute(self, statement, params):
        self.queries += 1
        return SimpleNamespace(
            first=lambda: self.legacy_identity or ((1,) if self.legacy_published else None)
        )


def test_shadow_keeps_legacy_verdict_on_teacher_outage(monkeypatch):
    monkeypatch.setattr(course_publication.settings, "TEACHER_PUBLICATION_READ_MODE", "shadow")

    def unavailable(*_args):
        raise teacher_publication_client.TeacherPublicationUnavailable()

    monkeypatch.setattr(course_publication, "get_teacher_publication", unavailable)
    session = FakeSession(legacy_published=True)
    course_publication.require_published_course(session, COURSE_ID)
    assert session.queries == 1


def test_api_mode_uses_teacher_verdict_and_fails_closed(monkeypatch):
    monkeypatch.setattr(course_publication.settings, "TEACHER_PUBLICATION_READ_MODE", "api")
    session = FakeSession(legacy_published=True)
    monkeypatch.setattr(course_publication, "get_teacher_publication", lambda *args: None)
    with pytest.raises(HTTPException) as unpublished:
        course_publication.require_published_course(session, COURSE_ID)
    assert unpublished.value.status_code == 409
    assert session.queries == 0

    def unavailable(*_args):
        raise teacher_publication_client.TeacherPublicationUnavailable()

    monkeypatch.setattr(course_publication, "get_teacher_publication", unavailable)
    with pytest.raises(HTTPException) as outage:
        course_publication.require_published_course(session, COURSE_ID)
    assert outage.value.status_code == 503
    assert session.queries == 0


def test_course_alias_only_reads_platform_mapping(monkeypatch):
    monkeypatch.setattr(teacher_bridge, "check_service_key", lambda value: None)

    class MappingSession:
        def __init__(self):
            self.statements = []

        def execute(self, statement, params):
            self.statements.append(str(statement))
            return SimpleNamespace(first=lambda: (str(COURSE_ID), "legacy-course"))

    session = MappingSession()
    result = teacher_bridge.resolve_course_alias(str(COURSE_ID), session, "test-key")
    assert result == {
        "platformCourseId": str(COURSE_ID), "legacyCourseId": "legacy-course"
    }
    assert len(session.statements) == 1
    assert "teacher." not in session.statements[0]


def test_student_launch_identity_switches_to_teacher_api(monkeypatch):
    session = FakeSession(True, ("2", "old-package"))
    monkeypatch.setattr(course_publication.settings, "TEACHER_PUBLICATION_READ_MODE", "shadow")
    monkeypatch.setattr(
        course_publication,
        "get_teacher_publication",
        lambda *args: {"publicationId": "new-package", "version": 3},
    )
    assert course_publication.latest_publication(session, COURSE_ID) == {
        "publicationId": "old-package", "version": 2
    }
    assert session.queries == 1

    monkeypatch.setattr(course_publication.settings, "TEACHER_PUBLICATION_READ_MODE", "api")
    assert course_publication.latest_publication(session, COURSE_ID) == {
        "publicationId": "new-package", "version": 3
    }
    assert session.queries == 1


def test_generated_teacher_provisioning_keeps_owner_and_course_id(monkeypatch):
    monkeypatch.setattr(teacher_course_client.settings, "TEACHER_SERVICE_KEY", "test-key")
    captured = {}

    async def generated_call(*, client, body):
        http_client = client.get_async_httpx_client()
        captured.update(
            key=http_client.headers["X-Platform-Service-Key"],
            subject=http_client.headers["X-Platform-Subject"],
            body=body.to_dict(),
        )
        return SimpleNamespace(
            status_code=200,
            parsed=ProvisionTeacherCourseResponse200(
                success=True,
                course=ProvisionTeacherCourseResponse200Course(id="legacy-course"),
            ),
        )

    monkeypatch.setattr(teacher_course_client, "asyncio_detailed", generated_call)
    result = asyncio.run(teacher_course_client.provision_teacher_course(
        "legacy-course", OWNER_ID, "课程", None
    ))
    assert result == "legacy-course"
    assert captured == {
        "key": "test-key",
        "subject": str(OWNER_ID),
        "body": {"id": "legacy-course", "title": "课程", "description": None},
    }


def test_teacher_workspace_only_reads_platform_mapping(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_COURSE_PROVISION_MODE", "api")
    monkeypatch.setattr(
        teacher_bridge,
        "get_owned_course",
        lambda session, user, course_id: SimpleNamespace(
            id=COURSE_ID, owner_id=OWNER_ID, title="课程", description=None
        ),
    )
    calls = []

    async def provision(external_id, owner_id, title, description):
        calls.append((external_id, owner_id, title, description))
        return external_id

    monkeypatch.setattr(teacher_bridge, "provision_teacher_course", provision)

    class MappingSession:
        def __init__(self):
            self.statements = []

        def execute(self, statement, params):
            self.statements.append(str(statement))
            return SimpleNamespace(first=lambda: ("legacy-course",))

    session = MappingSession()
    result = asyncio.run(teacher_bridge.open_teacher_workspace(
        COURSE_ID, session, SimpleNamespace(id=OWNER_ID)
    ))
    assert "workspace=legacy-course" in result["url"]
    assert calls == [("legacy-course", OWNER_ID, "课程", None)]
    assert len(session.statements) == 2
    assert all("teacher." not in statement for statement in session.statements)


def test_teacher_workspace_legacy_mode_keeps_existing_path(monkeypatch):
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_COURSE_PROVISION_MODE", "legacy")
    monkeypatch.setattr(
        teacher_bridge,
        "get_owned_course",
        lambda session, user, course_id: SimpleNamespace(id=COURSE_ID, owner_id=OWNER_ID),
    )

    async def unexpected_provision(*_args):
        raise AssertionError("generated client must stay disabled by default")

    monkeypatch.setattr(teacher_bridge, "provision_teacher_course", unexpected_provision)

    class LegacySession:
        def __init__(self):
            self.statements = []

        def execute(self, statement, params):
            sql = str(statement)
            self.statements.append(sql)
            if "teacher_course_link" in sql:
                return SimpleNamespace(first=lambda: ("legacy-course",))
            if "teacher.mentra_courses" in sql:
                return SimpleNamespace(first=lambda: (1,))
            return SimpleNamespace(first=lambda: None)

    session = LegacySession()
    result = asyncio.run(teacher_bridge.open_teacher_workspace(
        COURSE_ID, session, SimpleNamespace(id=OWNER_ID)
    ))
    assert "workspace=legacy-course" in result["url"]
    assert any("teacher.mentra_courses" in sql for sql in session.statements)


def test_teacher_provisioning_conflict_fails_closed(monkeypatch):
    monkeypatch.setattr(teacher_course_client.settings, "TEACHER_SERVICE_KEY", "test-key")

    async def conflict(*, client, body):
        assert client.get_async_httpx_client().headers["X-Platform-Service-Key"] == "test-key"
        assert body.id == "legacy-course"
        return SimpleNamespace(status_code=409, parsed=None)

    monkeypatch.setattr(teacher_course_client, "asyncio_detailed", conflict)
    with pytest.raises(teacher_course_client.TeacherCourseConflict):
        asyncio.run(teacher_course_client.provision_teacher_course(
            "legacy-course", OWNER_ID, "课程", None
        ))
