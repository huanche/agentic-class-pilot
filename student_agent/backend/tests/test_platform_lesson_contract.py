"""The current platform returns a catalog before a selected lesson body."""
from conftest import without_trace

from fastapi import BackgroundTasks
import pytest
from pathlib import Path
import sys
import io
from threading import Lock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend import main
from backend.session import service as learning_session
from backend.infrastructure import platform_access
from backend.teaching import service as teaching
from backend.contracts import SessionError


@pytest.mark.parametrize("base", ["http://platform:8080", "http://platform:8080/api/v1"])
def test_platform_context_accepts_shared_or_student_api_base(monkeypatch: pytest.MonkeyPatch, base: str) -> None:
    seen = []

    class Opener:
        def open(self, request, timeout):
            seen.append(request.full_url)
            return io.BytesIO(b'{}')

    monkeypatch.setenv("PLATFORM_AUTH_URL", base)
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    monkeypatch.setattr(platform_access.urllib.request, "build_opener", lambda *args: Opener())
    assert platform_access.platform_context("ticket", "L2") == {}
    assert seen == ["http://platform:8080/api/v1/internal/student/learning-context"]


def _context(selected: str | None = None) -> dict:
    lessons = [
        {"id": "L1", "title": "第一课", "week": 1, "lessonNumber": 1, "segmentCount": 1},
        {"id": "L2", "title": "第二课", "week": 2, "lessonNumber": 1, "segmentCount": 1},
    ]
    result = {
        "userId": "u", "courseId": "c", "courseTitle": "计算机网络",
        "publication": {"id": "p", "version": 1},
        "lessonCatalog": lessons, "selectedLessonId": selected,
        "lessons": [],
    }
    if selected:
        result["lessons"] = [{"id": selected, "title": "第二课", "classroom": {
            "id": "room-2", "playerUrl": "http://teacher/classroom-player/room-2",
            "scenes": [{"id": "scene-2", "order": 1, "visibleText": ["电路交换"], "actions": []}],
        }}]
    return result


def test_catalog_uses_published_courseware_title_for_lesson_card() -> None:
    context = _context()
    context["lessonCatalog"][0]["title"] = "计算机网络概述"
    context["lessonCatalog"][1]["title"] = "电子邮件系统与SMTP协议"
    lessons = learning_session.catalog(context)[0]["lessons"]
    assert [lesson["title"] for lesson in lessons] == ["计算机网络概述", "电子邮件系统与SMTP协议"]


def test_catalog_then_selected_lesson(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    calls = []

    def fake_platform_context(token: str, lesson_id: str | None = None) -> dict:
        calls.append((token, lesson_id))
        return _context(lesson_id)

    monkeypatch.setattr(platform_access, "platform_context", fake_platform_context)
    monkeypatch.setattr(learning_session.persistence, "save", lambda *args: None)
    monkeypatch.setattr(learning_session.persistence, "latest_session_key", lambda *args: None)
    monkeypatch.setattr(learning_session.published_knowledge, "read", lambda *args: None)
    started = main.start(main.StartRequest(launch_token="ticket"))
    sid = started["sessionId"]
    try:
        assert [lesson["id"] for lesson in started["courses"][0]["lessons"]] == ["L1", "L2"]
        assert started["courses"][0]["lessons"][1]["playerUrl"] is None

        tasks = BackgroundTasks()
        state = main.begin(sid, "L2", tasks)
        assert state["phase"] == "video"
        assert state["courses"][0]["lessons"][1]["playerUrl"].endswith("/room-2")
        assert state["courses"][0]["lessons"][0]["playerUrl"] is None
        assert learning_session.sessions[sid]["preparationMaterials"][0]["content"].endswith("电路交换")
        assert calls == [("ticket", None), ("ticket", "L2")]
        assert any(task.func is platform_access.report_learning_progress and task.args[1] == "started"
                   for task in tasks.tasks)
    finally:
        learning_session.sessions.pop(sid, None)
        learning_session.preparing.discard(sid)


def test_selected_lesson_must_match_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    monkeypatch.setattr(platform_access, "platform_context", lambda token, lesson_id=None: _context("L2") if lesson_id else _context())
    monkeypatch.setattr(learning_session.persistence, "save", lambda *args: None)
    sid = main.start(main.StartRequest(launch_token="ticket"))["sessionId"]
    try:
        with pytest.raises(SessionError) as error:
            main.begin(sid, "L1", BackgroundTasks())
        assert error.value.status_code == 409
        assert learning_session.sessions[sid]["phase"] == "idle"
    finally:
        learning_session.sessions.pop(sid, None)


def test_new_launch_resumes_saved_discussion_for_selected_lesson(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDENT_FRESH_SESSION_MODE", "0")
    monkeypatch.setattr(platform_access, "platform_context", lambda token, lesson_id=None: _context(lesson_id))
    monkeypatch.setattr(learning_session.persistence, "save", lambda *args: None)
    lookups = []

    def find_saved(*args):
        lookups.append(args)
        return "saved-session"

    monkeypatch.setattr(learning_session.persistence, "latest_session_key", find_saved)
    saved = {
        "id": "saved-session",
        "context": {"userId": "u", "courseId": "c", "publication": {"id": "p", "version": 1}},
        "courses": learning_session.catalog(_context("L2")),
        "phase": "discussion", "lessonId": "L2", "classroomId": "room-2",
        "messages": [{"role": "assistant", "phase": "recall", "text": "请继续复述电路交换。"}],
        "dialogue": teaching.new_dialogue([{"id": "point-1", "title": "电路交换", "content": "独占链路"}]),
        "preparation": "ready", "lock": Lock(),
    }
    monkeypatch.setattr(learning_session.persistence, "restore", lambda sid: saved if sid == "saved-session" else None)
    sid = main.start(main.StartRequest(launch_token="new-ticket"))["sessionId"]
    try:
        resumed = main.begin(sid, "L2", BackgroundTasks())
        assert resumed["sessionId"] == "saved-session"
        assert resumed["phase"] == "discussion"
        assert without_trace(resumed["messages"]) == without_trace(saved["messages"])
        assert resumed["agentStage"] == "recall"
        assert lookups == [("u", "c", "p", 1, "L2", "room-2")]
        assert sid not in learning_session.sessions
    finally:
        learning_session.sessions.pop(sid, None)
        learning_session.sessions.pop("saved-session", None)


def test_new_launch_resumes_completed_lesson_and_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDENT_FRESH_SESSION_MODE", "0")
    monkeypatch.setattr(platform_access, "platform_context", lambda token, lesson_id=None: _context(lesson_id))
    monkeypatch.setattr(learning_session.persistence, "save", lambda *args: None)
    monkeypatch.setattr(learning_session.persistence, "latest_session_key", lambda *args: "finished-session")
    feedback = {"summary": "已经掌握电路交换"}
    saved = {
        "id": "finished-session",
        "context": {"userId": "u", "courseId": "c", "publication": {"id": "p", "version": 1}},
        "courses": learning_session.catalog(_context("L2")), "phase": "done",
        "lessonId": "L2", "classroomId": "room-2",
        "messages": [{"role": "assistant", "phase": "postclass-open", "text": "继续提问吧。"}],
        "feedback": feedback, "postclassStage": "open", "dialogue": None,
        "lock": Lock(),
    }
    monkeypatch.setattr(learning_session.persistence, "restore", lambda sid: saved if sid == "finished-session" else None)
    sid = main.start(main.StartRequest(launch_token="new-ticket"))["sessionId"]
    try:
        resumed = main.begin(sid, "L2", BackgroundTasks())
        assert resumed["sessionId"] == "finished-session"
        assert resumed["phase"] == "done"
        assert without_trace(resumed["feedback"]) == without_trace(feedback)
        assert resumed["postclassStage"] == "open"
        assert without_trace(resumed["postclassMessages"]) == without_trace(saved["messages"])
    finally:
        learning_session.sessions.pop(sid, None)
        learning_session.sessions.pop("finished-session", None)


def test_new_browser_launch_recovers_saved_lesson_from_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STUDENT_FRESH_SESSION_MODE", raising=False)
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    monkeypatch.setattr(platform_access, "platform_context", lambda token, lesson_id=None: _context(lesson_id))
    monkeypatch.setattr(learning_session.persistence, "save", lambda *args: None)
    monkeypatch.setattr(learning_session.persistence, "latest_session_key", lambda *args: "stored-lesson")
    saved = {
        "id": "stored-lesson",
        "context": {"userId": "u", "courseId": "c", "publication": {"id": "p", "version": 1}},
        "courses": learning_session.catalog(_context("L2")), "phase": "discussion",
        "lessonId": "L2", "classroomId": "room-2",
        "videoRevision": learning_session.video_revision(_context("L2"), "L2"),
        "messages": [{"role": "assistant", "phase": "recall", "text": "继续复述"}],
        "dialogue": teaching.new_dialogue([{"id": "point-1", "title": "电路交换", "content": "独占链路"}]),
        "preparation": "ready", "lock": Lock(),
    }
    monkeypatch.setattr(learning_session.persistence, "restore", lambda sid: saved if sid == "stored-lesson" else None)
    started = main.start(main.StartRequest(launch_token="new-ticket"))
    sid = started["sessionId"]
    try:
        assert started["browserKey"] == "u:c:catalog"
        with pytest.raises(SessionError) as error:
            learning_session.get_session("stored-lesson")
        assert error.value.status_code == 404
        lesson = main.begin(sid, "L2", BackgroundTasks())
        assert lesson["sessionId"] == "stored-lesson"
        assert lesson["phase"] == "discussion"
        assert without_trace(lesson["messages"]) == without_trace(saved["messages"])
    finally:
        learning_session.sessions.pop(sid, None)
        learning_session.sessions.pop("stored-lesson", None)
        learning_session.preparing.discard(sid)


def test_database_lesson_with_old_video_is_reset_before_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STUDENT_FRESH_SESSION_MODE", raising=False)
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    current = _context("L2")
    current["lessons"][0]["publishedAt"] = 200
    previous = _context("L2")
    previous["lessons"][0]["publishedAt"] = 100
    monkeypatch.setattr(platform_access, "platform_context", lambda token, lesson_id=None: current if lesson_id else _context())
    monkeypatch.setattr(learning_session.persistence, "latest_session_key", lambda *args: "old-video-session")
    monkeypatch.setattr(learning_session.persistence, "save", lambda *args: None)
    discarded = []
    monkeypatch.setattr(learning_session.persistence, "discard_lesson_session",
                        lambda old, replacement: discarded.append(old["id"]))
    saved = {
        "id": "old-video-session",
        "context": {"userId": "u", "courseId": "c", "publication": {"id": "p", "version": 1}},
        "courses": learning_session.catalog(previous), "phase": "done", "lessonId": "L2",
        "classroomId": "room-2", "videoRevision": learning_session.video_revision(previous, "L2"),
        "messages": [{"role": "student", "text": "旧回答"}],
        "feedback": {"summary": "旧反馈"}, "dialogue": None, "lock": Lock(),
    }
    monkeypatch.setattr(learning_session.persistence, "restore", lambda sid: saved if sid == "old-video-session" else None)
    sid = main.start(main.StartRequest(launch_token="new-ticket"))["sessionId"]
    try:
        resumed = main.begin(sid, "L2", BackgroundTasks())
        assert resumed["phase"] == "video"
        assert without_trace(resumed["messages"]) == without_trace([])
        assert resumed["feedback"] is None
        assert resumed["videoUpdated"] is True
        assert discarded == ["old-video-session"]
    finally:
        learning_session.sessions.pop(sid, None)
        learning_session.sessions.pop("old-video-session", None)


def test_browser_record_uses_newer_database_lesson(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDENT_FRESH_SESSION_MODE", "1")
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    current = _context("L2")
    monkeypatch.setattr(platform_access, "platform_context", lambda *args: current)
    browser = {
        "id": "browser-lesson", "context": current, "courses": learning_session.catalog(current),
        "phase": "discussion", "lessonId": "L2", "classroomId": "room-2",
        "videoRevision": learning_session.video_revision(current, "L2"),
        "messages": [{"role": "student", "text": "旧浏览器回答"}],
        "dialogue": None, "lock": Lock(),
    }
    snapshot = learning_session.state(browser)["browserSnapshot"]
    newer = dict(browser, id="database-lesson", messages=[{"role": "student", "text": "数据库最新回答"}])
    monkeypatch.setattr(learning_session.persistence, "latest_session_key", lambda *args: "database-lesson")
    monkeypatch.setattr(learning_session.persistence, "restore", lambda sid: newer if sid == "database-lesson" else None)
    try:
        result = main.browser_restore(
            main.BrowserRestoreRequest(snapshot=snapshot, launch_token="ticket"), BackgroundTasks())
        assert result["sessionId"] == "database-lesson"
        assert without_trace(result["messages"]) == without_trace(newer["messages"])
    finally:
        learning_session.sessions.pop("database-lesson", None)


def test_reset_finished_lesson_keeps_other_lessons_and_rejects_old_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDENT_FRESH_SESSION_MODE", "1")
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    current = _context("L2")
    monkeypatch.setattr(platform_access, "platform_context", lambda *args: current)
    deleted = []
    monkeypatch.setattr(learning_session.persistence, "reset_lesson",
                        lambda user, course, lesson, sid, active: deleted.append((user, course, lesson, sid, active)) or [sid])
    monkeypatch.setattr(learning_session.persistence, "latest_session_key", lambda *args: None)
    monkeypatch.setattr(learning_session.persistence, "restore", lambda *args: None)
    session = {
        "id": "finished-lesson", "context": current, "courses": learning_session.catalog(current),
        "phase": "done", "lessonId": "L2", "classroomId": "room-2",
        "messages": [{"role": "student", "text": "原回答"}], "dialogue": None,
        "feedback": {"summary": "原反馈"}, "lock": Lock(),
    }
    other = dict(session, id="other-lesson", lessonId="L1", lock=Lock())
    learning_session.sessions[session["id"]] = session
    learning_session.sessions[other["id"]] = other
    snapshot = learning_session.state(session)["browserSnapshot"]
    try:
        result = main.reset_lesson(
            session["id"], main.ResetLessonRequest(launch_token="ticket"), BackgroundTasks())
        assert result["phase"] == "idle"
        assert result["lessonId"] is None
        assert result["feedback"] is None
        assert deleted == [("u", "c", "L2", "finished-lesson", ["finished-lesson"])]
        assert "finished-lesson" not in learning_session.sessions
        assert "other-lesson" in learning_session.sessions
        with pytest.raises(SessionError) as error:
            main.browser_restore(
                main.BrowserRestoreRequest(snapshot=snapshot, launch_token="ticket"), BackgroundTasks())
        assert error.value.status_code == 404
    finally:
        learning_session.sessions.pop("finished-lesson", None)
        learning_session.sessions.pop("other-lesson", None)
        if 'result' in locals():
            learning_session.sessions.pop(result["sessionId"], None)
