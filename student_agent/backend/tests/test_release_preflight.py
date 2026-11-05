"""Release checks use disposable databases; deployment tests never run systemctl."""
import ast
import json
from pathlib import Path

import pytest

from backend.infrastructure import release_check

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("scopes", ['[{"courseId":"c","lessonId":"l"}]', '{}', 'null', 'invalid'])
def test_release_rejects_dynamic_admission(monkeypatch, scopes):
    monkeypatch.setenv("PLATFORM_AUTH_URL", "http://127.0.0.1:8080/api/v1")
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test")
    monkeypatch.setenv("STUDENT_AGENT_API_KEY", "test")
    monkeypatch.setenv("PLATFORM_TO_STUDENT_KEY", "test-forward-channel")
    monkeypatch.setenv("STUDENT_DYNAMIC_PILOT_SCOPES", scopes)
    with pytest.raises(release_check.ReleaseCheckError, match="dynamic_teaching_must_be_closed"):
        release_check.check()


def test_readiness_returns_sanitized_failure(monkeypatch):
    from backend.main import app
    from fastapi.testclient import TestClient
    monkeypatch.setattr(release_check, "check", lambda: (_ for _ in ()).throw(
        release_check.ReleaseCheckError("database_schema_or_connection_unavailable")))
    response = TestClient(app).get("/api/session/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "database_schema_or_connection_unavailable"}


def deploy_functions():
    # Execute only the pure decision functions, never the Linux deployment entrypoint.
    tree = ast.parse((ROOT / "scripts/mainland/agentic-web-deploy").read_text(encoding="utf-8"))
    module = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)
                            and n.name in {"recover", "rollback_compatible", "frozen_environment", "staged_release_matches"}], type_ignores=[])
    namespace = {"json": json}
    exec(compile(module, "deploy-decisions", "exec"), namespace)
    return namespace


def test_failed_first_upgrade_cannot_restart_a_pre_p2_writer(tmp_path):
    functions = deploy_functions()
    old, new = tmp_path / "old", tmp_path / "new"
    (new / "student_agent").mkdir(parents=True)
    (new / "student_agent/RELEASE_COMPATIBILITY.json").write_text(
        '{"studentDataFormat":"student-reliable-records-v1"}')
    compatible = functions["rollback_compatible"](old, new)
    events = []
    with pytest.raises(RuntimeError, match="UNSAFE_CODE_ROLLBACK_BLOCKED"):
        functions["recover"](lambda: events.append("old_writer_started"),
                             lambda: events.append("writers_stopped"), compatible)
    assert events == ["writers_stopped"]
    (old / "student_agent").mkdir(parents=True)
    (old / "student_agent/RELEASE_COMPATIBILITY.json").write_text(
        (new / "student_agent/RELEASE_COMPATIBILITY.json").read_text())
    assert functions["rollback_compatible"](old, new)
    functions["recover"](lambda: events.append("compatible_restored"),
                         lambda: events.append("writers_stopped"), True)
    assert events == ["writers_stopped", "compatible_restored"]


def test_frozen_environment_and_staged_retry_require_trusted_matching_records(tmp_path):
    from types import SimpleNamespace
    functions = deploy_functions()
    class Record:
        def __init__(self, data):
            self.data, self.uid, self.mode, self.link = data, 0, 0o600, False
        def stat(self):
            return SimpleNamespace(st_uid=self.uid, st_mode=self.mode)
        def is_symlink(self):
            return self.link
        def read_text(self):
            return json.dumps(self.data)
    record = Record({"reference": "/old", "environment": {"DATABASE_URL": "secret-not-printed"}})
    assert functions["frozen_environment"](record, "/old") == record.data["environment"]
    for attr, bad in (("uid", 1000), ("mode", 0o644), ("link", True)):
        previous = getattr(record, attr)
        setattr(record, attr, bad)
        with pytest.raises(RuntimeError, match="Untrusted"):
            functions["frozen_environment"](record, "/old")
        setattr(record, attr, previous)
    with pytest.raises(RuntimeError, match="does not match"):
        functions["frozen_environment"](record, "/other")
    expected = {"sha": "a" * 40, "image_id": "image-1", "reference": "/old"}
    (tmp_path / "manifest.json").write_text(json.dumps({"sha": expected["sha"]}))
    receipt = Record(expected.copy())
    assert functions["staged_release_matches"](receipt, tmp_path, expected)
    receipt.data["image_id"] = "image-2"
    assert not functions["staged_release_matches"](receipt, tmp_path, expected)
    receipt.data = expected.copy()
    receipt.mode = 0o666
    assert not functions["staged_release_matches"](receipt, tmp_path, expected)


def test_student_role_readiness_checks_schema_permissions_and_indexes(pg, monkeypatch):
    import psycopg
    from psycopg import sql
    from uuid import uuid4
    role = "student_preflight_" + uuid4().hex
    with pg() as connection:
        connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        connection.execute(sql.SQL("GRANT USAGE ON SCHEMA student TO {}").format(sql.Identifier(role)))
        connection.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA student TO {}").format(sql.Identifier(role)))
        connection.execute(sql.SQL("GRANT USAGE ON ALL SEQUENCES IN SCHEMA student TO {}").format(sql.Identifier(role)))
        connection.execute(sql.SQL("REVOKE UPDATE,DELETE ON student.lesson_content_versions FROM {}").format(sql.Identifier(role)))
    import os
    original = psycopg.connect
    def admin():
        return original(os.environ["STUDENT_DATABASE_URL"])
    def restricted(*args, **kwargs):
        connection = original(*args, **kwargs)
        assert connection.execute("SHOW transaction_read_only").fetchone()[0] == "on"
        connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
        return connection
    monkeypatch.setattr(psycopg, "connect", restricted)
    monkeypatch.setenv("PLATFORM_AUTH_URL", "http://127.0.0.1:8080/api/v1")
    monkeypatch.setenv("STUDENT_AGENT_API_KEY", "test")
    monkeypatch.setenv("PLATFORM_TO_STUDENT_KEY", "test-forward-channel")
    monkeypatch.setenv("STUDENT_DYNAMIC_PILOT_SCOPES", "[]")
    try:
        assert release_check.check() == {"ok": True, "dynamicTeachingClosed": True}
        with admin() as connection:
            connection.execute(sql.SQL("REVOKE INSERT ON student.student_commands FROM {}").format(sql.Identifier(role)))
        with pytest.raises(release_check.ReleaseCheckError, match="database_privileges_missing"):
            release_check.check()
        with admin() as connection:
            connection.execute(sql.SQL("GRANT INSERT ON student.student_commands TO {}").format(sql.Identifier(role)))
            connection.execute(sql.SQL("REVOKE DELETE ON student.pending_progress_sync FROM {}").format(sql.Identifier(role)))
        with pytest.raises(release_check.ReleaseCheckError, match="database_privileges_missing"):
            release_check.check()
        with admin() as connection:
            connection.execute(sql.SQL("GRANT DELETE ON student.pending_progress_sync TO {}").format(sql.Identifier(role)))
            connection.execute(sql.SQL("GRANT UPDATE ON student.lesson_content_versions TO {}").format(sql.Identifier(role)))
        with pytest.raises(release_check.ReleaseCheckError, match="lesson_content_must_be_immutable"):
            release_check.check()
        with admin() as connection:
            connection.execute(sql.SQL("REVOKE UPDATE ON student.lesson_content_versions FROM {}").format(sql.Identifier(role)))
            connection.execute("ALTER TABLE student.student_commands RENAME COLUMN task_id TO missing_task_id")
        try:
            with pytest.raises(release_check.ReleaseCheckError, match="database_schema_or_connection_unavailable"):
                release_check.check()
        finally:
            with admin() as connection:
                connection.execute("ALTER TABLE student.student_commands RENAME COLUMN missing_task_id TO task_id")
        with admin() as connection:
            connection.execute("ALTER INDEX student.student_commands_active_idx RENAME TO preflight_hidden_idx")
        try:
            with pytest.raises(release_check.ReleaseCheckError, match="required_indexes_missing"):
                release_check.check()
        finally:
            with admin() as connection:
                connection.execute("ALTER INDEX student.preflight_hidden_idx RENAME TO student_commands_active_idx")
    finally:
        with admin() as connection:
            connection.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_actual_alembic_pub10_upgrade_backfill_atomic_failure_and_retry(pg, tmp_path):
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from psycopg.conninfo import conninfo_to_dict
    from sqlalchemy import URL
    import os

    info = conninfo_to_dict(os.environ["STUDENT_DATABASE_URL"])
    url = URL.create("postgresql+psycopg", username=info["user"], password=info.get("password"),
                     host=info["host"], port=int(info["port"]), database=info["dbname"])
    # Only the environment is minimal. Revision traversal and upgrade functions are the real files.
    (tmp_path / "env.py").write_text('''from alembic import context
from sqlalchemy import create_engine
with create_engine(context.config.attributes['url']).connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
''')
    config = Config()
    config.attributes["url"] = url
    config.set_main_option("script_location", str(tmp_path))
    config.set_main_option("path_separator", "os")
    config.set_main_option("version_locations", str(ROOT / "platform/backend/app/alembic/versions"))
    assert ScriptDirectory.from_config(config).get_heads() == ["rec12"]
    with pg() as connection:
        connection.execute("DROP TABLE student.student_commands,student.pending_progress_sync,student.lesson_content_versions")
        for column in ("state_version", "content_generation", "snapshot", "lesson_id", "revoked_at", "content_id"):
            connection.execute(f"ALTER TABLE student.student_sessions DROP COLUMN {column}")
        for column in ("message_id", "task_id", "episode_id"):
            connection.execute(f"ALTER TABLE student.student_messages DROP COLUMN {column}")
        connection.execute("INSERT INTO student.student_sessions(session_key,user_id,course_id,publication_id,publication_version) VALUES ('legacy','u','c','p',1)")
        connection.execute("INSERT INTO student.learning_events(session_key,user_id,course_id,publication_id,event_type,event_id,payload) VALUES ('legacy','u','c','p','agent_state','old','{\"lessonId\":\"lesson\",\"stateVersion\":\"broken\"}')")
    command.stamp(config, "pub10")
    try:
        with pytest.raises(Exception):
            command.upgrade(config, "head")
        with pg() as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "pub10"
            assert connection.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='student' AND table_name='student_sessions' AND column_name='snapshot'").fetchone()[0] == 0
            connection.execute("UPDATE student.learning_events SET payload='{\"lessonId\":\"lesson\",\"stateVersion\":3,\"contentGeneration\":2}'")
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        with pg() as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "rec12"
            assert connection.execute("SELECT state_version,content_generation,lesson_id,snapshot->>'lessonId' FROM student.student_sessions WHERE session_key='legacy'").fetchone() == (3, 2, "lesson", "lesson")
    finally:
        # Keep the shared disposable fixture usable even when an assertion fails.
        with pg() as connection:
            connection.execute("UPDATE student.learning_events SET payload='{}'")
        command.upgrade(config, "head")
