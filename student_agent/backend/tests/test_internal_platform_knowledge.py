"""The authenticated student command owns the durable insert."""

import pytest
from fastapi import HTTPException

from backend import internal_platform


def test_student_knowledge_queue_rejects_bad_service_key(monkeypatch):
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    body = internal_platform.PublishedLessonKnowledgeRequest(
        courseId="course", lessonId="lesson", videoRevision="a" * 64,
        classroomId="classroom", scenes=[],
    )
    with pytest.raises(HTTPException) as failure:
        internal_platform.enqueue_published_lesson_knowledge(body, "wrong")
    assert failure.value.status_code == 403


def test_student_knowledge_queue_inserts_only_student_table(monkeypatch):
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    statements = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, params):
            statements.append((statement, params))

    monkeypatch.setattr(internal_platform, "_db", Connection)
    body = internal_platform.PublishedLessonKnowledgeRequest(
        courseId="course", lessonId="lesson", videoRevision="a" * 64,
        classroomId="classroom", scenes=[{"id": "slide"}],
    )
    result = internal_platform.enqueue_published_lesson_knowledge(body, "test-key")
    assert result == {"courseId": "course", "lessonId": "lesson",
                      "videoRevision": "a" * 64}
    assert len(statements) == 1
    assert "INSERT INTO student.published_lesson_knowledge" in statements[0][0]
    assert "ON CONFLICT" in statements[0][0]
    assert statements[0][1][:4] == ("course", "lesson", "a" * 64, "classroom")


def test_program_course_name_is_stored_with_job(monkeypatch):
    from contextlib import contextmanager
    from backend import internal_platform
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    captured = []
    class Connection:
        def execute(self, sql, args):
            captured.append((sql, args))
    @contextmanager
    def db():
        yield Connection()
    monkeypatch.setattr(internal_platform, "_db", db)
    body = internal_platform.PublishedLessonKnowledgeRequest(
        courseId="c", courseName=" 数据结构 ", lessonId="l", videoRevision="a"*64,
        classroomId="room", scenes=[])
    internal_platform.enqueue_published_lesson_knowledge(body, "test-key")
    assert captured[0][1][-1].obj == {"courseName": "数据结构"}
    assert "EXCLUDED.coverage" in captured[0][0]
