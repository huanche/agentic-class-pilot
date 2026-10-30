"""Learning context assembly can come from one teacher snapshot instead of teacher-schema SQL."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import student_bridge
from app.generated.platform_teacher_api.models import (
    GetTeacherPublishedContentResponse200,
    PublishedClassroomView,
    PublishedClassroomViewScenesItem,
    PublishedClassroomViewScenesItemActionsItem,
    PublishedEntry,
    PublishedLearningContent,
    PublishedLearningContentCourse,
    PublishedLearningContentPublication,
    PublishedLesson,
)
from app.services import teacher_learning_content_client

COURSE_ID = uuid.UUID(int=21)
USER_ID = uuid.UUID(int=22)
OWNER_ID = uuid.UUID(int=23)


class NoSqlSession:
    """api 模式下不允许任何跨 schema 查询。"""

    def __init__(self):
        self.queries = 0

    def get(self, model, _id):
        assert model.__name__ == "Course"
        return SimpleNamespace(owner_id=OWNER_ID)

    def execute(self, statement, _params):
        self.queries += 1
        raise AssertionError(f"unexpected SQL in api mode: {statement}")


def snapshot():
    return PublishedLearningContent(
        publication=PublishedLearningContentPublication(publication_id="pkg-1", version=3),
        course=PublishedLearningContentCourse(id="canonical"),
        entries=[
            PublishedEntry(id="a1", title="工件", content="正文", kind="artifact",
                           publication_id="p1", resource_type="courseware",
                           scope={"type": "lesson", "lessonId": "L1"},
                           citations=[{"source": "s"}]),
            PublishedEntry(id="m1", title="资料", content="", kind="material",
                           publication_id="pm1",
                           url="/api/course-space/canonical/materials/m1"),
        ],
        lessons=[
            PublishedLesson(id="L1", title="课时一", order=1, week=1, lesson_number=1,
                            teaching_hours=2, published_at=300,
                            classroom=PublishedClassroomView(
                                id="room-1", title="课堂名",
                                scenes=[PublishedClassroomViewScenesItem(
                                    id="s1", type_="slide", order=2, title="页",
                                    visible_text=["要点"],
                                    actions=[PublishedClassroomViewScenesItemActionsItem(
                                        id="a", type_="speech", text="旁白")]),
                                ])),
        ],
    )


def test_api_mode_builds_context_from_one_snapshot(monkeypatch):
    monkeypatch.setattr(student_bridge.settings, "TEACHER_LEARNING_CONTENT_READ_MODE", "api")
    monkeypatch.setattr(student_bridge.settings, "TEACHER_PUBLIC_URL", "http://t:3200")
    monkeypatch.setattr(
        teacher_learning_content_client, "get_teacher_published_content",
        lambda course, owner: snapshot()
        if (course, owner) == (COURSE_ID, OWNER_ID) else None)
    session = NoSqlSession()

    package, lessons = student_bridge._load_published_content(session, COURSE_ID, USER_ID)

    assert package["id"] == "pkg-1" and package["version"] == 3
    artifact, material = package["entries"]
    assert artifact["kind"] == "artifact"
    assert artifact["scope"] == {"type": "lesson", "lessonId": "L1"}
    assert artifact["citations"] == [{"source": "s"}]
    assert artifact["resourceType"] == "courseware"
    assert material["url"] == "http://t:3200/api/course-space/canonical/materials/m1"
    assert session.queries == 0

    assert len(lessons) == 1
    lesson = lessons[0]
    assert lesson["id"] == "L1" and lesson["week"] == 1
    assert lesson["classroom"]["playerUrl"] == "http://t:3200/classroom-player/room-1"
    assert lesson["classroom"]["playbackToken"]
    scene = lesson["classroom"]["scenes"][0]
    assert scene["visibleText"] == ["要点"]
    assert scene["actions"] == [{"id": "a", "type": "speech", "text": "旁白"}]


def test_api_mode_unpublished_returns_none(monkeypatch):
    monkeypatch.setattr(student_bridge.settings, "TEACHER_LEARNING_CONTENT_READ_MODE", "api")
    monkeypatch.setattr(
        teacher_learning_content_client, "get_teacher_published_content",
        lambda *_: None)
    package, lessons = student_bridge._load_published_content(NoSqlSession(), COURSE_ID, USER_ID)
    assert package is None and lessons == []


def test_shadow_keeps_legacy_result_on_mismatch(monkeypatch):
    monkeypatch.setattr(student_bridge.settings, "TEACHER_LEARNING_CONTENT_READ_MODE", "shadow")
    legacy_package = {"id": "pkg-1", "version": 2, "entries": []}
    monkeypatch.setattr(student_bridge, "_published_package_payload",
                        lambda _s, _c: legacy_package)
    monkeypatch.setattr(student_bridge, "_published_lessons", lambda _s, _c, _u: [])
    monkeypatch.setattr(teacher_learning_content_client, "get_teacher_published_content",
                        lambda *_: snapshot())
    package, lessons = student_bridge._load_published_content(NoSqlSession(), COURSE_ID, USER_ID)
    assert package is legacy_package and lessons == []


def test_shadow_keeps_legacy_result_during_teacher_outage(monkeypatch):
    monkeypatch.setattr(student_bridge.settings, "TEACHER_LEARNING_CONTENT_READ_MODE", "shadow")
    legacy_package = {"id": "pkg-1", "version": 2, "entries": []}
    monkeypatch.setattr(student_bridge, "_published_package_payload",
                        lambda _s, _c: legacy_package)
    monkeypatch.setattr(student_bridge, "_published_lessons", lambda _s, _c, _u: [])

    def unavailable(*_args):
        raise teacher_learning_content_client.TeacherLearningContentUnavailable()

    monkeypatch.setattr(teacher_learning_content_client,
                        "get_teacher_published_content", unavailable)
    package, lessons = student_bridge._load_published_content(NoSqlSession(), COURSE_ID, USER_ID)
    assert package is legacy_package and lessons == []


def test_api_mode_fails_closed_when_teacher_unavailable(monkeypatch):
    monkeypatch.setattr(student_bridge.settings, "TEACHER_LEARNING_CONTENT_READ_MODE", "api")

    def unavailable(*_args):
        raise teacher_learning_content_client.TeacherLearningContentUnavailable()

    monkeypatch.setattr(teacher_learning_content_client,
                        "get_teacher_published_content", unavailable)
    with pytest.raises(HTTPException) as error:
        student_bridge._load_published_content(NoSqlSession(), COURSE_ID, USER_ID)
    assert error.value.status_code == 503


def test_api_mode_maps_missing_snapshot_to_legacy_404(monkeypatch):
    monkeypatch.setattr(student_bridge.settings, "TEACHER_LEARNING_CONTENT_READ_MODE", "api")

    def missing(*_args):
        raise teacher_learning_content_client.TeacherLearningContentMissing()

    monkeypatch.setattr(teacher_learning_content_client,
                        "get_teacher_published_content", missing)
    with pytest.raises(HTTPException) as error:
        student_bridge._load_published_content(NoSqlSession(), COURSE_ID, USER_ID)
    assert error.value.status_code == 404
    assert error.value.detail == "课堂不存在或尚未发布"


def test_generated_call_carries_service_key_and_course_owner(monkeypatch):
    captured = {}

    def generated_call(course_id, *, client):
        headers = client.get_httpx_client().headers
        captured.update(course_id=course_id, key=headers["X-Platform-Service-Key"],
                        subject=headers["X-Platform-Subject"])
        return SimpleNamespace(status_code=200, parsed=GetTeacherPublishedContentResponse200(
            published=False, content=None))

    monkeypatch.setattr(teacher_learning_content_client.settings, "TEACHER_SERVICE_KEY", "test-key")
    monkeypatch.setattr(teacher_learning_content_client, "sync_detailed", generated_call)
    assert teacher_learning_content_client.get_teacher_published_content(
        COURSE_ID, OWNER_ID) is None
    assert captured == {"course_id": str(COURSE_ID), "key": "test-key",
                        "subject": str(OWNER_ID)}


def test_generated_call_maps_statuses_and_rejects_wrong_shape(monkeypatch):
    monkeypatch.setattr(teacher_learning_content_client.settings, "TEACHER_SERVICE_KEY", "test-key")
    monkeypatch.setattr(
        teacher_learning_content_client, "sync_detailed",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=404, parsed=None))
    with pytest.raises(teacher_learning_content_client.TeacherLearningContentMissing):
        teacher_learning_content_client.get_teacher_published_content(COURSE_ID, OWNER_ID)
    monkeypatch.setattr(
        teacher_learning_content_client, "sync_detailed",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=503, parsed=None))
    with pytest.raises(teacher_learning_content_client.TeacherLearningContentUnavailable):
        teacher_learning_content_client.get_teacher_published_content(COURSE_ID, OWNER_ID)
    monkeypatch.setattr(
        teacher_learning_content_client, "sync_detailed",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=200, parsed="not-a-model"))
    with pytest.raises(teacher_learning_content_client.TeacherLearningContentUnavailable):
        teacher_learning_content_client.get_teacher_published_content(COURSE_ID, OWNER_ID)
