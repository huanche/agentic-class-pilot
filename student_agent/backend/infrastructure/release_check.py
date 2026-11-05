"""Read-only release gate. Never changes schemas, records or provider state."""
from __future__ import annotations

import json
import os


class ReleaseCheckError(RuntimeError):
    pass


TABLES = {
    "student_sessions": "session_key,state_version,content_generation,snapshot,lesson_id,revoked_at,content_id",
    "student_messages": "session_key,message_id,task_id,episode_id",
    "student_commands": "command_id,status,lease_until,accepted_version,content_generation,task_id,student_message_id,content_id",
    "pending_progress_sync": "event_id,status,next_retry_at,lease_until",
    "lesson_content_versions": "content_id,payload,source_manifest_hash,compiler_version",
    "published_lesson_knowledge": "course_id,lesson_id,video_revision,status,claim_token",
    "learning_events": "id,event_type,payload",
    "playback_progress": "session_key",
    "knowledge_mastery": "session_key",
    "task_submissions": "session_key",
    "after_class_reports": "session_key",
}
INDEXES = ("student_commands_active_idx", "student_commands_recovery_idx",
           "pending_progress_sync_ready_idx", "student_message_identity_idx")


def check() -> dict:
    if not (os.environ.get("PLATFORM_TO_STUDENT_KEY") and os.environ.get("PLATFORM_AUTH_URL") and os.environ.get("STUDENT_SERVICE_KEY")
            and (os.environ.get("STUDENT_AGENT_API_KEY") or os.environ.get("LLM_API_KEY"))):
        raise ReleaseCheckError("required_configuration_missing")
    if os.environ.get("STUDENT_NEW_DEMO_PLAYER_URL"):
        raise ReleaseCheckError("demo_must_be_disabled")
    try:
        closed = json.loads(os.environ.get("STUDENT_DYNAMIC_PILOT_SCOPES", "[]")) == []
    except (ValueError, TypeError):
        closed = False
    if not closed:
        raise ReleaseCheckError("dynamic_teaching_must_be_closed")
    url = os.environ.get("STUDENT_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise ReleaseCheckError("database_configuration_missing")
    import psycopg
    try:
        with psycopg.connect(url.replace("+psycopg", ""), connect_timeout=5,
                             options="-c default_transaction_read_only=on -c statement_timeout=5000") as connection:
            for table, columns in TABLES.items():
                # Both names are constants, never caller input.
                connection.execute(f"SELECT {columns} FROM student.{table} LIMIT 0")
                privileges = (("SELECT", "INSERT") if table == "lesson_content_versions" else
                              ("SELECT", "INSERT", "UPDATE") if table == "published_lesson_knowledge" else
                              ("SELECT", "INSERT", "UPDATE", "DELETE"))
                for privilege in privileges:
                    if not connection.execute("SELECT has_table_privilege(current_user,%s,%s)",
                                              ("student." + table, privilege)).fetchone()[0]:
                        raise ReleaseCheckError("database_privileges_missing")
            for privilege in ("UPDATE", "DELETE"):
                if connection.execute("SELECT has_table_privilege(current_user,%s,%s)",
                                      ("student.lesson_content_versions", privilege)).fetchone()[0]:
                    raise ReleaseCheckError("lesson_content_must_be_immutable")
            if connection.execute("SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
                                  "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='student' "
                                  "AND c.relname=ANY(%s) AND i.indisvalid AND i.indisready", (list(INDEXES),)).fetchone()[0] != len(INDEXES):
                raise ReleaseCheckError("required_indexes_missing")
            if connection.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                  "WHERE n.nspname='student' AND c.relkind='S' "
                                  "AND NOT has_sequence_privilege(current_user,c.oid,'USAGE')").fetchone()[0]:
                raise ReleaseCheckError("sequence_privileges_missing")
    except ReleaseCheckError:
        raise
    except Exception:
        # Drivers can include DSNs, users or record values in error messages.
        raise ReleaseCheckError("database_schema_or_connection_unavailable") from None
    return {"ok": True, "dynamicTeachingClosed": True}


if __name__ == "__main__":
    try:
        print(json.dumps(check()))
    except ReleaseCheckError as error:
        print(json.dumps({"ok": False, "code": str(error)}))
        raise SystemExit(1)
