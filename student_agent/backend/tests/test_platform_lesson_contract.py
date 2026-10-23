"""The current platform returns a catalog before a selected lesson body."""

from fastapi import BackgroundTasks, HTTPException
import pytest
from pathlib import Path
import sys
import io
from threading import Lock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend import main


@pytest.mark.parametrize("base", ["http://platform:8080", "http://platform:8080/api/v1"])
def test_platform_context_accepts_shared_or_student_api_base(monkeypatch: pytest.MonkeyPatch, base: str) -> None:
    seen = []

    class Opener:
        def open(self, request, timeout):
            seen.append(request.full_url)
            return io.BytesIO(b'{}')

    monkeypatch.setenv("PLATFORM_AUTH_URL", base)
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    monkeypatch.setattr(main.urllib.request, "build_opener", lambda *args: Opener())
    assert main.platform_context("ticket", "L2") == {}
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


def test_catalog_then_selected_lesson(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    calls = []

    def fake_platform_context(token: str, lesson_id: str | None = None) -> dict:
        calls.append((token, lesson_id))
        return _context(lesson_id)

    monkeypatch.setattr(main, "platform_context", fake_platform_context)
    monkeypatch.setattr(main.persistence, "save", lambda *args: None)
    monkeypatch.setattr(main.persistence, "latest_session_key", lambda *args: None)
    started = main.start(main.StartRequest(launch_token="ticket"))
    sid = started["sessionId"]
    try:
        assert [lesson["id"] for lesson in started["courses"][0]["lessons"]] == ["L1", "L2"]
        assert started["courses"][0]["lessons"][1]["playerUrl"] is None

        state = main.begin(sid, "L2", BackgroundTasks())
        assert state["phase"] == "video"
        assert state["courses"][0]["lessons"][1]["playerUrl"].endswith("/room-2")
        assert state["courses"][0]["lessons"][0]["playerUrl"] is None
        assert main.sessions[sid]["preparationMaterials"][0]["content"].endswith("电路交换")
        assert calls == [("ticket", None), ("ticket", "L2")]
    finally:
        main.sessions.pop(sid, None)
        main.preparing.discard(sid)


def test_selected_lesson_must_match_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    monkeypatch.setattr(main, "platform_context", lambda token, lesson_id=None: _context("L2") if lesson_id else _context())
    monkeypatch.setattr(main.persistence, "save", lambda *args: None)
    sid = main.start(main.StartRequest(launch_token="ticket"))["sessionId"]
    try:
        with pytest.raises(HTTPException) as error:
            main.begin(sid, "L1", BackgroundTasks())
        assert error.value.status_code == 409
        assert main.sessions[sid]["phase"] == "idle"
    finally:
        main.sessions.pop(sid, None)


def test_new_launch_resumes_saved_discussion_for_selected_lesson(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDENT_FRESH_SESSION_MODE", "0")
    monkeypatch.setattr(main, "platform_context", lambda token, lesson_id=None: _context(lesson_id))
    monkeypatch.setattr(main.persistence, "save", lambda *args: None)
    lookups = []

    def find_saved(*args):
        lookups.append(args)
        return "saved-session"

    monkeypatch.setattr(main.persistence, "latest_session_key", find_saved)
    saved = {
        "id": "saved-session",
        "context": {"userId": "u", "courseId": "c", "publication": {"id": "p", "version": 1}},
        "courses": main.catalog(_context("L2")),
        "phase": "discussion", "lessonId": "L2", "classroomId": "room-2",
        "messages": [{"role": "assistant", "phase": "recall", "text": "请继续复述电路交换。"}],
        "dialogue": main.initial_state([{"id": "point-1", "title": "电路交换", "content": "独占链路"}]),
        "preparation": "ready", "lock": Lock(),
    }
    monkeypatch.setattr(main.persistence, "restore", lambda sid: saved if sid == "saved-session" else None)
    sid = main.start(main.StartRequest(launch_token="new-ticket"))["sessionId"]
    try:
        resumed = main.begin(sid, "L2", BackgroundTasks())
        assert resumed["sessionId"] == "saved-session"
        assert resumed["phase"] == "discussion"
        assert resumed["messages"] == saved["messages"]
        assert resumed["agentStage"] == "recall"
        assert lookups == [("u", "c", "p", 1, "L2", "room-2")]
        assert sid not in main.sessions
    finally:
        main.sessions.pop(sid, None)
        main.sessions.pop("saved-session", None)


def test_new_launch_resumes_completed_lesson_and_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDENT_FRESH_SESSION_MODE", "0")
    monkeypatch.setattr(main, "platform_context", lambda token, lesson_id=None: _context(lesson_id))
    monkeypatch.setattr(main.persistence, "save", lambda *args: None)
    monkeypatch.setattr(main.persistence, "latest_session_key", lambda *args: "finished-session")
    feedback = {"summary": "已经掌握电路交换"}
    saved = {
        "id": "finished-session",
        "context": {"userId": "u", "courseId": "c", "publication": {"id": "p", "version": 1}},
        "courses": main.catalog(_context("L2")), "phase": "done",
        "lessonId": "L2", "classroomId": "room-2",
        "messages": [{"role": "assistant", "phase": "postclass-open", "text": "继续提问吧。"}],
        "feedback": feedback, "postclassStage": "open", "dialogue": None,
        "lock": Lock(),
    }
    monkeypatch.setattr(main.persistence, "restore", lambda sid: saved if sid == "finished-session" else None)
    sid = main.start(main.StartRequest(launch_token="new-ticket"))["sessionId"]
    try:
        resumed = main.begin(sid, "L2", BackgroundTasks())
        assert resumed["sessionId"] == "finished-session"
        assert resumed["phase"] == "done"
        assert resumed["feedback"] == feedback
        assert resumed["postclassStage"] == "open"
        assert resumed["postclassMessages"] == saved["messages"]
    finally:
        main.sessions.pop(sid, None)
        main.sessions.pop("finished-session", None)


def test_new_browser_launch_does_not_read_saved_lesson_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STUDENT_FRESH_SESSION_MODE", raising=False)
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    monkeypatch.setattr(main, "platform_context", lambda token, lesson_id=None: _context(lesson_id))
    monkeypatch.setattr(main.persistence, "save", lambda *args: None)
    monkeypatch.setattr(main.persistence, "latest_session_key",
                        lambda *args: pytest.fail("a new browser must not read saved lessons"))
    started = main.start(main.StartRequest(launch_token="new-ticket"))
    sid = started["sessionId"]
    try:
        assert started["browserKey"] == "u:c:catalog"
        lesson = main.begin(sid, "L2", BackgroundTasks())
        assert lesson["sessionId"] == sid
        assert lesson["phase"] == "video"
    finally:
        main.sessions.pop(sid, None)
        main.preparing.discard(sid)
