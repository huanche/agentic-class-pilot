"""Browser snapshots restore study progress without database reads."""
from conftest import without_trace
import sys
from pathlib import Path
from threading import Lock

import pytest
from fastapi import BackgroundTasks

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend import main
from backend.session import service as learning_session
from backend.contracts import SessionError
from backend.infrastructure import database
from backend.infrastructure import persistence


def test_signed_browser_snapshot_restores_after_memory_reset(monkeypatch):
    monkeypatch.setenv("STUDENT_FRESH_SESSION_MODE", "1")
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "local-test-key")
    session = {
        "id": "browser-session-1", "context": None,
        "courses": [{"id": "demo", "title": "演示课程", "lessons": []}],
        "phase": "done", "lessonId": "demo-lesson", "messages": [
            {"role": "student", "text": "我的复述", "phase": "recall"}],
        "dialogue": None, "feedback": {"summary": "已完成"},
        "lock": Lock(),
    }
    snapshot = learning_session.state(session)["browserSnapshot"]
    assert learning_session.state(session)["browserKey"] == "demo:demo-lesson"
    monkeypatch.setattr(learning_session.persistence, "restore", lambda *_: pytest.fail("must not read database"))
    learning_session.sessions.clear()
    restored = main.browser_restore(main.BrowserRestoreRequest(snapshot=snapshot), BackgroundTasks())
    assert restored["sessionId"] == session["id"]
    assert without_trace(restored["messages"]) == without_trace(session["messages"])
    assert without_trace(restored["feedback"]) == without_trace(session["feedback"])
    assert learning_session.get_session(session["id"])["phase"] == "done"
    learning_session.sessions.clear()


def test_modified_browser_snapshot_is_rejected(monkeypatch):
    monkeypatch.setenv("STUDENT_FRESH_SESSION_MODE", "1")
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "local-test-key")
    with pytest.raises(SessionError) as captured:
        main.browser_restore(main.BrowserRestoreRequest(snapshot="abc.def"), BackgroundTasks())
    assert captured.value.status_code == 400


def test_browser_snapshot_uses_independent_key_and_accepts_legacy_signature(monkeypatch):
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "channel-key")
    monkeypatch.delenv("STUDENT_TOKEN_SIGNING_KEY", raising=False)
    session = {"id": "legacy-session", "courses": [], "messages": [], "phase": "idle"}
    legacy = learning_session._browser_snapshot(session)
    monkeypatch.setenv("STUDENT_TOKEN_SIGNING_KEY", "snapshot-key")
    assert learning_session._restore_browser_snapshot(legacy)["id"] == "legacy-session"
    current = learning_session._browser_snapshot(session)
    assert current != legacy
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "different-channel-key")
    assert learning_session._restore_browser_snapshot(current)["id"] == "legacy-session"
