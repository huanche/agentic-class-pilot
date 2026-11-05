"""Exercise the existing teaching flows through HTTP, replacing external I/O only."""
from conftest import without_trace
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest
from conftest import business_client

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.infrastructure import model
from backend.teaching import prompts
from backend.session import service as learning_session
from backend import main
from backend.infrastructure import platform_access


@pytest.fixture
def classroom(monkeypatch):
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "offline-flow-key")
    monkeypatch.setenv("STUDENT_FRESH_SESSION_MODE", "1")
    monkeypatch.setenv("STUDENT_AGENT_RECALL_ROUNDS", "8")
    monkeypatch.setenv("STUDENT_AGENT_REINFORCE_ROUNDS", "4")
    monkeypatch.setattr(learning_session, "sessions", {})
    monkeypatch.setattr(learning_session, "preparing", set())
    lesson = {"id": "lesson", "title": "课时", "classroom": {
        "id": "room", "playerUrl": "https://example.test/player", "scenes": []}}
    def context(token, lesson_id=None, refresh_session=False):
        return {"userId": "student", "courseId": "course", "courseTitle": "课程",
                "publication": {"id": "publication", "version": 1},
                "selectedLessonId": lesson_id, "lessonCatalog": [lesson],
                "lessons": [lesson] if lesson_id else []}
    monkeypatch.setattr(platform_access, "platform_context", context)
    syncs = []
    monkeypatch.setattr(platform_access, "report_learning_progress",
                        lambda session, event: syncs.append(event))
    monkeypatch.setattr(learning_session.persistence, "latest_session_key", lambda *_: None)
    monkeypatch.setattr(learning_session.published_knowledge, "read", lambda *_: {
        "status": "ready", "points": [{"id": "point", "title": "概念", "content": "本课原文依据"}],
        "coverage": {"acceptedCount": 1}, "error": None})
    writes = []
    monkeypatch.setattr(learning_session.persistence, "save",
                        lambda draft, count: writes.append(deepcopy(draft)))
    control = {"result": "partial", "failure": None}
    calls = []
    def complete(system, user):
        calls.append((system, json.loads(user)))
        assessment = system in {prompts.EVALUATION_PROMPT, prompts.POSTCLASS_ASSESS_PROMPT}
        if control["failure"] == ("evaluation" if assessment else "reply"):
            raise TimeoutError("offline model failure")
        if system == prompts.EVALUATION_PROMPT:
            return json.dumps({"intent": "answer", "assessments": [{
                "id": "point", "result": control["result"], "evidence": "学生回答依据"}]})
        if system == prompts.POSTCLASS_ASSESS_PROMPT:
            return json.dumps({"result": control["result"], "evidence": "课后回答依据"})
        return "本轮导师回复"
    monkeypatch.setattr(model, "complete", complete)
    client = business_client(main)
    started = client.post("/api/session/start", json={"launch_token": "ticket"})
    assert started.status_code == 200
    sid = started.json()["sessionId"]
    begun = client.post(f"/api/session/{sid}/begin/lesson")
    assert begun.status_code == 200
    assert begun.json()["preparation"] == "ready"
    discussion = client.post(f"/api/session/{sid}/discussion")
    assert discussion.status_code == 200
    assert discussion.json()["agentStage"] == "recall"
    return client, sid, control, writes, syncs, calls


def send(classroom, result="mastered", text="学生回答"):
    client, sid, control, *_ = classroom
    control["result"] = result
    response = client.post(f"/api/session/{sid}/message", json={"text": text})
    assert response.status_code == 200, response.text
    return response.json()


def test_concept_mastery_and_discussion_outcome_remain_separate(classroom):
    client, sid, _, _, syncs, _ = classroom
    recalled = send(classroom)
    assert recalled["agentStage"] == "discuss"
    assert recalled["messages"][-2]["phase"] == "recall"
    assert recalled["messages"][-1]["phase"] == "discuss"
    wrong = send(classroom, "misconception")
    assert wrong["agentStage"] == "discuss"
    assert send(classroom)["agentStage"] == "wrapup"
    ended = client.post(f"/api/session/{sid}/end")
    assert ended.status_code == 200
    point = ended.json()["feedback"]["points"][0]
    assert point["status"] == "mastered"
    assert point["discussionResult"] == "mastered"
    assert point["recallRounds"] == 1
    assert not ended.json()["feedback"]["endedEarly"]
    assert syncs == ["started", "ended"]
    assert client.post(f"/api/session/{sid}/message", json={"text": "迟到回答"}).status_code == 409


def test_default_eight_and_four_rounds_still_defer_unmastered_points(classroom):
    client, sid, *_ = classroom
    for _ in range(7):
        assert send(classroom, "unanswered", "我不会")["agentStage"] == "recall"
    assert send(classroom, "unanswered")["agentStage"] == "reinforce"
    for _ in range(3):
        assert send(classroom, "partial")["agentStage"] == "reinforce"
    assert send(classroom, "partial")["agentStage"] == "wrapup"
    feedback = client.post(f"/api/session/{sid}/end").json()["feedback"]
    point = feedback["points"][0]
    assert (point["recallRounds"], point["reinforceRounds"]) == (8, 4)
    assert point["excludedFromDiscussion"]
    assert point["category"] == "needs_review"


def test_sixth_round_mastery_requires_independent_reinforcement(classroom):
    for _ in range(5):
        send(classroom, "partial")
    assert send(classroom)["agentStage"] == "reinforce"
    assert send(classroom, "partial")["agentStage"] == "reinforce"
    assert send(classroom)["agentStage"] == "discuss"


def test_early_end_preserves_classroom_feedback_while_postclass_completes(classroom):
    client, sid, control, writes, syncs, _ = classroom
    send(classroom, "partial")
    ended = client.post(f"/api/session/{sid}/end").json()
    original = deepcopy(ended["feedback"])
    assert original["endedEarly"]
    assert original["endedAtStage"] == "recall"
    count = len(writes)
    assert without_trace(client.post(f"/api/session/{sid}/end").json()["feedback"]) == without_trace(original)
    assert len(writes) == count
    assert syncs == ["started", "ended"]
    started = client.post(f"/api/session/{sid}/postclass/start")
    assert started.status_code == 200
    assert started.json()["postclassStage"] == "remediation"
    count = len(writes)
    client.post(f"/api/session/{sid}/postclass/start")
    assert len(writes) == count
    control["result"] = "mastered"
    completed = client.post(f"/api/session/{sid}/postclass/message", json={"text": "独立解释"})
    assert completed.status_code == 200
    assert completed.json()["phase"] == "done"
    assert completed.json()["postclassStage"] == "remediation"
    assert completed.json()["feedback"]["points"][0]["label"] == "课后补完"
    completed = client.post(f"/api/session/{sid}/postclass/message", json={"text": "完成讨论题"})
    assert completed.status_code == 200
    assert completed.json()["postclassStage"] == "open"
    assert completed.json()["feedback"]["points"][0]["label"] == "课后补完"
    assert writes[-1]["classroomFeedback"] == original
    free = client.post(f"/api/session/{sid}/postclass/message", json={"text": "另一个问题"})
    assert free.status_code == 200
    assert free.json()["postclassMessages"][-1]["text"] == "本轮导师回复"


@pytest.mark.parametrize("phase", ["classroom", "postclass"])
@pytest.mark.parametrize("failure", ["evaluation", "reply", "storage"])
def test_failed_turn_does_not_publish_messages_counters_or_feedback(classroom, monkeypatch, phase, failure):
    client, sid, control, writes, *_ = classroom
    endpoint = "message"
    if phase == "postclass":
        client.post(f"/api/session/{sid}/end")
        client.post(f"/api/session/{sid}/postclass/start")
        endpoint = "postclass/message"
    before = client.get(f"/api/session/{sid}").json()
    count = len(writes)
    control["failure"] = failure
    if failure == "storage":
        def fail_save(*_):
            raise RuntimeError("offline storage failure")
        monkeypatch.setattr(learning_session.persistence, "save", fail_save)
    failed = client.post(f"/api/session/{sid}/{endpoint}", json={"text": "失败的回答"})
    assert failed.status_code == 503
    assert "detail" in failed.json()
    assert client.get(f"/api/session/{sid}").json() == before
    assert len(writes) == count


@pytest.mark.parametrize("payload", [{}, {"text": ""}, {"text": "x" * 2001}])
def test_http_message_validation_remains_unchanged(classroom, payload):
    client, sid, _, writes, *_ = classroom
    count = len(writes)
    assert client.post(f"/api/session/{sid}/message", json=payload).status_code == 422
    assert len(writes) == count
