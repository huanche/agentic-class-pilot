"""Generated platform client keeps service identity and errors explicit."""

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from agent import platform_client
from backend import main


USER_ID = "00000000-0000-0000-0000-000000000001"
COURSE_ID = "00000000-0000-0000-0000-000000000002"


def test_generated_learning_context_uses_service_header_and_exact_body(monkeypatch):
    monkeypatch.setenv("PLATFORM_AUTH_URL", "http://platform:8080/api/v1")
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    captured = {}

    def call(*, client, body):
        http_client = client.get_httpx_client()
        captured.update(
            base_url=str(http_client.base_url),
            service_key=http_client.headers["X-Student-Service-Key"],
            body=body.to_dict(),
        )
        return SimpleNamespace(
            status_code=200,
            parsed=object(),
            content=json.dumps({"schemaVersion": 1, "newOptionalField": True}).encode(),
        )

    monkeypatch.setattr(platform_client, "sync_detailed", call)
    assert platform_client.learning_context("ticket", "L2", True) == {
        "schemaVersion": 1, "newOptionalField": True
    }
    assert captured == {
        "base_url": "http://platform:8080/api/v1/",
        "service_key": "test-key",
        "body": {"launch_token": "ticket", "lesson_id": "L2", "refresh_session": True},
    }


def test_generated_learning_context_keeps_platform_rejection(monkeypatch):
    monkeypatch.setenv("PLATFORM_AUTH_URL", "http://platform:8080")
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    monkeypatch.setattr(
        platform_client,
        "sync_detailed",
        lambda **kwargs: SimpleNamespace(status_code=403, parsed=None, content=b""),
    )
    with pytest.raises(HTTPException) as error:
        platform_client.learning_context("ticket")
    assert error.value.status_code == 403


def test_generated_learning_context_rejects_invalid_success(monkeypatch):
    monkeypatch.setenv("PLATFORM_AUTH_URL", "http://platform:8080")
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    monkeypatch.setattr(
        platform_client,
        "sync_detailed",
        lambda **kwargs: SimpleNamespace(status_code=200, parsed=None, content=b"{}"),
    )
    with pytest.raises(HTTPException) as error:
        platform_client.learning_context("ticket")
    assert error.value.status_code == 503


def test_runtime_switch_only_routes_opted_in_calls(monkeypatch):
    monkeypatch.setenv("STUDENT_PLATFORM_CLIENT_MODE", "generated")
    monkeypatch.setattr(
        platform_client,
        "learning_context",
        lambda token, lesson_id, refresh: {
            "token": token, "lesson": lesson_id, "refresh": refresh
        },
    )
    assert main.platform_context("ticket", "L2", True) == {
        "token": "ticket", "lesson": "L2", "refresh": True
    }


def test_generated_progress_uses_contract_header_body_and_one_request(monkeypatch):
    monkeypatch.setenv("PLATFORM_AUTH_URL", "http://platform:8080")
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    captured = []

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append({
            "url": str(request.url),
            "method": request.method,
            "service_key": request.headers["X-Student-Service-Key"],
            "timeout": request.extensions["timeout"]["read"],
            "body": json.loads(request.content),
        })
        return httpx.Response(200, json={"ok": True, "progress": {}, "pushedToTeacher": False})

    real_client = platform_client.AuthenticatedClient
    transport = httpx.MockTransport(handle)

    def client_with_transport(**kwargs):
        kwargs["httpx_args"] = {**kwargs["httpx_args"], "transport": transport}
        return real_client(**kwargs)

    monkeypatch.setattr(platform_client, "AuthenticatedClient", client_with_transport)
    assert platform_client.report_learning_progress(
        USER_ID, COURSE_ID, "session-1", "room-1", "started"
    ) is False
    assert captured == [{
        "url": "http://platform:8080/api/v1/internal/student/learning-progress",
        "method": "POST",
        "service_key": "test-key",
        "timeout": 8.0,
        "body": {
            "user_id": USER_ID, "course_id": COURSE_ID,
            "session_key": "session-1", "classroom_id": "room-1",
            "event": "started",
        },
    }]


def test_generated_progress_rejects_platform_error(monkeypatch):
    monkeypatch.setenv("PLATFORM_AUTH_URL", "http://platform:8080")
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    monkeypatch.setattr(platform_client, "report_progress_detailed", lambda **kwargs:
                        SimpleNamespace(status_code=403, parsed=None))
    with pytest.raises(HTTPException) as error:
        platform_client.report_learning_progress(USER_ID, COURSE_ID, "session-1", "room-1", "ended")
    assert error.value.status_code == 403


def test_generated_progress_switch_sends_once_without_blocking_class(monkeypatch, caplog):
    monkeypatch.setenv("STUDENT_PLATFORM_CLIENT_MODE", "generated")
    monkeypatch.setenv("PLATFORM_AUTH_URL", "http://platform:8080")
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    sent = []
    monkeypatch.setattr(platform_client, "report_learning_progress", lambda *args:
                        sent.append(args) or False)
    monkeypatch.setattr(main.urllib.request, "build_opener", lambda *args:
                        pytest.fail("legacy progress request must not be sent"))
    session = {"id": "session-1", "classroomId": "room-1",
               "context": {"userId": USER_ID, "courseId": COURSE_ID}}
    main.report_learning_progress(session, "started")
    assert sent == [(USER_ID, COURSE_ID, "session-1", "room-1", "started")]
    assert "teacher sync failed" in caplog.text
