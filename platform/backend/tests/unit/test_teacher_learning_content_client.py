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


def test_enqueue_api_mode_maps_reasons_and_course_ref(monkeypatch):
    """① api 模式：登记端点用教师快照替代教师表读取。"""
    from app.api.routes import teacher_bridge

    class Row:
        def __init__(self, values):
            self.values = values

        def first(self):
            return self.values

    class Session:
        def __init__(self):
            self.sql = []

        def execute(self, statement, params):
            sql = str(statement)
            self.sql.append(sql)
            if "owner_id::text FROM course" in sql:
                return Row((str(OWNER_ID),))
            if "SELECT id::text FROM course WHERE" in sql:
                return Row((COURSE_ID,))
            if "teacher_course_link" in sql:
                return Row((COURSE_ID,))
            if "teacher." in sql:
                raise AssertionError(f"teacher SQL in api mode: {sql}")
            raise AssertionError(sql)

    lesson_model = SimpleNamespace(
        course_id="canonical-id", lesson_id="L1", classroom_id="room-1",
        published_at=123,
        classroom=SimpleNamespace(
            id="room-1", title="课堂", scenes=[],
            to_dict=lambda: {"id": "room-1", "title": "课堂", "scenes": []}))

    def fetch_ok():
        return ({"courseId": "canonical-id", "lessonId": "L1", "classroomId": "room-1",
                 "publishedAt": 123, "classroom": lesson_model.classroom}, None)

    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_LEARNING_CONTENT_READ_MODE", "api")
    monkeypatch.setattr(teacher_bridge.settings, "STUDENT_KNOWLEDGE_ENQUEUE_MODE", "legacy")
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_SERVICE_KEY", "test-key")
    monkeypatch.setattr(teacher_bridge, "get_teacher_published_lesson", fetch_ok, raising=False)
    monkeypatch.setattr(
        "app.services.teacher_learning_content_client.get_teacher_published_lesson",
        lambda artifact, owner: fetch_ok())
    enqueued = {}
    monkeypatch.setattr(teacher_bridge, "ensure_published_knowledge_job",
                        lambda session, course, lesson, classroom, published_at:
                        enqueued.update(course=course, lesson=lesson,
                                        classroom=classroom, at=published_at) or "rev-1")
    session = Session()
    body = teacher_bridge.PublishedLessonPreparation(course_id=str(COURSE_ID), artifact_id="a1")
    result = teacher_bridge.enqueue_published_lesson_knowledge(body, session, "test-key")
    assert result == {"lessonId": "L1", "videoRevision": "rev-1"}
    assert str(enqueued["course"]) == str(COURSE_ID)
    assert enqueued["classroom"]["id"] == "room-1"
    assert not any("teacher.mentra" in s for s in session.sql)


def test_enqueue_api_mode_rejects_unpublished(monkeypatch):
    from fastapi import HTTPException as HTTPError
    from app.api.routes import teacher_bridge

    class Row:
        def __init__(self, values):
            self.values = values

        def first(self):
            return self.values

    class Session:
        def execute(self, statement, params):
            return Row((str(OWNER_ID),)) if "owner_id" in str(statement) else Row(None)

    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_LEARNING_CONTENT_READ_MODE", "api")
    monkeypatch.setattr(teacher_bridge.settings, "TEACHER_SERVICE_KEY", "test-key")
    monkeypatch.setattr(
        "app.services.teacher_learning_content_client.get_teacher_published_lesson",
        lambda artifact, owner: (None, "not-published"))
    with pytest.raises(HTTPError) as error:
        teacher_bridge.enqueue_published_lesson_knowledge(
            teacher_bridge.PublishedLessonPreparation(course_id=str(COURSE_ID), artifact_id="a1"),
            Session(), "test-key")
    assert error.value.status_code == 409
    assert error.value.detail == "未找到已发布的教学视频"


def test_classroom_view_endpoint_serves_replay_without_teacher_tables(monkeypatch):
    """③ 平台回放端点：api 模式从教师快照取场景，学生不再有直查路径。"""
    from app.api.routes import student_bridge

    class Row:
        def __init__(self, values):
            self.values = values

        def first(self):
            return self.values

    class Session:
        def execute(self, statement, params):
            if "teacher." in str(statement):
                raise AssertionError("teacher SQL in api mode")
            raise AssertionError(str(statement))

    view_model = SimpleNamespace(
        id="room-1", title="课堂", to_dict=lambda: {
            "id": "room-1", "title": "课堂",
            "scenes": [{"id": "s1", "type": "slide", "order": 1, "title": "页",
                        "visibleText": ["要点"], "actions": []}]})
    monkeypatch.setattr(student_bridge.settings, "TEACHER_LEARNING_CONTENT_READ_MODE", "api")
    monkeypatch.setattr(student_bridge.settings, "STUDENT_SERVICE_KEY", "key")
    monkeypatch.setattr(
        "app.services.teacher_learning_content_client.get_teacher_classroom_view",
        lambda classroom_id: view_model)
    result = student_bridge.student_classroom_view(
        student_bridge.ClassroomViewRequest(classroom_id="room-1"), Session(), "key")
    assert result == {"classroomId": "room-1", "scenes": view_model.to_dict()["scenes"]}


def test_classroom_view_missing_returns_empty_scenes(monkeypatch):
    from app.api.routes import student_bridge

    class Session:
        def execute(self, statement, params):
            raise AssertionError("no SQL expected")

    monkeypatch.setattr(student_bridge.settings, "TEACHER_LEARNING_CONTENT_READ_MODE", "api")
    monkeypatch.setattr(student_bridge.settings, "STUDENT_SERVICE_KEY", "key")
    monkeypatch.setattr(
        "app.services.teacher_learning_content_client.get_teacher_classroom_view",
        lambda classroom_id: None)
    result = student_bridge.student_classroom_view(
        student_bridge.ClassroomViewRequest(classroom_id="missing"), Session(), "key")
    assert result == {"classroomId": "missing", "scenes": []}
