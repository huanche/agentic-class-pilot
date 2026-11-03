"""Contract and access tests for student-owned teacher chat records."""

from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import internal_platform


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeConnection:
    def __init__(self):
        self.revoked = False

    def execute(self, sql, params):
        if "SELECT 1 FROM student.student_sessions" in sql:
            return Rows([] if self.revoked or "student-a" not in params[2] else [(1,)])
        if "FROM student.student_messages WHERE" in sql:
            if "phase=%s" in sql and "other" in params:
                return Rows([])
            return Rows([(1, "student", "recall", "hello", datetime(2026, 1, 1, tzinfo=timezone.utc))])
        if "FROM student.student_sessions s" in sql:
            if "student-a" not in params[1] or self.revoked:
                return Rows([])
            now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            return Rows([("session-a", "student-a", "room-a", now, now, None, "lesson-a", 1)])
        raise AssertionError(sql)


def test_chat_records_enforce_service_key_student_scope_and_revocation(monkeypatch):
    connection = FakeConnection()

    @contextmanager
    def db():
        yield connection

    monkeypatch.setattr(internal_platform, "_db", db)
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-service-key")
    app = FastAPI()
    app.include_router(internal_platform.router)
    client = TestClient(app)
    base = "/api/internal/platform/courses/course-a/chat-sessions"
    headers = {"X-Student-Service-Key": "test-service-key"}
    assert client.post(base, json={"userIds": ["student-a"]}).status_code == 403
    assert client.post(base, headers=headers, json={"userIds": ["student-b"]}).json() == []
    rows = client.post(base, headers=headers, json={"userIds": ["student-a"]}).json()
    assert rows[0]["sessionKey"] == "session-a"
    path = base + "/session-a/messages"
    assert client.post(path, headers=headers, json={"userIds": ["student-b"]}).status_code == 404
    assert client.post(path, headers=headers, json={"userIds": ["student-a"]}).json()[0]["content"] == "hello"
    assert client.post(path, headers=headers, json={"userIds": ["student-a"], "phase": "other"}).json() == []
    connection.revoked = True
    assert client.post(path, headers=headers, json={"userIds": ["student-a"]}).status_code == 404
    assert client.post(base, headers=headers, json={"userIds": ["student-a"]}).json() == []
