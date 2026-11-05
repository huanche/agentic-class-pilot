"""Real PostgreSQL: pilot turns use the existing durable command transaction."""
from copy import deepcopy
from threading import Event
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import business_client

from backend.infrastructure import commands
from backend.infrastructure import persistence
from backend.infrastructure import model
from backend.teaching import dynamic_teaching as dynamic
from backend.session import command_runtime
from backend.session import service as learning_session
from backend import main
from backend.infrastructure import platform_access
from backend.teaching import service as teaching
from test_dynamic_teaching import video, scripted
from test_reliable_commands import command, post, stored


@pytest.fixture
def pilot(pg, monkeypatch):
    monkeypatch.setattr(learning_session, "sessions", {})
    lesson = {"id": "lesson", "title": "试点课时", "classroom": {
        "id": "room", "playerUrl": "https://example.test/player", "scenes": []}}
    context = {"userId": "student", "courseId": "course", "publication": {"id": "pub", "version": 1},
               "selectedLessonId": "lesson", "lessons": [lesson], "lessonCatalog": [lesson]}
    session = video()
    session.update(context=context, courses=learning_session.catalog(context), classroomId="room")
    session.pop("stateVersion")
    persistence.save(session, 0)
    monkeypatch.setattr(platform_access, "authorize_student", lambda *a: {
        "userId": "student", "courseId": "course", "publication": {"publicationId": "pub", "version": 1},
        "source": "launch_token"})
    monkeypatch.setattr(platform_access, "platform_context", lambda *a: deepcopy(context))
    monkeypatch.setattr(platform_access, "report_learning_progress", lambda *a: True)
    calls = scripted(monkeypatch)
    fixture = business_client(main), session, context, calls
    response = post(fixture, command(session, "start_discussion"))
    assert response.status_code == 200, response.text
    return fixture


def answer(session, text="当前回答", kind="submit_answer"):
    body = command(session, kind, text)
    body["payload"]["text"] = text
    body["payload"]["taskId"] = session["currentTaskId"]
    return body


def counts(pg):
    with pg() as conn:
        return dict(conn.execute("SELECT event_type,count(*) FROM student.learning_events GROUP BY event_type").fetchall())


def test_dynamic_receipt_is_idempotent_and_restores_pinned_task_and_policy(pilot, pg, monkeypatch):
    body = answer(stored())
    before_calls = len(pilot[3])
    first = post(pilot, body)
    assert first.status_code == 200, first.text
    view = first.json()["sessionView"]
    before = counts(pg)
    assert post(pilot, body).json() == first.json()
    assert counts(pg) == before and len(pilot[3]) == before_calls + 2
    assert before["teaching_decision"] == 2 and before["learning_observation"] == 1
    monkeypatch.setenv("STUDENT_DYNAMIC_PILOT_SCOPES", "[]")
    learning_session.sessions.clear()
    restored = stored()
    assert restored["flowVersion"] == dynamic.FLOW and restored["teachingPolicy"] == dynamic.POLICY
    assert restored["currentTaskId"] == view["currentTaskPublic"]["taskId"]
    assert restored["messages"] == view["messages"]


def test_dynamic_write_failure_rolls_back_decision_task_evidence_then_retries_same_ids(pilot, pg, monkeypatch):
    original = persistence.write_records
    before = stored()
    before_counts = counts(pg)
    def fail(conn, candidate):
        original(conn, candidate)
        raise RuntimeError("Injected failure after pilot records")
    monkeypatch.setattr(persistence, "write_records", fail)
    body = answer(before)
    response = post(pilot, body)
    assert response.status_code == 503
    failed = commands.read("session", body["commandId"])
    assert failed["status"] == "failed" and stored()["messages"] == before["messages"]
    assert counts(pg) == before_counts
    monkeypatch.setattr(persistence, "write_records", original)
    assert post(pilot, body).status_code == 200
    assert stored()["messages"][-2]["messageId"] == failed["studentMessageId"]
    assert counts(pg)["learning_observation"] == 1


def test_invalid_dynamic_model_keeps_task_and_original_input_for_retry(pilot, monkeypatch):
    before = stored()
    calls = []
    monkeypatch.setattr(model, "complete_bounded", lambda *a: calls.append(a) or '{"action":"finish_without_evidence"}')
    body = answer(before)
    response = post(pilot, body)
    assert response.status_code == 503 and len(calls) == 2
    receipt = commands.read("session", body["commandId"])
    assert receipt["failure"]["code"] == "INVALID_DECISION"
    assert receipt["payload"]["text"] == body["payload"]["text"]
    assert stored()["messages"] == before["messages"] and stored()["currentTaskId"] == before["currentTaskId"]
    scripted(monkeypatch)
    assert post(pilot, body).status_code == 200


def test_dynamic_concurrent_answer_busy_and_finish_rejects_late_candidate(pilot, monkeypatch):
    entered, release = Event(), Event()
    original = model.complete_bounded
    def blocked(*args):
        if args[0] == dynamic.DECISION_PROMPT:
            entered.set()
            assert release.wait(10)
        return original(*args)
    monkeypatch.setattr(model, "complete_bounded", blocked)
    body = answer(stored())
    with ThreadPoolExecutor() as pool:
        first = pool.submit(post, pilot, body)
        try:
            assert entered.wait(5)
            busy = post(pilot, answer(stored(), "另一设备回答"))
            assert busy.status_code == 409 and busy.json()["code"] == "COMMAND_BUSY"
            ended = post(pilot, command(stored(), "finish"))
            assert ended.status_code == 200
            ended_messages = stored()["messages"]
        finally:
            release.set()
        first.result(timeout=10)
    assert commands.read("session", body["commandId"])["status"] == "cancelled"
    assert stored()["phase"] == "done" and stored()["messages"] == ended_messages


def test_dynamic_help_pause_and_afterclass_commands_are_authorized_and_preserve_classroom(pilot, pg):
    before = stored()
    help_body = answer(before, "给一个提示", "request_help")
    assert post(pilot, help_body).status_code == 200
    after_help = stored()
    assert commands.read("session", help_body["commandId"])["studentMessageId"] == after_help["messages"][-2]["messageId"]
    assert after_help["learningRecords"]["assistance"][-1]["guidedPolicy"] is True
    assert post(pilot, command(after_help, "pause")).status_code == 200
    paused = stored()
    task = paused["currentTaskId"]
    rejected = post(pilot, answer(paused))
    assert rejected.status_code == 409 and rejected.json()["code"] == "INVALID_ACTION"
    assert post(pilot, command(paused, "resume_activity")).status_code == 200
    assert stored()["currentTaskId"] == task
    assert post(pilot, command(stored(), "finish")).status_code == 200
    classroom = deepcopy(stored()["classroomFeedback"])
    assert post(pilot, command(stored(), "continue_after_class")).status_code == 200
    assert post(pilot, answer(stored(), "课后表达", "postclass_answer")).status_code == 200
    assert stored()["phase"] == "done" and stored()["classroomFeedback"] == classroom
    record = pilot[0].post("/api/session/session/learning-records", json={"launch_token": "ticket"})
    assert record.status_code == 200 and record.json()["observations"][-1]["studentExcerpt"] == "课后表达"
