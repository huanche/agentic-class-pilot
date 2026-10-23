"""Browser snapshots restore study progress without database reads."""
import sys
from pathlib import Path
from threading import Lock

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend import main


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
    snapshot = main.state(session)["browserSnapshot"]
    assert main.state(session)["browserKey"] == "demo:demo-lesson"
    monkeypatch.setattr(main.persistence, "restore", lambda *_: pytest.fail("must not read database"))
    main.sessions.clear()
    restored = main.browser_restore(main.BrowserRestoreRequest(snapshot=snapshot))
    assert restored["sessionId"] == session["id"]
    assert restored["messages"] == session["messages"]
    assert restored["feedback"] == session["feedback"]
    assert main.get_session(session["id"])["phase"] == "done"
    main.sessions.clear()


def test_modified_browser_snapshot_is_rejected(monkeypatch):
    monkeypatch.setenv("STUDENT_FRESH_SESSION_MODE", "1")
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "local-test-key")
    with pytest.raises(HTTPException) as captured:
        main.browser_restore(main.BrowserRestoreRequest(snapshot="abc.def"))
    assert captured.value.status_code == 400
