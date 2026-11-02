"""Account-scoped history must survive a new browser and a server restart."""
from copy import deepcopy
from pathlib import Path
import sys
from threading import Lock
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend import main


def context(lesson_id=None, user_id="student-a"):
    return {
        "userId": user_id, "courseId": "course", "courseTitle": "课程",
        "publication": {"id": "publication", "version": 1},
        "selectedLessonId": lesson_id,
        "lessonCatalog": [{"id": "lesson", "title": "课时"}],
        "lessons": [] if not lesson_id else [{
            "id": lesson_id, "title": "课时", "classroom": {
                "id": "room", "playerUrl": "http://example.test/player", "scenes": []},
        }],
    }


def saved_session(phase="discussion"):
    return {
        "id": "saved", "context": context("lesson"),
        "courses": main.catalog(context("lesson")),
        "phase": phase, "lessonId": "lesson", "classroomId": "room",
        "messages": [{"role": "student", "phase": "recall", "text": "我的历史发言"},
                     {"role": "assistant", "phase": "recall", "text": "历史导师回复"}],
        "dialogue": main.initial_state([{"id": "point", "title": "概念", "content": "解释"}]),
        "preparation": "ready", "feedback": {"schemaVersion": 3, "summary": "历史反馈"},
        "postclassStage": "open", "lock": Lock(),
    }


@pytest.fixture
def history(monkeypatch):
    monkeypatch.setenv("STUDENT_FRESH_SESSION_MODE", "1")
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "offline-history-test-key")
    monkeypatch.setattr(main, "sessions", {})
    monkeypatch.setattr(main, "preparing", set())
    monkeypatch.setattr(main, "platform_context", lambda token, lesson_id=None: context(lesson_id))
    saved = saved_session()
    calls = []
    def lookup(*args):
        calls.append(args)
        return "saved"
    def restore(sid):
        assert sid == "saved"
        return {**deepcopy({k: v for k, v in saved.items() if k != "lock"}), "lock": Lock()}
    monkeypatch.setattr(main.persistence, "latest_session_key", lookup)
    monkeypatch.setattr(main.persistence, "restore", restore)
    monkeypatch.setattr(main.persistence, "save", lambda *_: pytest.fail("recovery must not write records"))
    return TestClient(main.app), saved, calls


def resume(client, token="new-platform-token"):
    return client.post("/api/session/resume", json={"launch_token": token, "lesson_id": "lesson"})


def test_new_device_without_browser_cache_restores_account_history(history):
    client, saved, calls = history
    response = resume(client)
    assert response.status_code == 200
    assert response.json()["messages"] == saved["messages"]
    assert response.json()["sessionId"] == "saved"
    assert calls == [("student-a", "course", "publication", 1, "lesson", "room")]
    assert main.sessions["saved"]["launchToken"] == "new-platform-token"


@pytest.mark.parametrize("phase", ["video", "discussion", "done", "postclass"])
def test_new_login_begin_resumes_instead_of_starting_again(history, phase):
    client, saved, _ = history
    saved["phase"] = phase
    started = main.start(main.StartRequest(launch_token="new-platform-token"))
    result = main.begin(started["sessionId"], "lesson", BackgroundTasks())
    assert result["sessionId"] == "saved"
    assert result["phase"] == ("done" if phase == "postclass" else phase)
    assert result["messages"] == saved["messages"]
    assert result["feedback"] == saved["feedback"]
    assert started["sessionId"] not in main.sessions


def test_database_history_overrides_stale_server_memory(history):
    client, saved, _ = history
    stale = saved_session()
    stale["messages"] = []
    main.sessions["saved"] = stale
    response = resume(client)
    assert response.status_code == 200
    assert response.json()["messages"] == saved["messages"]
    assert main.sessions["saved"] is stale


def test_missing_history_is_404_without_creating_a_session(history, monkeypatch):
    client, _, _ = history
    monkeypatch.setattr(main.persistence, "latest_session_key", lambda *_: None)
    assert resume(client).status_code == 404
    assert not main.sessions


def test_database_failure_is_not_treated_as_empty_history(history, monkeypatch):
    client, _, _ = history
    def unavailable(*_):
        raise RuntimeError("offline database failure")
    monkeypatch.setattr(main.persistence, "restore", unavailable)
    assert resume(client).status_code == 503
    assert not main.sessions


def test_resume_requires_current_platform_authorization(history, monkeypatch):
    client, _, calls = history
    assert resume(client, token="").status_code == 401
    def denied(*_):
        raise HTTPException(403, "not enrolled")
    monkeypatch.setattr(main, "platform_context", denied)
    assert resume(client).status_code == 403
    assert calls == []


@pytest.mark.parametrize("field,value", [("userId", "other-student"), ("courseId", "other-course")])
def test_restored_record_must_match_authorized_user_and_course(history, field, value):
    client, saved, _ = history
    saved["context"][field] = value
    response = resume(client)
    assert response.status_code == 409
    assert not main.sessions


def test_browser_snapshot_is_only_a_hint_and_cannot_roll_back_history(history):
    client, saved, _ = history
    stale = saved_session()
    stale["messages"] = []
    snapshot = main._browser_snapshot(stale)
    response = client.post("/api/session/browser-restore", json={
        "snapshot": snapshot, "launch_token": "new-platform-token"})
    assert response.status_code == 200
    assert response.json()["messages"] == saved["messages"]


def test_signed_snapshot_does_not_authorize_a_different_account(history, monkeypatch):
    client, _, calls = history
    snapshot = main._browser_snapshot(saved_session())
    monkeypatch.setattr(main, "platform_context", lambda token, lesson_id=None: context(lesson_id, "student-b"))
    response = client.post("/api/session/browser-restore", json={
        "snapshot": snapshot, "launch_token": "student-b-token"})
    assert response.status_code == 403
    assert calls == []
    assert not main.sessions


def test_platform_snapshot_without_token_cannot_restore(history):
    client, _, calls = history
    response = client.post("/api/session/browser-restore", json={
        "snapshot": main._browser_snapshot(saved_session())})
    assert response.status_code == 401
    assert calls == []


def test_postclass_messages_and_feedback_survive_relogin(history):
    client, saved, _ = history
    saved["phase"] = "done"
    saved["messages"] += [{"role": "student", "text": "课后问题", "phase": "postclass-open"},
                          {"role": "assistant", "text": "课后回复", "phase": "postclass-open"}]
    response = resume(client)
    assert response.status_code == 200
    assert response.json()["postclassMessages"] == saved["messages"][-2:]
    assert response.json()["postclassStage"] == "open"
    assert response.json()["feedback"] == saved["feedback"]


def test_successful_message_can_be_restored_after_server_memory_is_cleared(history, monkeypatch):
    client, saved, _ = history
    saved["dialogue"]["curriculum_version"] = main.CURRICULUM_VERSION
    main.sessions["saved"] = {
        **deepcopy({key: value for key, value in saved.items() if key != "lock"}), "lock": Lock()}
    writes = []
    def persist(draft, old_count):
        writes.append((old_count, deepcopy(draft["messages"])))
        saved.update(deepcopy(draft))
    monkeypatch.setattr(main.persistence, "save", persist)
    monkeypatch.setattr(main, "dialogue_graph", SimpleNamespace(
        invoke=lambda dialogue: dict(dialogue, reply="已保存的本轮 AI 回复")))
    response = client.post("/api/session/saved/message", json={"text": "本轮学生发言"})
    assert response.status_code == 200
    assert writes[0][0] == 2
    assert [message["text"] for message in writes[0][1][-2:]] == ["本轮学生发言", "已保存的本轮 AI 回复"]
    main.sessions.clear()
    restored = resume(client)
    assert restored.status_code == 200
    assert restored.json()["messages"] == response.json()["messages"]


def test_missing_snapshot_after_history_lookup_is_an_error_not_a_new_session(history, monkeypatch):
    client, _, _ = history
    monkeypatch.setattr(main.persistence, "restore", lambda *_: None)
    assert resume(client).status_code == 503
    assert not main.sessions


@pytest.mark.parametrize("mismatch", ["publication", "classroomId", "lessonId"])
def test_wrong_lesson_or_publication_is_not_restored(history, mismatch):
    client, saved, _ = history
    if mismatch == "publication":
        saved["context"][mismatch] = {"id": "publication", "version": 2}
    else:
        saved[mismatch] = "other"
    assert resume(client).status_code == 409
    assert not main.sessions
