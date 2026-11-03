"""PostgreSQL command journal. Row locks order session before command everywhere."""
from __future__ import annotations

from backend.infrastructure import content_store

import hashlib
import json
import os
import secrets

from backend.infrastructure import database
from backend.infrastructure import persistence
from backend.content import lesson_content
from backend.evidence import records as learning_records
from backend.infrastructure.persistence import RecordConflict

LEASE_SECONDS = 180


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _command(connection, sid, command_id):
    row = connection.execute(
        "SELECT command_id,kind,payload,payload_hash,base_state,accepted_version,content_generation,"
        "status,claim_token,result,failure,lease_until>clock_timestamp(),task_id,student_message_id,content_id "
        "FROM student.student_commands "
        "WHERE session_key=%s AND command_id=%s FOR UPDATE", (sid, command_id)).fetchone()
    return (dict(zip(("commandId", "type", "payload", "hash", "base", "version", "generation", "status",
                      "token", "result", "failure", "live", "taskId", "studentMessageId", "contentId"), row)) if row else None)


def scope(sid):
    with database._db() as connection:
        return persistence.lock_record(connection, sid)


def check_access(record, context):
    if (str(record["user_id"]) != str(context.get("userId"))
            or str(record["course_id"]) != str(context.get("courseId"))):
        raise RecordConflict("ACCESS_DENIED", "学习记录与当前用户或课程不匹配")
    publication = context.get("publication") or {}
    if (str(record["publication_id"]) != str(publication.get("id") or publication.get("publicationId"))
            or record["publication_version"] != publication.get("version")):
        raise RecordConflict("CONTENT_CHANGED", "课时发布信息已变化，请从课时列表重新进入")
    if context.get("source") == "launch_token":
        return  # Lesson binding is already owned by this persisted session, not the browser.
    if (str(context.get("selectedLessonId")) != record["lesson_id"]
            or len(context.get("lessons") or []) != 1
            or str((context["lessons"][0].get("classroom") or {}).get("id")) != str(record["classroom_id"])):
        raise RecordConflict("CONTENT_CHANGED", "课时发布信息已变化，请从课时列表重新进入")


def accept(sid, command, context, validate):
    digest = hashlib.sha256(_json(command).encode()).hexdigest()
    with database._db() as connection:
        record = persistence.lock_record(connection, sid)
        check_access(record, context)
        existing = _command(connection, sid, command["commandId"])
        if existing and existing["hash"] != digest:
            raise RecordConflict("COMMAND_REUSED", "同一命令编号不能提交不同内容")
        if existing and existing["status"] == "completed" and existing["type"] == "reset_lesson":
            return existing
        if record["revoked_at"]:
            raise RecordConflict("SESSION_RESET", "本课学习记录已重置，请重新选择课时")
        if command["contentGeneration"] != record["content_generation"]:
            raise RecordConflict("CONTENT_CHANGED", "课堂内容已更新，请刷新后重试")
        if existing:
            if existing["status"] == "cancelled":
                raise RecordConflict("COMMAND_CANCELLED", "该提交已取消，请刷新学习状态")
            if existing["status"] == "failed":
                if existing["version"] != record["state_version"]:
                    raise RecordConflict("VERSION_CONFLICT", "学习状态已变化，不能重放旧回答")
                connection.execute("UPDATE student.student_commands SET status='pending',failure=NULL,"
                                   "updated_at=now() WHERE session_key=%s AND command_id=%s",
                                   (sid, command["commandId"]))
                existing["status"] = "pending"
            return existing
        if os.environ.get("STUDENT_COMMAND_ACCEPT_NEW", "1") == "0":
            raise RecordConflict("COMMANDS_DRAINING", "学习提交正在维护，请稍后重试")
        if command["expectedStateVersion"] != record["state_version"]:
            raise RecordConflict("VERSION_CONFLICT", "学习状态已更新，请刷新后重试")
        base = dict(record["snapshot"] or {})
        if base.get("phase") in {"postclass", "replay"}:
            base["phase"] = "done"
        base = learning_records.normalize(content_store.hydrate(base, connection=connection))
        if base.get("lessonContent"):
            content_store.store(base["lessonContent"], connection=connection)
        validate(base, command["type"], command["payload"])
        active = connection.execute("SELECT command_id FROM student.student_commands WHERE session_key=%s "
                                    "AND status IN ('pending','processing')", (sid,)).fetchone()
        interrupt = command["type"] in {"finish", "reset_lesson"}
        if active and not interrupt:
            raise RecordConflict("COMMAND_BUSY", "上一条回答仍在处理中，请稍后重试")
        # Failed submissions retain their original text, but a new intent supersedes them.
        connection.execute("UPDATE student.student_commands SET status='cancelled',base_state='{}',claim_token=NULL,"
                           "lease_until=NULL WHERE session_key=%s AND status IN "
                           + ("('pending','processing','failed')" if interrupt else "('failed')"), (sid,))
        version = record["state_version"] + 1
        base.update(stateVersion=record["state_version"], contentGeneration=record["content_generation"])
        accepted = dict(base, stateVersion=version)
        connection.execute("UPDATE student.student_sessions SET state_version=%s,snapshot=%s,content_id=%s,last_active_at=now() "
                           "WHERE session_key=%s", (version, _json(persistence.snapshot(accepted)),
                           (base.get("contentRef") or {}).get("contentId"), sid))
        task_id = learning_records.input_task(base, command["type"], command["commandId"])
        student_message_id = (learning_records.message_identity(base, command["commandId"])
                              if command["type"] in {"submit_answer", "postclass_answer", "request_help", "ask_question"} else None)
        connection.execute(
            "INSERT INTO student.student_commands (session_key,command_id,payload_hash,kind,payload,base_state,"
            "accepted_version,content_generation,status,task_id,student_message_id,content_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s)",
            (sid, command["commandId"], digest, command["type"], _json(command["payload"]), _json(persistence.snapshot(base)),
             version, record["content_generation"], task_id, student_message_id, (base.get("contentRef") or {}).get("contentId")))
        return _command(connection, sid, command["commandId"])


def claim(sid, command_id):
    with database._db() as connection:
        record = persistence.lock_record(connection, sid)
        command = _command(connection, sid, command_id)
        if not command or command["status"] not in {"pending", "processing"}:
            return None
        if command["status"] == "processing" and command["live"]:
            return None
        if (record["revoked_at"] or record["state_version"] != command["version"]
                or record["content_generation"] != command["generation"]):
            connection.execute("UPDATE student.student_commands SET status='cancelled',base_state='{}',claim_token=NULL,"
                               "lease_until=NULL WHERE session_key=%s AND command_id=%s", (sid, command_id))
            return None
        token = secrets.token_hex(16)
        command["base"] = learning_records.normalize(content_store.hydrate(command["base"], connection=connection))
        if command["base"].get("lessonContent"):
            content_store.store(command["base"]["lessonContent"], connection=connection)
        task_id = learning_records.input_task(command["base"], command["type"], command_id)
        student_id = (learning_records.message_identity(command["base"], command_id)
                      if command["type"] in {"submit_answer", "postclass_answer", "request_help", "ask_question"} else None)
        connection.execute("UPDATE student.student_commands SET status='processing',claim_token=%s,"
                           "lease_until=clock_timestamp()+(%s*interval '1 second'),attempts=attempts+1,"
                           "base_state=%s,task_id=COALESCE(task_id,%s),student_message_id=COALESCE(student_message_id,%s),"
                           "content_id=COALESCE(content_id,%s),updated_at=now() WHERE session_key=%s AND command_id=%s",
                           (token, LEASE_SECONDS, _json(persistence.snapshot(command["base"])), task_id, student_id,
                            (command["base"].get("contentRef") or {}).get("contentId"), sid, command_id))
        command.update(status="processing", token=token, taskId=task_id, studentMessageId=student_id)
        return command


def renew(sid, command_id, token):
    with database._db() as connection:
        return bool(connection.execute(
            "UPDATE student.student_commands SET lease_until=clock_timestamp()+(%s*interval '1 second') "
            "WHERE session_key=%s AND command_id=%s AND claim_token=%s AND status='processing' "
            "AND lease_until>clock_timestamp() RETURNING 1", (LEASE_SECONDS, sid, command_id, token)).fetchone())


def complete(sid, command_id, token, changed):
    with database._db() as connection:
        record = persistence.lock_record(connection, sid)
        command = _command(connection, sid, command_id)
        if (not command or command["status"] != "processing" or command["token"] != token
                or not command["live"] or record["revoked_at"]
                or record["state_version"] != command["version"]
                or record["content_generation"] != command["generation"]):
            raise RecordConflict("VERSION_CONFLICT", "提交已过期或被取消，请刷新学习状态")
        base = content_store.hydrate(command["base"], connection=connection)
        draft = learning_records.transition(base, dict(base, **changed), command_id=command_id)
        draft.update(stateVersion=record["state_version"] + 1, contentGeneration=command["generation"])
        persistence.write_state(connection, draft, len(command["base"]["messages"]))
        result = persistence.snapshot(draft)
        connection.execute("UPDATE student.student_commands SET status='completed',result=%s,base_state='{}',"
                           "claim_token=NULL,lease_until=NULL,failure=NULL,updated_at=now() "
                           "WHERE session_key=%s AND command_id=%s", (_json(result), sid, command_id))
        return result


def fail(sid, command_id, token, failure):
    with database._db() as connection:
        connection.execute("UPDATE student.student_commands SET status='failed',failure=%s,claim_token=NULL,"
                           "lease_until=NULL,updated_at=now() WHERE session_key=%s AND command_id=%s "
                           "AND claim_token=%s AND status='processing' AND lease_until>clock_timestamp()",
                           (_json(failure), sid, command_id, token))


def complete_reset(sid, command_id, token, fresh):
    with database._db() as connection:
        unlocked = scope(sid)
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                           (f"{unlocked['user_id']}:{unlocked['course_id']}:{unlocked['lesson_id']}",))
        record = persistence.lock_record(connection, sid)
        command = _command(connection, sid, command_id)
        if (not command or command["token"] != token or command["status"] != "processing"
                or not command["live"] or record["revoked_at"]
                or record["state_version"] != command["version"]):
            raise RecordConflict("VERSION_CONFLICT", "重置请求已过期，请刷新后重试")
        persistence.erase_lesson(connection, record["user_id"], record["course_id"], record["lesson_id"], sid)
        persistence.enqueue_sync(connection, dict(command["base"], stateVersion=record["state_version"]+1), "reset")
        ids = persistence._ids(fresh)
        database.upsert_session(**ids, publication_version=int(fresh["context"]["publication"]["version"]),
                                connection=connection)
        fresh.update(stateVersion=1, contentGeneration=0)
        persistence.write_state(connection, fresh, 0)
        result = persistence.snapshot(fresh)
        # Only the reset receipt survives, without old answers or the old snapshot.
        connection.execute("INSERT INTO student.student_commands (session_key,command_id,payload_hash,kind,"
                           "payload,base_state,accepted_version,content_generation,status,result) "
                           "VALUES (%s,%s,%s,'reset_lesson','{}','{}',%s,%s,'completed',%s)",
                           (sid, command_id, command["hash"], record["state_version"]+1,
                            record["content_generation"]+1, _json(result)))
        return result


def read(sid, command_id):
    with database._db() as connection:
        return _command(connection, sid, command_id)


def next_pending():
    with database._db() as connection:
        row = connection.execute("SELECT session_key,command_id FROM student.student_commands "
            "WHERE status='pending' OR (status='processing' AND lease_until<clock_timestamp()) "
            "ORDER BY created_at LIMIT 1").fetchone()
        return row


def claim_sync():
    with database._db() as connection:
        row = connection.execute("SELECT event_id,session_key,user_id,course_id,classroom_id,event "
            "FROM student.pending_progress_sync WHERE (status='pending' AND next_retry_at<=now()) "
            "OR (status='processing' AND lease_until<now()) ORDER BY created_at "
            "FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
        if not row:
            return None
        token = secrets.token_hex(16)
        connection.execute("UPDATE student.pending_progress_sync SET status='processing',claim_token=%s,"
                           "lease_until=now()+interval '30 seconds',attempts=attempts+1 WHERE event_id=%s",
                           (token, row[0]))
        return row, token


def finish_sync(event_id, token, success):
    with database._db() as connection:
        connection.execute("UPDATE student.pending_progress_sync SET status=%s,claim_token=NULL,lease_until=NULL,"
                           "next_retry_at=now()+interval '30 seconds' WHERE event_id=%s AND claim_token=%s",
                           ("completed" if success else "pending", event_id, token))
