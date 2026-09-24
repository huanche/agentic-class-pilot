"""Student bridge: launch-token and authorize semantics (no external services)."""
import time

import pytest
from fastapi.testclient import TestClient

from app.api.routes.student_bridge import issue_launch_token, verify_launch_token
from app.core.config import settings

BRIDGE_KEY = "student-bridge-test-key"


@pytest.fixture(autouse=True)
def bridge_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "STUDENT_SERVICE_KEY", BRIDGE_KEY)


def _token(exp_offset: int = 600) -> str:
    # Bypass the settings TTL for expired-token crafting via direct issue + expiry edit.
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings, "STUDENT_LAUNCH_TOKEN_TTL_SECONDS", exp_offset)
    try:
        return issue_launch_token("00000000-0000-0000-0000-000000000001",
                                  "00000000-0000-0000-0000-000000000002",
                                  "cls-1", {"publicationId": "pkg-1", "version": 3})
    finally:
        monkeypatch.undo()


def test_launch_token_roundtrip() -> None:
    payload = verify_launch_token(_token())
    assert payload["uid"] == "00000000-0000-0000-0000-000000000001"
    assert payload["cid"] == "00000000-0000-0000-0000-000000000002"
    assert payload["rid"] == "cls-1"
    assert payload["pub"] == {"publicationId": "pkg-1", "version": 3}


def test_launch_token_tamper_rejected() -> None:
    token = _token()
    with pytest.raises(Exception):
        verify_launch_token(token[:-2] + "zz")
    with pytest.raises(Exception):
        verify_launch_token("garbage")
    with pytest.raises(Exception):
        verify_launch_token("eyJ1aWQiOiJ4In0.deadbeef")


def test_launch_token_expiry_rejected() -> None:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings, "STUDENT_LAUNCH_TOKEN_TTL_SECONDS", -10)
    try:
        expired = issue_launch_token("00000000-0000-0000-0000-000000000001",
                                     "00000000-0000-0000-0000-000000000002",
                                     "cls-1", {"publicationId": "pkg-1", "version": 1})
    finally:
        monkeypatch.undo()
    with pytest.raises(Exception):
        verify_launch_token(expired)


def test_authorize_rejects_wrong_service_key(client: TestClient) -> None:
    response = client.post("/api/v1/internal/student/authorize",
                           json={"cookie": None, "launch_token": None})
    assert response.status_code == 403


def test_authorize_rejects_launch_token_without_enrollment(client: TestClient) -> None:
    token = issue_launch_token("00000000-0000-0000-0000-000000000001",
                               "00000000-0000-0000-0000-000000000002",
                               "cls-1", {"publicationId": "pkg-1", "version": 3})
    response = client.post("/api/v1/internal/student/authorize",
                           headers={"X-Student-Service-Key": BRIDGE_KEY},
                           json={"launch_token": token})
    # valid signature, but the enrollment re-check finds no matching row -> denied
    assert response.status_code == 403
