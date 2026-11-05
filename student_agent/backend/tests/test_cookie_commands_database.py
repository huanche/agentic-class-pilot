"""Production internal identity boundary over the real PostgreSQL command ledger."""
from fastapi.testclient import TestClient
import pytest

from backend import main
from backend.infrastructure import persistence
from backend.infrastructure import published_knowledge
from backend.session import service
from test_reliable_commands import active as active
from test_reliable_commands import command


@pytest.fixture
def protected(active, monkeypatch):
    monkeypatch.setenv("PLATFORM_TO_STUDENT_KEY", "test-forward-channel")
    return TestClient(main.app, headers={
        "X-Platform-Learning-Key": "test-forward-channel", "X-Platform-Protocol": "platform-cookie-v1",
        "X-Platform-User-Id": "student", "X-Platform-Course-Id": "course"}), active


def test_same_command_is_saved_once_through_production_middleware(protected):
    client, active = protected
    body = command(active[1])
    first = client.post("/api/session/session/commands", json=body)
    assert first.status_code == 200, first.text
    version = persistence.restore("session")["stateVersion"]
    count = len(active[3])
    repeated = client.post("/api/session/session/commands", json=body)
    assert repeated.status_code == 200
    assert repeated.json()["commandId"] == first.json()["commandId"]
    assert persistence.restore("session")["stateVersion"] == version
    assert len(active[3]) == count


def test_restart_and_foreign_account_cannot_override_database(protected):
    client, _ = protected
    service.sessions.clear()
    response = client.get("/api/session/session")
    assert response.status_code == 200
    assert response.json()["userId"] == "student"
    denied = client.get("/api/session/session", headers={"X-Platform-User-Id": "other"})
    assert denied.status_code == 404


def test_reset_receipt_survives_tombstone_and_lost_response(protected):
    client, active = protected
    saved = persistence.restore("session")
    saved["phase"] = "done"
    persistence.save(saved, len(saved["messages"]))
    body = command(saved, kind="reset_lesson")
    first = client.post("/api/session/session/commands", json=body)
    assert first.status_code == 200, first.text
    service.sessions.clear()
    receipt = client.post(f"/api/session/session/commands/{body['commandId']}/status", json={})
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["sessionView"]["sessionId"] == first.json()["sessionView"]["sessionId"]
    assert client.post("/api/session/session/commands", json=body).status_code == 200


def test_ready_after_video_poll_binds_content_in_command_without_version_conflict(protected, monkeypatch):
    client, active = protected
    pending = {"id": "pending", "context": active[2], "courses": service.catalog(active[2]),
               "phase": "video", "lessonId": "lesson", "classroomId": "room", "messages": [],
               "dialogue": None, "preparation": "pending", "videoRevision": "revision"}
    persistence.save(pending, 0)
    version = pending["stateVersion"]
    monkeypatch.setattr(published_knowledge, "read", lambda *a: {"status": "ready", "points": [
        {"id": "p", "title": "概念", "content": "本课内容"}], "coverage": {}})
    view = client.get("/api/session/pending")
    assert view.status_code == 200, view.text
    assert view.json()["preparation"] == "ready"
    assert persistence.restore("pending")["stateVersion"] == version
    assert persistence.restore("pending")["dialogue"] is None
    body = command(pending, kind="start_discussion")
    entered = client.post("/api/session/pending/commands", json=body)
    assert entered.status_code == 200, entered.text
    assert entered.json()["sessionView"]["phase"] == "discussion"
    saved = persistence.restore("pending")
    assert saved["contentRef"] and saved["phase"] == "discussion"
