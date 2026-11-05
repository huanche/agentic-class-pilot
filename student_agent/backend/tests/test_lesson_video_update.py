"""A replacement published video invalidates only its own learning session."""
from conftest import without_trace
import copy

import pytest
from fastapi import BackgroundTasks

from test_platform_lesson_contract import _context
from backend import main
from backend.session import service as learning_session
from backend.infrastructure import platform_access
from backend.teaching import service as teaching
from backend.contracts import SessionError


@pytest.fixture
def lesson_session(monkeypatch):
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    monkeypatch.setenv("STUDENT_FRESH_SESSION_MODE", "1")
    current = _context("L2")
    current["lessons"][0]["publishedAt"] = 100
    monkeypatch.setattr(platform_access, "platform_context", lambda *args: copy.deepcopy(current))
    monkeypatch.setattr(learning_session.persistence, "save", lambda *args: None)
    monkeypatch.setattr(learning_session.persistence, "latest_session_key", lambda *args: None)
    monkeypatch.setattr(learning_session.persistence, "restore", lambda sid: learning_session.sessions.get(sid))
    monkeypatch.setattr(learning_session.published_knowledge, "read", lambda *args: None)
    deleted = []
    monkeypatch.setattr(learning_session.persistence, "discard_lesson_session", lambda s, replacement: deleted.append(s["id"]), raising=False)
    sid = main.start(main.StartRequest(launch_token="ticket"))["sessionId"]
    main.begin(sid, "L2", BackgroundTasks())
    session = learning_session.sessions[sid]
    session.update(phase="done", preparation="ready", feedback={"schemaVersion": 3},
                   postclassStage="open", messages=[{"role": "student", "text": "旧回答"}])
    snapshot = learning_session.state(session)["browserSnapshot"]
    yield current, session, snapshot, deleted
    learning_session.sessions.pop(sid, None)
    learning_session.preparing.discard(sid)


@pytest.mark.parametrize("change", ["publishedAt", "classroom", "scenes"])
def test_updated_video_discards_old_progress(lesson_session, change):
    current, session, snapshot, deleted = lesson_session
    lesson = current["lessons"][0]
    if change == "publishedAt":
        lesson[change] = 200
    elif change == "classroom":
        lesson["classroom"]["id"] = "new-room"
    else:
        lesson["classroom"]["scenes"][0]["visibleText"] = ["新的视频内容"]
    restored = main.browser_restore(main.BrowserRestoreRequest(snapshot=snapshot, launch_token="ticket"), BackgroundTasks())
    assert restored["phase"] == "video"
    assert without_trace(restored["messages"]) == without_trace([])
    assert restored["feedback"] is None
    assert restored["postclassStage"] is None
    assert restored["preparation"] == "pending"
    assert deleted == [session["id"]]
    # An older tab must not resurrect the obsolete signed snapshot.
    again = main.browser_restore(main.BrowserRestoreRequest(snapshot=snapshot, launch_token="ticket"), BackgroundTasks())
    assert without_trace(again["messages"]) == without_trace([])
    assert len(deleted) == 1


def test_other_publication_changes_keep_this_lessons_progress(lesson_session):
    current, session, snapshot, deleted = lesson_session
    current["publication"]["version"] += 1
    restored = main.browser_restore(main.BrowserRestoreRequest(snapshot=snapshot, launch_token="ticket"), BackgroundTasks())
    assert without_trace(restored["messages"]) == without_trace(session["messages"])
    assert restored["phase"] == "done"
    assert deleted == []


def test_failed_version_check_preserves_record(lesson_session, monkeypatch):
    _, session, snapshot, deleted = lesson_session
    def unavailable(*args):
        raise SessionError(503, "temporary failure")
    monkeypatch.setattr(platform_access, "platform_context", unavailable)
    with pytest.raises(SessionError):
        main.browser_restore(main.BrowserRestoreRequest(snapshot=snapshot, launch_token="ticket"), BackgroundTasks())
    assert session["messages"]
    assert deleted == []


def test_old_background_extraction_cannot_overwrite_new_video(lesson_session, monkeypatch):
    _, session, _, _ = lesson_session
    def finish_old_extraction(materials, *scope):
        session.update(contentGeneration=1, dialogue=None, preparation="pending")
        return {"points": [{"title": "旧知识点"}]}, {
            "acceptedCount": 1, "rejectedCount": 0, "repairAttempted": False, "partial": False}
    monkeypatch.setattr(teaching, "prepare", finish_old_extraction)
    learning_session.prepare_in_background(session)
    assert session["dialogue"] is None
    assert session["preparation"] == "pending"
