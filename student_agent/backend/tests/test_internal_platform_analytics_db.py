"""Student learning read APIs against the isolated app_test database."""

import os
import uuid
from urllib.parse import urlparse

import pytest

from agent import database
from backend import internal_platform


def test_student_analytics_matches_persisted_rows(monkeypatch):
    url = os.environ.get("DECOUPLING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DECOUPLING_TEST_DATABASE_URL not configured")
    parsed = urlparse(url)
    assert parsed.path == "/app_test" and parsed.port == 55433
    assert parsed.username == "student"
    monkeypatch.setenv("STUDENT_DATABASE_URL", url)
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "integration-test-key")
    course_id, user_id, session_key = (str(uuid.uuid4()) for _ in range(3))
    database.upsert_session(session_key, user_id, course_id, "publication", 2, "classroom")
    database.upsert_mastery(
        session_key, user_id, course_id, "publication", "point", 3, "掌握",
    )
    database.record_event(
        session_key, user_id, course_id, "publication", "lesson_started", {},
        classroom_id="classroom", event_id="test-event",
    )
    progress = internal_platform.user_course_progress(
        course_id, user_id, "integration-test-key",
    )
    assert {key: progress[key] for key in (
        "learnedLessons", "sessionCount", "endedSessions", "stars",
    )} == {"learnedLessons": 1, "sessionCount": 1, "endedSessions": 0, "stars": 3}
    data = internal_platform.course_learning_data(
        course_id, internal_platform.LearningDataRequest(userIds=[user_id]),
        "integration-test-key",
    )
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["sessionKey"] == session_key
    assert data["mastery"][0]["stars"] == 3
    assert data["eventSummary"] == {"lesson_started": 1}
