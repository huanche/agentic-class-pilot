"""Replay resolves only the saved lesson and never restarts learning."""
from copy import deepcopy
from pathlib import Path
import sys
from threading import Lock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend import main


@pytest.fixture
def replay(monkeypatch):
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    context = {
        "userId": "u", "courseId": "c", "publication": {"id": "p", "version": 1},
        "selectedLessonId": "L2", "lessonCatalog": [{"id": "L2", "title": "第二课"}],
        "lessons": [{"id": "L2", "classroom": {
            "id": "room-2", "playerUrl": "https://teacher.example/classroom-player/room-2"}}],
    }
    session = {
        "id": "replay-test", "context": deepcopy(context), "launchToken": "ticket",
        "courses": [{"id": "c", "lessons": [{"id": "L2", "playerUrl": None}]}],
        "phase": "done", "lessonId": "L2", "classroomId": "room-2",
        "messages": [{"role": "student", "text": "我的复述", "phase": "recall"}],
        "feedback": {"summary": "本次反馈", "points": []}, "dialogue": None,
        "lock": Lock(),
    }
    calls = []

    def platform(token, lesson_id=None):
        calls.append((token, lesson_id))
        return context

    monkeypatch.setitem(main.sessions, session["id"], session)
    monkeypatch.setattr(main, "platform_context", platform)
    monkeypatch.setattr(main.persistence, "save", lambda *_: pytest.fail("replay must not write learning progress"))
    return TestClient(main.app), session, context, calls


def test_replay_fetches_missing_url_without_changing_progress(replay):
    client, session, _, calls = replay
    before = deepcopy({k: v for k, v in session.items() if k != "lock"})
    response = client.post("/api/session/replay-test/playback", json={})
    assert response.status_code == 200
    assert response.json()["courseId"] == "c"
    assert response.json()["lesson"]["id"] == "L2"
    assert response.json()["lesson"]["playerUrl"].endswith("/room-2")
    assert calls == [("ticket", "L2")]
    assert {k: v for k, v in session.items() if k != "lock"} == before


def test_replay_accepts_current_browser_token_after_server_restore(replay):
    client, session, _, calls = replay
    session.pop("launchToken")
    response = client.post("/api/session/replay-test/playback", json={"launch_token": "new-ticket"})
    assert response.status_code == 200
    assert calls == [("new-ticket", "L2")]


@pytest.mark.parametrize("field,value", [
    ("userId", "another-user"), ("courseId", "another-course"),
    ("publication", {"id": "other", "version": 1}),
    ("publication", {"id": "p", "version": 2}),
    ("selectedLessonId", "L1"), ("lessons", []),
])
def test_replay_rejects_mismatched_platform_context(replay, field, value):
    client, _, context, _ = replay
    context[field] = value
    assert client.post("/api/session/replay-test/playback", json={}).status_code == 409


@pytest.mark.parametrize("field,value", [("id", "another-room"), ("playerUrl", None)])
def test_replay_rejects_replaced_or_unplayable_classroom(replay, field, value):
    client, _, context, _ = replay
    context["lessons"][0]["classroom"][field] = value
    assert client.post("/api/session/replay-test/playback", json={}).status_code == 409


def test_replay_requires_launch_token_for_platform_refresh(replay):
    client, session, _, calls = replay
    session.pop("launchToken")
    response = client.post("/api/session/replay-test/playback", json={})
    assert response.status_code == 409
    assert "平台" in response.json()["detail"]
    assert calls == []


def test_replay_preserves_feedback_when_platform_unavailable(replay, monkeypatch):
    client, session, _, _ = replay

    def unavailable(*_):
        raise HTTPException(503, "平台服务暂不可用")

    monkeypatch.setattr(main, "platform_context", unavailable)
    response = client.post("/api/session/replay-test/playback", json={})
    assert response.status_code == 503
    assert session["phase"] == "done"
    assert session["feedback"]["summary"] == "本次反馈"


def test_demo_replay_does_not_request_platform(replay):
    client, session, _, calls = replay
    session["context"] = None
    session["courses"][0]["lessons"][0]["playerUrl"] = "/demo-player"
    response = client.post("/api/session/replay-test/playback", json={})
    assert response.status_code == 200
    assert response.json()["lesson"]["playerUrl"] == "/demo-player"
    assert calls == []
