"""Browser snapshots restore study progress without database reads."""
import sys
from pathlib import Path
from threading import Lock

import pytest
from fastapi import BackgroundTasks, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend import main
from agent import database, persistence


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
    restored = main.browser_restore(main.BrowserRestoreRequest(snapshot=snapshot), BackgroundTasks())
    assert restored["sessionId"] == session["id"]
    assert restored["messages"] == session["messages"]
    assert restored["feedback"] == session["feedback"]
    assert main.get_session(session["id"])["phase"] == "done"
    main.sessions.clear()


def test_modified_browser_snapshot_is_rejected(monkeypatch):
    monkeypatch.setenv("STUDENT_FRESH_SESSION_MODE", "1")
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "local-test-key")
    with pytest.raises(HTTPException) as captured:
        main.browser_restore(main.BrowserRestoreRequest(snapshot="abc.def"), BackgroundTasks())
    assert captured.value.status_code == 400


def test_browser_snapshot_uses_independent_key_and_accepts_legacy_signature(monkeypatch):
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "channel-key")
    monkeypatch.delenv("STUDENT_TOKEN_SIGNING_KEY", raising=False)
    session = {"id": "legacy-session", "courses": [], "messages": [], "phase": "idle"}
    legacy = main._browser_snapshot(session)
    monkeypatch.setenv("STUDENT_TOKEN_SIGNING_KEY", "snapshot-key")
    assert main._restore_browser_snapshot(legacy)["id"] == "legacy-session"
    current = main._browser_snapshot(session)
    assert current != legacy
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "different-channel-key")
    assert main._restore_browser_snapshot(current)["id"] == "legacy-session"


def test_default_mode_still_writes_progress_without_reading_prior_mastery(monkeypatch):
    monkeypatch.delenv("STUDENT_FRESH_SESSION_MODE", raising=False)
    monkeypatch.setattr(persistence, "_bind_database", lambda: None)
    monkeypatch.setattr(database, "read_mastery", lambda *args: pytest.fail("must not read prior mastery"))
    monkeypatch.setattr(database, "upsert_session", lambda **kwargs: None)
    monkeypatch.setattr(database, "upsert_message", lambda **kwargs: None)
    written = []
    monkeypatch.setattr(database, "upsert_mastery", lambda **kwargs: written.append(kwargs))
    monkeypatch.setattr(database, "record_event", lambda **kwargs: written.append(kwargs))
    session = {
        "id": "new-browser-session", "context": {
            "userId": "u", "courseId": "c", "publication": {"id": "p", "version": 1}},
        "courses": [], "phase": "video", "lessonId": "L1", "classroomId": "room-1",
        "messages": [], "dialogue": {"points": [{
            "id": "point-1", "status": "mastered", "source": "published-classroom-scene"}]},
    }
    persistence.save(session, 0)
    assert any(item.get("knowledge_point_id") == "point-1" for item in written)
    assert any(item.get("event_type") == "agent_state" for item in written)
