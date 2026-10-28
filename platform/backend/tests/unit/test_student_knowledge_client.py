"""The student service owns durable knowledge jobs after the API switch."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import student_bridge
from app.generated.platform_student_api.models import (
    EnqueuePublishedLessonKnowledgeAtStudentResponse200,
)
from app.services import student_knowledge_client


def test_generated_student_queue_preserves_identity_and_service_key(monkeypatch):
    monkeypatch.setattr(student_knowledge_client.settings, "STUDENT_SERVICE_KEY", "test-key")
    captured = {}
    revision = "a" * 64

    def generated_call(*, client, body):
        captured["key"] = client.get_httpx_client().headers["X-Student-Service-Key"]
        captured["body"] = body.to_dict()
        return SimpleNamespace(
            status_code=200,
            parsed=EnqueuePublishedLessonKnowledgeAtStudentResponse200(
                course_id="course", lesson_id="lesson", video_revision=revision,
            ),
        )

    monkeypatch.setattr(student_knowledge_client, "sync_detailed", generated_call)
    student_knowledge_client.enqueue_student_knowledge(
        "course", "lesson", revision, "classroom", [{"id": "slide"}],
    )
    assert captured == {
        "key": "test-key",
        "body": {"courseId": "course", "lessonId": "lesson",
                 "videoRevision": revision, "classroomId": "classroom",
                 "scenes": [{"id": "slide"}]},
    }


def test_student_queue_rejects_mismatched_response(monkeypatch):
    monkeypatch.setattr(student_knowledge_client.settings, "STUDENT_SERVICE_KEY", "test-key")
    monkeypatch.setattr(student_knowledge_client, "sync_detailed", lambda **_kwargs: SimpleNamespace(
        status_code=200,
        parsed=EnqueuePublishedLessonKnowledgeAtStudentResponse200(
            course_id="other", lesson_id="lesson", video_revision="a" * 64,
        ),
    ))
    with pytest.raises(student_knowledge_client.StudentKnowledgeUnavailable):
        student_knowledge_client.enqueue_student_knowledge(
            "course", "lesson", "a" * 64, "classroom", [],
        )


def test_api_mode_does_not_write_student_table_from_platform(monkeypatch):
    monkeypatch.setattr(student_bridge.settings, "STUDENT_KNOWLEDGE_ENQUEUE_MODE", "api")
    called = []
    monkeypatch.setattr(
        student_knowledge_client, "enqueue_student_knowledge",
        lambda *args: called.append(args),
    )

    class NoSqlSession:
        def execute(self, *_args):
            raise AssertionError("platform must not write the student table")

    revision = student_bridge.ensure_published_knowledge_job(
        NoSqlSession(), uuid.UUID(int=1), "lesson", {"id": "classroom", "scenes": []}, 123,
    )
    assert called == [(str(uuid.UUID(int=1)), "lesson", revision, "classroom", [])]


def test_api_mode_fails_closed_on_student_outage(monkeypatch):
    monkeypatch.setattr(student_bridge.settings, "STUDENT_KNOWLEDGE_ENQUEUE_MODE", "api")

    def unavailable(*_args):
        raise student_knowledge_client.StudentKnowledgeUnavailable()

    monkeypatch.setattr(student_knowledge_client, "enqueue_student_knowledge", unavailable)
    with pytest.raises(HTTPException) as failure:
        student_bridge.ensure_published_knowledge_job(
            None, uuid.UUID(int=1), "lesson", {"id": "classroom", "scenes": []}, 123,
        )
    assert failure.value.status_code == 503
