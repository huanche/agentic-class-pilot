"""Platform keeps access decisions while student service owns learning rows."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import student_bridge
from app.generated.platform_teacher_api.models import (
    GetTeacherPublicationCountsResponse200,
)
from app.services import student_analytics_client, teacher_analytics_client

COURSE_ID = uuid.UUID(int=1)
USER_ID = uuid.UUID(int=2)


def test_api_learning_data_uses_only_platform_owned_queries(monkeypatch):
    monkeypatch.setattr(student_bridge.settings, "STUDENT_ANALYTICS_READ_MODE", "api")
    monkeypatch.setattr(student_bridge, "get_accessible_course", lambda *_args: None)
    captured = []
    monkeypatch.setattr(
        student_analytics_client, "get_course_learning_data",
        lambda course_id, users: captured.append((course_id, users)) or {
            "sessions": [{"sessionKey": "saved"}], "mastery": [], "eventSummary": {},
        },
    )

    class Session:
        def execute(self, statement, _params):
            sql = str(statement)
            assert "student." not in sql
            if "enrollment" in sql:
                return SimpleNamespace(fetchall=lambda: [(USER_ID,)])
            assert "teacher.mentra_course_artifacts" in sql
            return SimpleNamespace(first=lambda: (2,))

    result = student_bridge.course_learning_data(
        COURSE_ID, Session(), SimpleNamespace(role="teacher", is_superuser=False),
    )
    assert captured == [(COURSE_ID, [str(USER_ID)])]
    assert result == {"publishedLessons": 2, "sessions": [{"sessionKey": "saved"}],
                      "mastery": [], "eventSummary": {}}


def test_api_progress_uses_student_metrics_and_teacher_total(monkeypatch):
    monkeypatch.setattr(student_bridge.settings, "STUDENT_ANALYTICS_READ_MODE", "api")
    monkeypatch.setattr(
        student_analytics_client, "get_user_course_progress",
        lambda *_args: {"learnedLessons": 1, "sessionCount": 2,
                        "endedSessions": 1, "lastActiveAt": None, "stars": 3},
    )

    class Session:
        def execute(self, statement, _params):
            assert "student." not in str(statement)
            return SimpleNamespace(first=lambda: (2,))

    result = student_bridge._course_learning_progress(Session(), USER_ID, COURSE_ID)
    assert result == {"totalLessons": 2, "learnedLessons": 1, "sessionCount": 2,
                      "endedSessions": 1, "lastActiveAt": None, "stars": 3,
                      "percent": 50}


def test_api_progress_fails_closed_on_student_outage(monkeypatch):
    monkeypatch.setattr(student_bridge.settings, "STUDENT_ANALYTICS_READ_MODE", "api")

    def unavailable(*_args):
        raise student_analytics_client.StudentAnalyticsUnavailable()

    monkeypatch.setattr(student_analytics_client, "get_user_course_progress", unavailable)

    class Session:
        def execute(self, *_args):
            return SimpleNamespace(first=lambda: (2,))

    with pytest.raises(HTTPException) as error:
        student_bridge._course_learning_progress(Session(), USER_ID, COURSE_ID)
    assert error.value.status_code == 503


def test_teacher_course_owner_comes_from_platform_course():
    class Session:
        def execute(self, statement, _params):
            assert "teacher." not in str(statement)
            assert "FROM course" in str(statement)
            return SimpleNamespace(first=lambda: (USER_ID,))

    assert student_bridge._teacher_course_owner(Session(), COURSE_ID) == str(USER_ID)


def test_both_api_modes_avoid_teacher_and_student_tables(monkeypatch):
    monkeypatch.setattr(student_bridge.settings, "STUDENT_ANALYTICS_READ_MODE", "api")
    monkeypatch.setattr(student_bridge.settings, "TEACHER_ANALYTICS_READ_MODE", "api")
    monkeypatch.setattr(
        student_bridge, "get_accessible_course",
        lambda *_args: SimpleNamespace(owner_id=USER_ID),
    )
    monkeypatch.setattr(
        teacher_analytics_client, "get_teacher_publication_counts",
        lambda *_args: {"distinctClassrooms": 2,
                        "publishedArtifactsWithClassroom": 3},
    )
    monkeypatch.setattr(
        student_analytics_client, "get_course_learning_data",
        lambda *_args: {"sessions": [], "mastery": [], "eventSummary": {}},
    )
    monkeypatch.setattr(
        student_analytics_client, "get_user_course_progress",
        lambda *_args: {"learnedLessons": 1, "sessionCount": 1,
                        "endedSessions": 0, "lastActiveAt": None, "stars": 0},
    )

    class PlatformSession:
        def execute(self, statement, _params):
            assert "teacher." not in str(statement) and "student." not in str(statement)
            assert "enrollment" in str(statement)
            return SimpleNamespace(fetchall=lambda: [(USER_ID,)])

        def get(self, _model, _course_id):
            return SimpleNamespace(owner_id=USER_ID)

    session = PlatformSession()
    view = student_bridge.course_learning_data(
        COURSE_ID, session, SimpleNamespace(role="teacher", is_superuser=False),
    )
    assert view["publishedLessons"] == 2
    progress = student_bridge._course_learning_progress(session, USER_ID, COURSE_ID)
    assert progress["totalLessons"] == 3
    assert progress["percent"] == 33


def test_teacher_counts_generated_client_keeps_delegated_owner(monkeypatch):
    monkeypatch.setattr(teacher_analytics_client.settings, "TEACHER_SERVICE_KEY", "test-key")
    captured = {}

    def generated_call(course_id, *, client):
        captured["courseId"] = course_id
        captured["key"] = client.get_httpx_client().headers["X-Platform-Service-Key"]
        captured["owner"] = client.get_httpx_client().headers["X-Platform-Subject"]
        return SimpleNamespace(status_code=200, parsed=GetTeacherPublicationCountsResponse200(
            distinct_classrooms=2, published_artifacts_with_classroom=3,
        ))

    monkeypatch.setattr(teacher_analytics_client, "sync_detailed", generated_call)
    result = teacher_analytics_client.get_teacher_publication_counts(COURSE_ID, USER_ID)
    assert result == {"distinctClassrooms": 2, "publishedArtifactsWithClassroom": 3}
    assert captured == {"courseId": str(COURSE_ID), "key": "test-key",
                        "owner": str(USER_ID)}
