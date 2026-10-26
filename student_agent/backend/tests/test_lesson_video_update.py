"""A replacement published video invalidates only its own learning session."""
import copy

import pytest
from fastapi import BackgroundTasks, HTTPException

from test_platform_lesson_contract import _context
from backend import main


@pytest.fixture
def lesson_session(monkeypatch):
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    monkeypatch.setenv("STUDENT_FRESH_SESSION_MODE", "1")
    current = _context("L2")
    current["lessons"][0]["publishedAt"] = 100
    monkeypatch.setattr(main, "platform_context", lambda *args: copy.deepcopy(current))
    monkeypatch.setattr(main.persistence, "save", lambda *args: None)
    monkeypatch.setattr(main.persistence, "latest_session_key", lambda *args: None)
    monkeypatch.setattr(main.persistence, "restore", lambda sid: main.sessions.get(sid))
    deleted = []
    monkeypatch.setattr(main.persistence, "discard_lesson_session", lambda s, replacement: deleted.append(s["id"]), raising=False)
    sid = main.start(main.StartRequest(launch_token="ticket"))["sessionId"]
    main.begin(sid, "L2", BackgroundTasks())
    session = main.sessions[sid]
    session.update(phase="done", preparation="ready", feedback={"schemaVersion": 3},
                   postclassStage="open", messages=[{"role": "student", "text": "旧回答"}])
    snapshot = main.state(session)["browserSnapshot"]
    yield current, session, snapshot, deleted
    main.sessions.pop(sid, None)
    main.preparing.discard(sid)


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
    assert restored["messages"] == []
    assert restored["feedback"] is None
    assert restored["postclassStage"] is None
    assert restored["preparation"] == "pending"
    assert deleted == [session["id"]]
    # An older tab must not resurrect the obsolete signed snapshot.
    again = main.browser_restore(main.BrowserRestoreRequest(snapshot=snapshot, launch_token="ticket"), BackgroundTasks())
    assert again["messages"] == []
    assert len(deleted) == 1


def test_other_publication_changes_keep_this_lessons_progress(lesson_session):
    current, session, snapshot, deleted = lesson_session
    current["publication"]["version"] += 1
    restored = main.browser_restore(main.BrowserRestoreRequest(snapshot=snapshot, launch_token="ticket"), BackgroundTasks())
    assert restored["messages"] == session["messages"]
    assert restored["phase"] == "done"
    assert deleted == []


def test_failed_version_check_preserves_record(lesson_session, monkeypatch):
    _, session, snapshot, deleted = lesson_session
    def unavailable(*args):
        raise HTTPException(503, "temporary failure")
    monkeypatch.setattr(main, "platform_context", unavailable)
    with pytest.raises(HTTPException):
        main.browser_restore(main.BrowserRestoreRequest(snapshot=snapshot, launch_token="ticket"), BackgroundTasks())
    assert session["messages"]
    assert deleted == []


def test_old_background_extraction_cannot_overwrite_new_video(lesson_session, monkeypatch):
    _, session, _, _ = lesson_session
    def finish_old_extraction(materials):
        session.update(contentGeneration=1, dialogue=None, preparation="pending")
        return {"points": [{"title": "旧知识点"}]}, {
            "acceptedCount": 1, "rejectedCount": 0, "repairAttempted": False, "partial": False}
    monkeypatch.setattr(main, "prepared_dialogue", finish_old_extraction)
    main.prepare_in_background(session)
    assert session["dialogue"] is None
    assert session["preparation"] == "pending"


def test_reset_database_writes_are_scoped_and_exclude_launch_secret(monkeypatch):
    from agent import persistence, database
    from test_database_writes import StrictConnection
    connection = StrictConnection()
    monkeypatch.setattr(persistence, "_bind_database", lambda: None)
    monkeypatch.setattr(database, "_db", lambda: connection)
    replacement = {"id": "s", "context": _context("L2"), "classroomId": "room-2",
                   "phase": "video", "messages": [], "launchToken": "secret-token"}
    persistence.discard_lesson_session({"id": "s"}, replacement)
    deletes = [(sql, args) for sql, args in connection.statements if sql.startswith("DELETE")]
    assert len(deletes) == 7
    assert all(args == ("s", "u", "c") for sql, args in deletes)
    assert "secret-token" not in connection.statements[-1][1][-1]


def test_manual_reset_deletes_only_selected_students_lesson_sessions(monkeypatch):
    from agent import persistence, database
    from test_database_writes import StrictConnection

    class ResetConnection(StrictConnection):
        def execute(self, query, params):
            super().execute(query, params)
            if query.startswith("SELECT DISTINCT"):
                return type("Rows", (), {"fetchall": lambda self: [("older-session",)]})()

    connection = ResetConnection()
    monkeypatch.setattr(persistence, "_bind_database", lambda: None)
    monkeypatch.setattr(database, "_db", lambda: connection)
    keys = persistence.reset_lesson("student", "course", "L2", "current-session")
    assert keys == ["current-session", "older-session"]
    deletes = [(sql, args) for sql, args in connection.statements if sql.startswith("DELETE")]
    assert len(deletes) == 7
    assert all(args == (keys, "student", "course") for _, args in deletes)
