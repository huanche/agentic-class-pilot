"""Generated platform client keeps service identity and errors explicit."""

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agent import platform_client
from backend import main


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
