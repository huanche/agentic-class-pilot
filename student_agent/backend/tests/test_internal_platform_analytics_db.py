"""Student learning read APIs against the isolated app_test database."""

import os
import uuid
from urllib.parse import urlparse

import pytest
from psycopg.types.json import Jsonb

from backend.infrastructure import database
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


def test_roster_uses_current_revision_and_enrolled_student_scope(monkeypatch):
    url = os.environ.get("DECOUPLING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DECOUPLING_TEST_DATABASE_URL not configured")
    parsed = urlparse(url)
    assert (parsed.path, parsed.port, parsed.username) == ("/app_test", 55433, "student")
    monkeypatch.setenv("STUDENT_DATABASE_URL", url)
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "integration-test-key")
    course, user, other = (str(uuid.uuid4()) for _ in range(3))
    revision, old_revision = "a" * 64, "b" * 64
    keys = [str(uuid.uuid4()) for _ in range(3)]
    with database._db() as conn:
        conn.execute(
            "INSERT INTO student.published_lesson_knowledge "
            "(course_id,lesson_id,video_revision,classroom_id,scenes,status,points) "
            "VALUES (%s,'lesson',%s,'current','[]','ready',%s)",
            (course, revision, Jsonb([{"id": "one", "title": "知识点一"}, {"id": "two"}])),
        )
        conn.commit()
    for key, student, version, classroom, point in (
        (keys[0], user, revision, "current", "one"),
        (keys[1], user, old_revision, "old", "two"),
        (keys[2], other, revision, "current", "two"),
    ):
        database.upsert_session(key, student, course, version, 2, classroom)
        database.upsert_mastery(key, student, course, version, point, 4, "掌握")
        with database._db() as conn:
            conn.execute("UPDATE student.student_sessions SET snapshot=%s WHERE session_key=%s",
                         (Jsonb({"lessonId": "lesson", "videoRevision": version}), key))
            conn.commit()
    data = internal_platform.roster_progress(
        course, internal_platform.RosterRequest(
            userIds=[user], lessonRevisions={"lesson": revision},
            activeSessionKeys=keys, detailUserId=user,
        ), "integration-test-key",
    )
    assert data["totals"] == {"lesson": 2}
    assert data["mastered"] == {user: {"lesson": 1}}
    assert data["active"] == [{"sessionId": keys[0], "studentId": user, "classroomId": "current"}]
    assert [row["pointId"] for row in data["assessments"]] == ["one"]
