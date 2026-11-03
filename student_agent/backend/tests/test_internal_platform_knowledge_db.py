"""Run only against a dedicated ephemeral app_test database."""

import os
import uuid
from urllib.parse import urlparse

import psycopg
import pytest

from backend import internal_platform


def test_student_role_can_queue_one_durable_job(monkeypatch):
    url = os.environ.get("DECOUPLING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DECOUPLING_TEST_DATABASE_URL not configured")
    parsed = urlparse(url)
    assert parsed.path == "/app_test" and parsed.port == 55433
    assert parsed.username == "student"
    monkeypatch.setenv("STUDENT_DATABASE_URL", url)
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "integration-test-key")
    course_id = str(uuid.uuid4())
    body = internal_platform.PublishedLessonKnowledgeRequest(
        courseId=course_id, lessonId="lesson", videoRevision="b" * 64,
        classroomId="classroom", scenes=[{"id": "slide", "title": "test"}],
    )
    for _ in range(2):
        result = internal_platform.enqueue_published_lesson_knowledge(
            body, "integration-test-key",
        )
        assert result["videoRevision"] == "b" * 64
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT count(*), min(status), min(classroom_id) "
            "FROM student.published_lesson_knowledge WHERE course_id=%s",
            (course_id,),
        ).fetchone()
    assert row == (1, "pending", "classroom")
