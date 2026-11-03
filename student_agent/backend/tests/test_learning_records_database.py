"""Trace records share the P2 transaction, scope and retry guarantees."""
from copy import deepcopy
import json

import pytest

from backend.infrastructure import commands
from backend.evidence import records as learning_records
from backend.infrastructure import persistence
from backend.session import command_runtime
from backend.session import service as learning_session
from backend.infrastructure import platform_access
from test_reliable_commands import active, command, post, stored


def event_counts(pg):
    with pg() as connection:
        return dict(connection.execute("SELECT event_type,count(*) FROM student.learning_events "
                                       "GROUP BY event_type").fetchall())


def test_command_task_and_message_ids_are_bound_before_completion_and_stable_after_retry(active, pg):
    body = command(active[1])
    body["payload"]["taskId"] = stored()["currentTaskId"]
    accepted = commands.accept("session", body, active[2], command_runtime.validate)
    assert accepted["taskId"] == body["payload"]["taskId"]
    assert accepted["studentMessageId"] == learning_records.message_identity(active[1], body["commandId"])
    response = post(active, body)
    assert response.status_code == 200, response.text
    student = response.json()["sessionView"]["messages"][0]
    assert student["messageId"] == accepted["studentMessageId"] and student["taskId"] == accepted["taskId"]
    before = event_counts(pg)
    assert post(active, body).json() == response.json()
    assert event_counts(pg) == before
    with pg() as connection:
        row = connection.execute("SELECT message_id,task_id,episode_id FROM student.student_messages WHERE seq=1").fetchone()
    assert row == (student["messageId"], student["taskId"], student["episodeId"])


def test_wrong_task_is_rejected_before_model_or_state_change(active):
    body = command(active[1])
    body["payload"]["taskId"] = "another-task"
    response = post(active, body)
    assert response.status_code == 409 and response.json()["code"] == "TASK_CHANGED"
    assert not active[3] and stored()["stateVersion"] == active[1]["stateVersion"]


def test_record_write_failure_rolls_back_messages_observations_help_and_task_changes(active, pg, monkeypatch):
    original = persistence.write_records
    before = event_counts(pg)
    def broken(connection, session):
        original(connection, session)
        raise RuntimeError("failure after trace records before snapshot")
    monkeypatch.setattr(persistence, "write_records", broken)
    body = command(active[1])
    response = post(active, body)
    assert response.status_code == 503
    receipt = commands.read("session", body["commandId"])
    assert receipt["status"] == "failed"
    assert event_counts(pg) == before and stored()["messages"] == []
    with pg() as connection:
        assert connection.execute("SELECT count(*) FROM student.student_messages").fetchone() == (0,)
    monkeypatch.setattr(persistence, "write_records", original)
    completed = post(active, body)
    assert completed.status_code == 200
    assert stored()["messages"][0]["messageId"] == receipt["studentMessageId"]
    counts = event_counts(pg)
    assert counts["learning_observation"] == counts["learning_assistance"] == 1


def test_read_records_is_authorized_and_does_not_write_or_invoke_model(active, pg, monkeypatch):
    assert post(active, command(active[1])).status_code == 200
    before, model_calls = event_counts(pg), len(active[3])
    response = active[0].post("/api/session/session/learning-records", json={"launch_token": "ticket"})
    assert response.status_code == 200
    assert response.json()["observations"][0]["studentExcerpt"] == "原始回答"
    assert response.json()["observations"][0]["independence"] == "unknown"
    assert event_counts(pg) == before and len(active[3]) == model_calls
    monkeypatch.setattr(platform_access, "authorize_student", lambda *args: {
        "userId": "different-student", "courseId": "course"})
    denied = active[0].post("/api/session/session/learning-records", json={"launch_token": "other"})
    assert denied.status_code == 403


def test_formal_browser_snapshot_contains_only_locator_not_teaching_or_evidence(active):
    response = post(active, command(active[1]))
    snapshot = learning_session._restore_browser_snapshot(response.json()["sessionView"]["browserSnapshot"])
    assert snapshot["messages"] == snapshot["courses"] == []
    assert not set(snapshot) & {"dialogue", "learningRecords", "lessonContent", "feedback", "launchToken"}
    assert snapshot["id"] == "session" and snapshot["lessonId"] == "lesson"


def test_reset_erases_trace_records_and_keeps_shared_course_content(active, pg):
    assert post(active, command(active[1])).status_code == 200
    assert post(active, command(stored(), "finish")).status_code == 200
    with pg() as connection:
        versions = connection.execute("SELECT count(*) FROM student.lesson_content_versions").fetchone()[0]
    assert post(active, command(stored(), "reset_lesson")).status_code == 200
    with pg() as connection:
        assert connection.execute("SELECT count(*) FROM student.learning_events WHERE session_key='session'").fetchone() == (0,)
        assert connection.execute("SELECT content_id FROM student.student_sessions WHERE session_key='session'").fetchone() == (None,)
        assert connection.execute("SELECT count(*) FROM student.lesson_content_versions").fetchone()[0] == versions


def test_legacy_messages_are_backfilled_without_fabricating_old_assistance(active, pg):
    legacy = deepcopy(active[1])
    for key in ("learningRecords", "recordsStored", "currentTaskId", "lessonContent", "contentRef"):
        legacy.pop(key, None)
    legacy["messages"] = [{"role": "student", "text": "旧回答", "phase": "recall"},
                           {"role": "assistant", "text": "旧提示", "phase": "recall"}]
    legacy["dialogue"]["points"][0]["assessment_history"] = [{"stage": "recall", "round": 1,
        "result": "partial", "studentText": "旧回答", "evidence": "原评估"}]
    legacy["dialogue"]["points"][0]["recall_attempts"] = 1
    with pg() as connection:
        connection.execute("DELETE FROM student.learning_events WHERE event_type LIKE 'learning_%'")
        connection.execute("UPDATE student.student_sessions SET snapshot=%s,content_id=NULL", (json.dumps(legacy),))
        for seq, message in enumerate(legacy["messages"], 1):
            connection.execute("INSERT INTO student.student_messages(session_key,user_id,course_id,publication_id,"
                "seq,role,phase,content) VALUES ('session','student','course','pub',%s,%s,%s,%s)",
                (seq, message["role"], message["phase"], message["text"]))
    restored = stored()
    first_ids = [m["messageId"] for m in restored["messages"]]
    assert restored["learningRecords"]["observations"][0]["studentMessageIds"] == []
    assert not restored["learningRecords"]["assistance"]
    assert post(active, command(restored)).status_code == 200
    final = stored()
    assert [m["messageId"] for m in final["messages"][:2]] == first_ids
    assert final["learningRecords"]["observations"][0]["independence"] == "unknown"
    with pg() as connection:
        assert connection.execute("SELECT message_id FROM student.student_messages ORDER BY seq LIMIT 2").fetchall() == [(i,) for i in first_ids]


def test_rec12_removes_mutation_rights_inherited_from_old_default_grants(pg):
    import ast
    from pathlib import Path
    import psycopg
    path = Path(__file__).resolve().parents[3] / "platform/backend/app/alembic/versions/rec12_student_learning_records.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    statements = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "STATEMENTS" for t in n.targets))
    with pg() as connection:
        connection.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='student') "
                           "THEN CREATE ROLE student NOLOGIN; END IF; END $$")
        connection.execute("GRANT USAGE ON SCHEMA student TO student")
        connection.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA student TO student")
        for statement in statements:
            connection.execute(statement)
        assert connection.execute("SELECT has_table_privilege('student','student.lesson_content_versions','SELECT'),"
            "has_table_privilege('student','student.lesson_content_versions','INSERT'),"
            "has_table_privilege('student','student.lesson_content_versions','UPDATE'),"
            "has_table_privilege('student','student.lesson_content_versions','DELETE')").fetchone() == (True, True, False, False)
        connection.execute("SET LOCAL ROLE student")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection.transaction():
                connection.execute("UPDATE student.lesson_content_versions SET payload='{}'")
