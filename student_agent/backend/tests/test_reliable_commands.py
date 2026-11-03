"""Real PostgreSQL concurrency, rollback and recovery at the command interface."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.infrastructure import commands
from backend.infrastructure import database
from backend.infrastructure import model
from backend.infrastructure import persistence
from backend.teaching import prompts
from backend.session import command_runtime
from backend.session import service as learning_session
from backend import main
from backend.infrastructure import platform_access
from backend.teaching import service as teaching
from backend.contracts import SessionError


@pytest.fixture
def active(pg, monkeypatch):
    monkeypatch.setattr(learning_session, "sessions", {})
    lesson = {"id": "lesson", "title": "课时", "classroom": {
        "id": "room", "playerUrl": "https://example.test/player", "scenes": []}}
    context = {"userId": "student", "courseId": "course", "publication": {"id": "pub", "version": 1},
               "selectedLessonId": "lesson", "lessons": [lesson], "lessonCatalog": [lesson]}
    session = {"id": "session", "context": context, "courses": learning_session.catalog(context),
               "phase": "discussion", "lessonId": "lesson", "classroomId": "room", "messages": [],
               "dialogue": teaching.new_dialogue([{"id": "p", "title": "概念", "content": "原文依据"}]),
               "preparation": "ready", "videoRevision": "revision", "launchToken": "never-persist-this"}
    persistence.save(session, 0)
    monkeypatch.setattr(platform_access, "platform_context", lambda *args: deepcopy(context))
    monkeypatch.setattr(platform_access, "report_learning_progress", lambda *args: True)
    monkeypatch.setattr(platform_access, "authorize_student", lambda *args: {
        "userId": context["userId"], "courseId": context["courseId"],
        "publication": {"publicationId": context["publication"]["id"],
                        "version": context["publication"]["version"]}, "source": "launch_token"})
    calls = []
    def complete(system, user):
        calls.append(system)
        if system == prompts.EVALUATION_PROMPT:
            return json.dumps({"intent": "answer", "assessments": [{
                "id": "p", "result": "mastered", "evidence": "学生依据"}]})
        if system == prompts.POSTCLASS_ASSESS_PROMPT:
            return json.dumps({"result": "mastered", "evidence": "课后依据"})
        return "导师回复"
    monkeypatch.setattr(model, "complete", complete)
    return TestClient(main.app), session, context, calls


def command(session, kind="submit_answer", text="原始回答", command_id=None):
    return {"commandId": command_id or uuid4().hex, "expectedStateVersion": session["stateVersion"],
            "contentGeneration": session.get("contentGeneration", 0), "type": kind,
            "payload": {"text": text} if kind in {"submit_answer", "postclass_answer"} else {}}


def post(active, body):
    return active[0].post("/api/session/session/commands", json={**body, "launch_token": "ticket"})


def stored():
    return persistence.restore("session")


def counts(pg):
    with pg() as connection:
        return tuple(connection.execute(f"SELECT count(*) FROM student.{name}").fetchone()[0]
                     for name in ("student_messages", "knowledge_mastery", "learning_events", "pending_progress_sync"))


def test_duplicate_and_payload_reuse_cannot_repeat_a_teaching_turn(active, pg):
    body = command(active[1])
    first = post(active, body)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "completed"
    assert first.json()["sessionView"]["stateVersion"] == active[1]["stateVersion"] + 2
    before, calls = counts(pg), len(active[3])
    assert post(active, body).json() == first.json()
    assert counts(pg) == before and len(active[3]) == calls
    changed = post(active, dict(body, payload={"text": "不同回答"}))
    assert changed.status_code == 409
    assert changed.json()["code"] == "COMMAND_REUSED"
    assert stored()["dialogue"]["points"][0]["recall_attempts"] == 1


def test_stale_version_and_wrong_generation_are_rejected_before_model(active):
    body = command(active[1])
    for changed, code in ((dict(body, expectedStateVersion=0), "VERSION_CONFLICT"),
                          (dict(body, contentGeneration=1), "CONTENT_CHANGED")):
        response = post(active, changed)
        assert response.status_code == 409 and response.json()["code"] == code
    assert not active[3]


def test_account_and_publication_must_match_current_platform_authorization(active, monkeypatch):
    body = command(active[1])
    for field, value, status in (("userId", "other", 403), ("publication", {"id": "pub", "version": 2}, 409)):
        context = dict(active[2], **{field: value})
        monkeypatch.setattr(platform_access, "authorize_student", lambda *args: context)
        assert post(active, body).status_code == status
    assert not active[3]
    assert stored()["stateVersion"] == active[1]["stateVersion"]


def test_concurrent_same_and_different_commands_only_run_one_model(active, monkeypatch):
    entered, release = Event(), Event()
    original = model.complete
    def blocking(*args):
        entered.set()
        assert release.wait(8)
        return original(*args)
    monkeypatch.setattr(model, "complete", blocking)
    body = command(active[1])
    with ThreadPoolExecutor(2) as pool:
        future = pool.submit(post, active, body)
        try:
            assert entered.wait(5)
            duplicate = post(active, body)
            assert duplicate.status_code == 202
            other = command(stored(), command_id="other")
            busy = post(active, other)
            assert busy.status_code == 409 and busy.json()["code"] == "COMMAND_BUSY"
        finally:
            release.set()
        assert future.result(timeout=8).status_code == 200
    assert len(active[3]) == 2  # One evaluation and one reply, through the actual graph.
    assert len(stored()["messages"]) == 2


def test_simultaneous_acceptance_uses_database_version_not_process_locks(active):
    bodies = [command(active[1]), command(active[1])]
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda body: post(active, body), bodies))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert stored()["dialogue"]["points"][0]["recall_attempts"] == 1


@pytest.mark.parametrize("failure", ["evaluation", "reply", "write"])
def test_failure_preserves_original_answer_and_retry_finishes_once(active, pg, monkeypatch, failure):
    body = command(active[1])
    baseline = counts(pg)
    original = model.complete
    original_write = database.upsert_mastery
    def failing_model(system, user):
        if (system == prompts.EVALUATION_PROMPT) == (failure == "evaluation"):
            raise TimeoutError("isolated model timeout")
        return original(system, user)
    def failing_write(**kwargs):
        original_write(**kwargs)
        raise RuntimeError("fail after messages and mastery, before snapshot/feedback")
    if failure == "write":
        monkeypatch.setattr(database, "upsert_mastery", failing_write)
    else:
        monkeypatch.setattr(model, "complete", failing_model)
    failed = post(active, body)
    assert failed.status_code == 503
    assert failed.json()["status"] == "failed"
    assert counts(pg) == baseline
    restored = stored()
    assert restored["messages"] == []
    assert restored["dialogue"]["points"][0]["recall_attempts"] == 0
    assert restored["pendingSubmission"]["payload"]["text"] == "原始回答"
    learning_session.sessions.clear()  # New process/browser has no local conversation state.
    monkeypatch.setattr(database, "upsert_mastery", original_write)
    monkeypatch.setattr(model, "complete", original)
    retry = post(active, body)
    assert retry.status_code == 200, retry.text
    assert len(stored()["messages"]) == 2
    assert stored()["dialogue"]["points"][0]["recall_attempts"] == 1


def test_committed_result_survives_a_lost_commit_acknowledgement(active, monkeypatch):
    original = database._db
    @contextmanager
    def lost_ack():
        completed = False
        with original() as connection:
            class Proxy:
                def execute(self, query, params=None):
                    nonlocal completed
                    if "SET status='completed',result=" in query:
                        completed = True
                    return connection.execute(query, params)
            yield Proxy()
        if completed:
            raise ConnectionError("server committed; client lost acknowledgement")
    monkeypatch.setattr(database, "_db", lost_ack)
    body = command(active[1])
    first = post(active, body)
    assert first.status_code == 200
    assert first.json()["status"] == "completed"
    assert post(active, body).json() == first.json()
    assert len(active[3]) == 2


def test_expired_lease_is_reclaimed_and_old_worker_cannot_write(active, pg):
    body = command(active[1])
    commands.accept("session", body, active[2], command_runtime.validate)
    old = commands.claim("session", body["commandId"])
    assert commands.renew("session", body["commandId"], old["token"])
    with pg() as connection:
        connection.execute("UPDATE student.student_commands SET lease_until=now()-interval '1 second'")
    assert not commands.renew("session", body["commandId"], old["token"])
    newer = commands.claim("session", body["commandId"])
    assert newer["token"] != old["token"]
    changed = teaching.classroom_turn(newer["base"], "原始回答")
    with pytest.raises(persistence.RecordConflict):
        commands.complete("session", body["commandId"], old["token"], changed)
    commands.complete("session", body["commandId"], newer["token"], changed)
    assert len(stored()["messages"]) == 2


@pytest.mark.parametrize("claimed", [False, True])
def test_durable_pending_or_abandoned_processing_recovers_after_restart(active, pg, claimed):
    body = command(active[1])
    commands.accept("session", body, active[2], command_runtime.validate)
    if claimed:
        commands.claim("session", body["commandId"])
        with pg() as connection:
            connection.execute("UPDATE student.student_commands SET lease_until=now()-interval '1 second'")
    learning_session.sessions.clear()
    assert commands.next_pending() == ("session", body["commandId"])
    command_runtime.process(*commands.next_pending())
    response = command_runtime.status("session", body["commandId"], "ticket")
    assert response["status"] == "completed"
    assert len(response["sessionView"]["messages"]) == 2
    assert commands.next_pending() is None


def test_finish_cancels_an_inflight_answer_without_counting_it(active, monkeypatch):
    entered, release = Event(), Event()
    original = model.complete
    def blocking(*args):
        entered.set()
        assert release.wait(8)
        return original(*args)
    monkeypatch.setattr(model, "complete", blocking)
    with ThreadPoolExecutor(1) as pool:
        answer = command(active[1])
        future = pool.submit(post, active, answer)
        try:
            assert entered.wait(5)
            ended = post(active, command(stored(), "finish"))
            assert ended.status_code == 200, ended.text
            assert ended.json()["sessionView"]["phase"] == "done"
        finally:
            release.set()
        assert future.result(timeout=8).json()["status"] == "cancelled"
    assert stored()["messages"] == []
    assert stored()["feedback"]["points"][0]["recallRounds"] == 0


def test_completion_feedback_and_outbox_roll_back_together(active, pg, monkeypatch):
    original = persistence.write_completion
    baseline = counts(pg)
    def fail(*args):
        original(*args)
        raise RuntimeError("fail after feedback and final snapshot")
    monkeypatch.setattr(persistence, "write_completion", fail)
    body = command(active[1], "finish")
    assert post(active, body).status_code == 503
    assert stored()["phase"] == "discussion" and stored().get("feedback") is None
    assert counts(pg) == baseline
    monkeypatch.setattr(persistence, "write_completion", original)
    assert post(active, body).status_code == 200
    with pg() as connection:
        assert connection.execute("SELECT event FROM student.pending_progress_sync").fetchall() == [("ended",)]


def test_default_mode_still_writes_progress_without_reading_prior_mastery(active, pg, monkeypatch):
    monkeypatch.delenv("STUDENT_FRESH_SESSION_MODE", raising=False)
    monkeypatch.setattr(database, "read_mastery", lambda *args, **kwargs: pytest.fail("must not read old mastery"))
    assert post(active, command(active[1])).status_code == 200
    with pg() as connection:
        assert connection.execute("SELECT stars FROM student.knowledge_mastery").fetchone() == (4,)


def test_reset_is_idempotent_scoped_and_old_browser_or_worker_cannot_resurrect(active, pg):
    assert post(active, command(active[1], "finish")).status_code == 200
    other = dict(active[1], id="other", lessonId="other-lesson", stateVersion=0)
    for key in ("learningRecords", "recordsStored", "currentTaskId", "contentRef", "lessonContent"):
        other.pop(key, None)
    persistence.save(other, 0)
    body = command(stored(), "reset_lesson")
    first = post(active, body)
    assert first.status_code == 200, first.text
    assert first.json()["sessionView"]["phase"] == "idle"
    assert post(active, body).json() == first.json()
    assert stored() is None
    assert persistence.restore("other") is not None
    with pytest.raises(persistence.RecordConflict):
        persistence.save(dict(active[1]), 0)
    with pg() as connection:
        assert connection.execute("SELECT snapshot,revoked_at IS NOT NULL FROM student.student_sessions "
                                  "WHERE session_key='session'").fetchone() == (None, True)
        assert connection.execute("SELECT base_state,payload FROM student.student_commands "
                                  "WHERE session_key='session'").fetchall() == [({}, {})]
        assert connection.execute("SELECT event FROM student.pending_progress_sync "
                                  "WHERE session_key='session'").fetchall() == [("reset",)]
        fresh_id = first.json()["sessionView"]["sessionId"]
        connection.execute("UPDATE student.student_sessions SET started_at=now()-interval '1 day' "
                           "WHERE session_key=%s", (fresh_id,))
    fresh = persistence.restore(fresh_id)
    fresh["context"]["publication"] = {"id": "new-pub-before-first-start", "version": 2}
    fresh.update(phase="video", lessonId="lesson", classroomId="room")
    persistence.save(fresh, 0)
    with pg() as connection:
        assert connection.execute("SELECT started_at>now()-interval '1 hour' FROM student.student_sessions "
                                  "WHERE session_key=%s", (fresh_id,)).fetchone() == (True,)
        assert connection.execute("SELECT publication_id FROM student.student_sessions "
                                  "WHERE session_key=%s", (fresh_id,)).fetchone() == ("new-pub-before-first-start",)


def test_video_replacement_clears_only_its_session_and_excludes_launch_secret(active, pg):
    assert post(active, command(active[1], "finish")).status_code == 200
    source = stored()
    pending = command(source, "continue_after_class")
    commands.accept("session", pending, active[2], command_runtime.validate)
    claimed = commands.claim("session", pending["commandId"])
    source = stored()
    replacement = dict(source, phase="video", messages=[], dialogue=None, videoRevision="new",
                       launchToken="never-persist-this", feedback=None)
    persistence.discard_lesson_session(source, replacement)
    assert stored()["contentGeneration"] == 1 and stored()["videoRevision"] == "new"
    with pytest.raises(persistence.RecordConflict):
        commands.complete("session", pending["commandId"], claimed["token"], {})
    with pg() as connection:
        values = connection.execute("SELECT snapshot::text FROM student.student_sessions").fetchall()
        assert all("never-persist-this" not in value[0] for value in values)
        assert connection.execute("SELECT ended_at FROM student.student_sessions "
                                  "WHERE session_key='session'").fetchone() == (None,)


def test_legacy_stale_snapshot_save_is_rejected_without_partial_messages(active, pg):
    stale = deepcopy(active[1])
    assert post(active, command(active[1])).status_code == 200
    baseline = counts(pg)
    stale["messages"] = [{"role": "student", "text": "旧快照覆盖"}]
    with pytest.raises(persistence.RecordConflict):
        persistence.save(stale, 0)
    assert counts(pg) == baseline


def test_progress_sync_retries_from_durable_intent(active, pg, monkeypatch):
    assert post(active, command(active[1], "finish")).status_code == 200
    monkeypatch.setattr(platform_access, "report_learning_progress", lambda *args: False)
    assert command_runtime.sync_once()
    with pg() as connection:
        assert connection.execute("SELECT status,attempts FROM student.pending_progress_sync").fetchone() == ("pending", 1)
        connection.execute("UPDATE student.pending_progress_sync SET next_retry_at=now()")
    monkeypatch.setattr(platform_access, "report_learning_progress", lambda *args: True)
    assert command_runtime.sync_once()
    assert not command_runtime.sync_once()
    with pg() as connection:
        assert connection.execute("SELECT status,attempts FROM student.pending_progress_sync").fetchone() == ("completed", 2)


def test_worker_process_crash_and_new_process_recovery(active, pg):
    body = command(active[1], command_id="process-recovery")
    commands.accept("session", body, active[2], command_runtime.validate)
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2]))
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    crashed = subprocess.run([sys.executable, "-c",
        "from backend.infrastructure import commands; import os; "
        "assert commands.claim('session','process-recovery'); os._exit(17)"],
        env=env, capture_output=True, timeout=15, creationflags=flags)
    assert crashed.returncode == 17, crashed.stderr.decode(errors="replace")
    assert commands.read("session", body["commandId"])["status"] == "processing"
    with pg() as connection:
        connection.execute("UPDATE student.student_commands SET lease_until=now()-interval '1 second'")
    recovered = subprocess.run([sys.executable, "-c", """
import json
from backend.infrastructure import model
from backend.teaching import prompts
from backend.session import command_runtime
model.complete = lambda system, user: json.dumps({'intent':'answer','assessments':[
    {'id':'p','result':'mastered','evidence':'answer'}]}) if system == prompts.EVALUATION_PROMPT else 'reply'
command_runtime.process('session','process-recovery')
"""], env=env, capture_output=True, timeout=20, creationflags=flags)
    assert recovered.returncode == 0, recovered.stderr.decode(errors="replace")
    assert commands.read("session", body["commandId"])["status"] == "completed"
    assert len(stored()["messages"]) == 2


def test_migration_backfills_legacy_state_and_is_repeatable_without_losing_receipts(active, pg):
    import ast
    assert post(active, command(active[1])).status_code == 200
    version = stored()["stateVersion"]
    path = Path(__file__).resolve().parents[3] / "platform/backend/app/alembic/versions/cmd11_reliable_student_commands.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    statements = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "STATEMENTS" for t in n.targets))
    with pg() as connection:
        connection.execute("UPDATE student.student_sessions SET snapshot=NULL,state_version=0")
        for _ in range(2):
            for statement in statements:
                connection.execute(statement)
    assert stored()["stateVersion"] == version
    assert len(stored()["messages"]) == 2
    with pg() as connection:
        assert connection.execute("SELECT status FROM student.student_commands").fetchall() == [("completed",)]


def test_legacy_writers_also_use_one_transaction(active, pg, monkeypatch):
    before = counts(pg)
    original = database.upsert_mastery
    def fail(**kwargs):
        original(**kwargs)
        raise RuntimeError("legacy write failed after message and mastery")
    monkeypatch.setattr(database, "upsert_mastery", fail)
    changed = deepcopy(active[1])
    changed.update(teaching.classroom_turn(changed, "answer"))
    with pytest.raises(RuntimeError):
        persistence.save(changed, 0)
    assert counts(pg) == before
    assert stored()["stateVersion"] == active[1]["stateVersion"]


def test_new_commands_keep_eight_four_rules_and_postclass_feedback(active, monkeypatch):
    def partial(system, user):
        if system == prompts.EVALUATION_PROMPT:
            return json.dumps({"intent": "answer", "assessments": [{"id": "p", "result": "partial"}]})
        if system == prompts.POSTCLASS_ASSESS_PROMPT:
            return json.dumps({"result": "mastered", "evidence": "补完依据"})
        return "导师回复"
    monkeypatch.setattr(model, "complete", partial)
    for index in range(12):
        response = post(active, command(stored()))
        assert response.status_code == 200, response.text
        expected = "recall" if index < 7 else "reinforce" if index < 11 else "wrapup"
        assert response.json()["sessionView"]["agentStage"] == expected
    ended = post(active, command(stored(), "finish"))
    original = ended.json()["sessionView"]["feedback"]
    assert original["points"][0]["recallRounds"] == 8
    assert original["points"][0]["reinforceRounds"] == 4
    assert post(active, command(stored(), "continue_after_class")).status_code == 200
    completed = post(active, command(stored(), "postclass_answer"))
    assert completed.status_code == 200
    assert completed.json()["sessionView"]["postclassStage"] == "open"
    assert stored()["classroomFeedback"] == original


def test_reset_keeps_another_students_same_lesson_and_erases_answer_bodies(active, pg):
    assert post(active, command(active[1], text="private-original-answer")).status_code == 200
    assert post(active, command(stored(), "finish")).status_code == 200
    context = dict(active[2], userId="another-student")
    other = dict(active[1], id="another-session", context=context, stateVersion=0)
    for key in ("learningRecords", "recordsStored", "currentTaskId"):
        other.pop(key, None)
    persistence.save(other, 0)
    assert post(active, command(stored(), "reset_lesson")).status_code == 200
    assert persistence.restore("another-session") is not None
    with pg() as connection:
        for table in ("student_messages", "learning_events", "knowledge_mastery"):
            assert connection.execute(f"SELECT count(*) FROM student.{table} WHERE session_key='session'").fetchone() == (0,)
        receipt = connection.execute("SELECT row_to_json(c)::text FROM student.student_commands c "
                                     "WHERE session_key='session'").fetchone()[0]
        assert "private-original-answer" not in receipt


def test_authorization_uses_identity_endpoint_without_refetching_lesson(active, monkeypatch):
    monkeypatch.setattr(platform_access, "platform_context", lambda *args: pytest.fail("must not fetch materials per answer"))
    assert post(active, command(active[1])).status_code == 200


def test_platform_progress_ignores_revoked_rows_and_new_idle_session(active, pg):
    """Execute the real platform aggregate against PostgreSQL without importing its app startup."""
    import ast
    import re
    import uuid
    source = (Path(__file__).resolve().parents[3] /
              "platform/backend/app/api/routes/student_bridge.py").read_text(encoding="utf-8")
    function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                    and n.name == "_course_learning_progress")
    namespace = {"uuid": uuid, "text": lambda query: query}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "platform-progress", "exec"), namespace)
    with pg() as connection:
        class Session:
            def execute(self, query, params):
                if "teacher.mentra_course_artifacts" in query:
                    return type("Total", (), {"first": lambda self: (1,)})()
                cursor = connection.execute(re.sub(r":([a-zA-Z_]\w*)", r"%(\1)s", query), params)
                return type("Rows", (), {"first": lambda self: cursor.fetchone()})()
        before = namespace["_course_learning_progress"](Session(), "student", "course")
    assert before["learnedLessons"] == 1 and before["sessionCount"] == 1
    assert post(active, command(active[1], "finish")).status_code == 200
    assert post(active, command(stored(), "reset_lesson")).status_code == 200
    with pg() as connection:
        after = namespace["_course_learning_progress"](Session(), "student", "course")
    assert after["learnedLessons"] == after["endedSessions"] == after["sessionCount"] == 0
    assert after["percent"] == 0


def test_drain_mode_keeps_existing_receipts_and_recovery_available(active, monkeypatch):
    body = command(active[1])
    commands.accept("session", body, active[2], command_runtime.validate)
    monkeypatch.setenv("STUDENT_COMMAND_ACCEPT_NEW", "0")
    assert post(active, body).status_code == 200
    assert post(active, body).json()["status"] == "completed"
    before = stored()["stateVersion"]
    rejected = post(active, command(stored(), "finish"))
    assert rejected.status_code == 503 and rejected.json()["code"] == "COMMANDS_DRAINING"
    assert stored()["stateVersion"] == before


def test_legacy_postclass_answer_cannot_cancel_a_durable_pending_answer(active):
    assert post(active, command(active[1], "finish")).status_code == 200
    assert post(active, command(stored(), "continue_after_class")).status_code == 200
    body = command(stored(), "postclass_answer")
    commands.accept("session", body, active[2], command_runtime.validate)
    before = stored()
    response = active[0].post("/api/session/session/postclass/message", json={"text": "另一个回答"})
    assert response.status_code == 409 and response.json()["code"] == "COMMAND_BUSY"
    assert stored()["messages"] == before["messages"]
    assert commands.read("session", body["commandId"])["status"] == "pending"


def test_explicit_legacy_end_can_cancel_pending_without_publishing_control_flags(active):
    body = command(active[1])
    commands.accept("session", body, active[2], command_runtime.validate)
    learning_session.sessions["session"] = stored()
    response = active[0].post("/api/session/session/end")
    assert response.status_code == 200, response.text
    assert response.json()["pendingSubmission"] is None
    assert stored()["phase"] == "done"
    assert "_cancelPending" not in stored()
    assert commands.read("session", body["commandId"])["status"] == "cancelled"


@pytest.mark.parametrize("legacy_phase", ["postclass", "replay"])
def test_historical_view_phases_restore_as_completed_classroom(active, pg, legacy_phase):
    with pg() as connection:
        connection.execute("UPDATE student.student_sessions SET snapshot=jsonb_set(snapshot,'{phase}',%s::jsonb)",
                           (json.dumps(legacy_phase),))
    assert stored()["phase"] == "done"
    response = post(active, command(stored(), "continue_after_class"))
    assert response.status_code == 200, response.text
    assert response.json()["sessionView"]["phase"] == "done"
    assert response.json()["sessionView"]["postclassStage"] == "remediation"
