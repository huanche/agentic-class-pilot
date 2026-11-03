"""Atomic learning records, authoritative snapshots and legacy-compatible restoration."""
from __future__ import annotations

from backend.infrastructure import content_store

import os
import json
import logging
from uuid import uuid4

from backend.contracts import SessionError

from backend.infrastructure import database
from backend.content import lesson_content
from backend.evidence import records as learning_records


def fresh_session_mode() -> bool:
    """Legacy browser preference, independent of authenticated lesson recovery."""
    return os.environ.get("STUDENT_FRESH_SESSION_MODE", "1").strip().lower() not in {"0", "false", "off"}


def _bind_database() -> None:
    os.environ.setdefault("STUDENT_DATABASE_URL", os.environ.get("DATABASE_URL", ""))
    if not os.environ.get("STUDENT_DATABASE_URL") and not os.environ.get("STUDENT_DEMO_MODE"):
        raise RuntimeError("请配置 STUDENT_DATABASE_URL 或 DATABASE_URL")


def _ids(session: dict) -> dict:
    context = session["context"]
    return {"session_key": session["id"], "user_id": str(context["userId"]),
            "course_id": str(context["courseId"]),
            "publication_id": str(context["publication"]["id"])}


def _delete_records(connection, keys: list[str], user_id: str, course_id: str) -> None:
    for table in ("student_messages", "learning_events", "playback_progress",
                  "knowledge_mastery", "task_submissions", "after_class_reports"):
        connection.execute(f"DELETE FROM student.{table} WHERE session_key=ANY(%s) AND user_id=%s AND course_id=%s",
                           (keys, user_id, course_id))
    connection.execute("DELETE FROM student.student_commands WHERE session_key=ANY(%s)", (keys,))
    connection.execute("DELETE FROM student.pending_progress_sync WHERE session_key=ANY(%s)", (keys,))


def discard_lesson_session(session: dict, replacement: dict) -> None:
    _bind_database()
    with database._db() as connection:
        record = lock_record(connection, session["id"])
        check_record(record, session)
        _delete_records(connection, [session["id"]], record["user_id"], record["course_id"])
        connection.execute("UPDATE student.student_sessions SET ended_at=NULL,started_at=now() "
                           "WHERE session_key=%s", (session["id"],))
        replacement["stateVersion"] = record["state_version"] + 1
        replacement["contentGeneration"] = record["content_generation"] + 1
        token = replacement.get("launchToken")
        prepared = learning_records.transition(content_store.hydrate(session, connection=connection), replacement)
        replacement.clear()
        replacement.update(prepared)
        if token:
            replacement["launchToken"] = token
        write_state(connection, replacement, 0)


def erase_lesson(connection, user_id: str, course_id: str, lesson_id: str,
                 current_session_key: str, active_session_keys=None) -> list[str]:
    rows = connection.execute(
        "SELECT session_key FROM student.student_sessions WHERE user_id=%s AND course_id=%s "
        "AND (lesson_id=%s OR session_key=%s OR session_key=ANY(%s)) ORDER BY session_key FOR UPDATE",
        (user_id, course_id, lesson_id, current_session_key, active_session_keys or [])).fetchall()
    keys = list(dict.fromkeys([current_session_key, *(str(row[0]) for row in rows)]))
    _delete_records(connection, keys, user_id, course_id)
    connection.execute("UPDATE student.student_sessions SET revoked_at=now(),snapshot=NULL,"
                       "content_id=NULL,state_version=state_version+1,content_generation=content_generation+1 "
                       "WHERE session_key=ANY(%s) AND user_id=%s AND course_id=%s", (keys, user_id, course_id))
    return keys


def reset_lesson(user_id: str, course_id: str, lesson_id: str,
                 current_session_key: str, active_session_keys: list[str] | None = None) -> list[str]:
    _bind_database()
    with database._db() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                           (f"{user_id}:{course_id}:{lesson_id}",))
        record = lock_record(connection, current_session_key)
        if str(record["user_id"]) != user_id or str(record["course_id"]) != course_id:
            raise RecordConflict("ACCESS_DENIED", "学习记录与当前用户或课程不匹配")
        if record["revoked_at"]:
            raise RecordConflict("SESSION_RESET", "本课学习记录已重置，请重新选择课时")
        keys = erase_lesson(connection, user_id, course_id, lesson_id, current_session_key, active_session_keys)
        old = record["snapshot"] or {}
        enqueue_sync(connection, dict(old, stateVersion=record["state_version"]+1), "reset")
        return keys


class RecordConflict(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def snapshot(session: dict) -> dict:
    result = {key: value for key, value in session.items()
              if key not in {"lock", "launchToken", "pendingSubmission", "reset", "_cancelPending", "lessonContent", "dynamicTurn"}}
    context = session.get("context")
    if context:
        result["context"] = {key: context[key] for key in ("userId", "courseId", "publication")}
    result["version"] = len(session["messages"])  # Legacy snapshot compatibility only.
    return result


def lock_record(connection, sid: str) -> dict:
    row = connection.execute(
        "SELECT user_id,course_id,publication_id,publication_version,classroom_id,"
        "state_version,content_generation,revoked_at,snapshot,lesson_id "
        "FROM student.student_sessions WHERE session_key=%s FOR UPDATE", (sid,)).fetchone()
    if not row:
        raise RecordConflict("HISTORY_NOT_FOUND", "会话不存在，请重新进入课堂")
    return dict(zip(("user_id", "course_id", "publication_id", "publication_version", "classroom_id",
                     "state_version", "content_generation", "revoked_at", "snapshot", "lesson_id"), row))


def check_record(record: dict, session: dict) -> None:
    if record["revoked_at"]:
        raise RecordConflict("SESSION_RESET", "本课学习记录已重置，请重新选择课时")
    ids = _ids(session)
    if any(str(record[key]) != str(ids[key]) for key in ("user_id", "course_id")):
        raise RecordConflict("ACCESS_DENIED", "学习记录与当前用户或课程不匹配")
    unbound_entry = ((record.get("snapshot") or {}).get("phase") == "idle"
                     and record.get("lesson_id") is None and record.get("classroom_id") is None)
    if str(record["publication_id"]) != ids["publication_id"] and not unbound_entry:
        raise RecordConflict("CONTENT_CHANGED", "课时发布信息已变化，请重新进入课堂")
    if (record["state_version"] != session.get("stateVersion", 0)
            or record["content_generation"] != session.get("contentGeneration", 0)):
        raise RecordConflict("VERSION_CONFLICT", "学习状态已更新，请刷新后重试")


def enqueue_sync(connection, session: dict, event: str) -> None:
    context = session.get("context") or {}
    if not session.get("classroomId") or not context:
        return
    connection.execute(
        "INSERT INTO student.pending_progress_sync "
        "(event_id,session_key,user_id,course_id,classroom_id,event) VALUES (%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT(event_id) DO NOTHING",
        (f"{session['id']}:{session.get('stateVersion', 0)}:{event}", session["id"],
         str(context["userId"]), str(context["courseId"]), session["classroomId"], event))


def write_records(connection, session):
    """The owning learning transaction also owns these records and their rollback."""
    ids = _ids(session)
    row = connection.execute("SELECT snapshot->'learningRecords',snapshot->>'recordsStored' "
                             "FROM student.student_sessions WHERE session_key=%s", (session["id"],)).fetchone()
    prior = row[0] if row and row[1] == "true" and row[0] else {}
    if prior.get("scope") != session["learningRecords"].get("scope"):
        prior = {}
    for group, event_type, key in (("episodes", "learning_episode", "episodeId"),
                                   ("tasks", "learning_task", "taskId"),
                                   ("observations", "learning_observation", "observationId"),
                                     ("assistance", "learning_assistance", "assistanceId"),
                                     ("decisions", "teaching_decision", "decisionId")):
        previous = {item[key]: item for item in prior.get(group, [])}
        for item in session["learningRecords"].get(group, []):
            if previous.get(item[key]) == item:
                continue
            if group == "tasks":
                connection.execute("INSERT INTO student.learning_events (session_key,user_id,course_id,publication_id,"
                    "classroom_id,event_type,event_id,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT(session_key,event_type,event_id) DO UPDATE SET payload=EXCLUDED.payload",
                    (session["id"], ids["user_id"], ids["course_id"], ids["publication_id"], session.get("classroomId"),
                     event_type, item[key], json.dumps(item, ensure_ascii=False)))
            else:
                database.record_event(**ids, classroom_id=session.get("classroomId"), event_type=event_type,
                                      event_id=item[key], payload=item, connection=connection)


def write_state(connection, session: dict, old_count: int) -> None:
    """All business records and the authoritative snapshot use the caller's transaction."""
    session.update(learning_records.normalize(content_store.hydrate(session, connection=connection)))
    learning_records.validate(session)
    if session.get("lessonContent"):
        content_store.store(session["lessonContent"], connection=connection)
    if not session.get("recordsStored"):
        old_count = 0
    ids = _ids(session)
    context = session["context"]
    for index, item in enumerate(session["messages"][old_count:], old_count + 1):
        database.upsert_message(**ids, seq=index, role=item["role"],
                                phase=item.get("phase"), content=item["text"], message_id=item["messageId"],
                                task_id=item["taskId"], episode_id=item["episodeId"], connection=connection)
    mastery = {"mastered": (4, "掌握"), "verify": (3, "待独立验证"),
               "partial": (2, "部分理解"), "misconception": (1, "存在误区")}
    previous = ({} if fresh_session_mode() else database.read_mastery(
        ids["user_id"], ids["course_id"], ids["publication_id"], connection=connection))
    for point in (session.get("dialogue") or {}).get("points") or []:
        if point.get("status") in mastery:
            stars, status = mastery[point["status"]]
            if previous.get(point["id"], 0) > stars:
                continue
            database.upsert_mastery(**ids, knowledge_point_id=point["id"], stars=stars,
                status=status, evidence=point.get("evidence"), source=point.get("source"), connection=connection)
    write_records(connection, session)
    session["recordsStored"] = True
    saved = snapshot(session)
    connection.execute(
        "UPDATE student.student_sessions SET started_at=CASE WHEN snapshot->>'phase'='idle' AND %s='video' "
        "THEN now() ELSE started_at END,snapshot=%s,state_version=%s,content_generation=%s,"
        "lesson_id=%s,publication_id=%s,publication_version=%s,classroom_id=%s,content_id=%s,last_active_at=now() "
        "WHERE session_key=%s",
        (session["phase"], json.dumps(saved, ensure_ascii=False), session["stateVersion"], session.get("contentGeneration", 0),
         session.get("lessonId"), ids["publication_id"], int(context["publication"].get("version") or 1),
         session.get("classroomId"), (session.get("contentRef") or {}).get("contentId"), session["id"]))
    if session["phase"] == "done" and session.get("feedback"):
        write_completion(connection, session, saved)
        enqueue_sync(connection, session, "ended")
    else:
        database.record_event(**ids, classroom_id=session.get("classroomId"), event_type="agent_state",
            event_id=f"state:{session['stateVersion']}", payload=saved, connection=connection)
        if session["phase"] == "video":
            enqueue_sync(connection, session, "started")


def save(session: dict, old_count: int) -> None:
    if not session.get("context"):
        session["stateVersion"] = session.get("stateVersion", 0) + 1
        return
    _bind_database()
    ids = _ids(session)
    with database._db() as connection:
        database.upsert_session(**ids,
            publication_version=int(session["context"]["publication"].get("version") or 1),
            classroom_id=session.get("classroomId"), connection=connection)
        record = lock_record(connection, session["id"])
        check_record(record, session)
        active = connection.execute(
            "SELECT command_id FROM student.student_commands WHERE session_key=%s "
            "AND status IN ('pending','processing')", (session["id"],)).fetchone()
        if active:
            if not session.get("_cancelPending"):
                raise RecordConflict("COMMAND_BUSY", "上一条回答仍在处理中，请稍后重试")
            connection.execute("UPDATE student.student_commands SET status='cancelled',base_state='{}',claim_token=NULL,"
                               "lease_until=NULL WHERE session_key=%s AND status IN ('pending','processing','failed')",
                               (session["id"],))
        connection.execute("UPDATE student.student_commands SET status='cancelled',base_state='{}' "
                           "WHERE session_key=%s AND status='failed'", (session["id"],))
        before = content_store.hydrate(record["snapshot"], connection=connection) if record["snapshot"] else dict(session, messages=[], dialogue=None)
        session.update(learning_records.transition(before, content_store.hydrate(session, connection=connection)))
        session["stateVersion"] = record["state_version"] + 1
        write_state(connection, session, old_count)
        connection.commit()


def write_completion(connection, session: dict, snapshot: dict) -> None:
    """Write final feedback and snapshot inside the caller's transaction."""
    ids = _ids(session)
    events = [("lesson_feedback", "final", session["feedback"]),
              ("agent_state", f"done:{uuid4().hex}", snapshot)]
    if session.get("classroomFeedback"):
        events.append(("classroom_feedback", "final", session["classroomFeedback"]))
    for event_type, event_id, payload in events:
        conflict = ("DO UPDATE SET payload=EXCLUDED.payload" if event_type == "lesson_feedback"
                    else "DO NOTHING")
        connection.execute(
            "INSERT INTO student.learning_events "
            "(session_key,user_id,course_id,publication_id,classroom_id,event_type,event_id,payload) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            f"ON CONFLICT (session_key,event_type,event_id) {conflict}",
            (ids["session_key"], ids["user_id"], ids["course_id"], ids["publication_id"],
             session.get("classroomId"), event_type, event_id,
             json.dumps(payload, ensure_ascii=False)),
        )
    connection.execute(
        "UPDATE student.student_sessions SET ended_at=COALESCE(ended_at,now()), "
        "last_active_at=now() WHERE session_key=%s", (session["id"],))


def restore(sid: str) -> dict | None:
    _bind_database()
    with database._db() as connection:
        row = connection.execute(
            "SELECT snapshot,state_version,content_generation,revoked_at FROM student.student_sessions "
            "WHERE session_key=%s", (sid,)).fetchone()
        if not row or row[3]:
            return None
        saved, version, generation, _ = row
        if not saved:
            legacy = connection.execute(
                "SELECT payload FROM student.learning_events WHERE session_key=%s AND event_type='agent_state' "
                "ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
            saved = legacy[0] if legacy else None
        if not saved:
            return None
        result = dict(saved, stateVersion=version, contentGeneration=generation)
        if result.get("phase") in {"postclass", "replay"}:
            result["phase"] = "done"  # Historic snapshots stored a view as a lifecycle phase.
        pending = connection.execute(
            "SELECT command_id,status,kind,payload,accepted_version,content_generation FROM student.student_commands "
            "WHERE session_key=%s AND status IN ('pending','processing','failed') ORDER BY created_at DESC LIMIT 1",
            (sid,)).fetchone()
        result["pendingSubmission"] = ({"commandId": pending[0], "status": pending[1],
                                         "type": pending[2], "payload": pending[3],
                                         "expectedStateVersion": pending[4]-1,
                                         "contentGeneration": pending[5]} if pending else None)
    result = learning_records.normalize(content_store.hydrate(result))
    result["lock"] = __import__("threading").Lock()
    return result


def latest_session_key(user_id: str, course_id: str, publication_id: str,
                       publication_version: int, lesson_id: str,
                       classroom_id: str) -> str | None:
    """Find the most recent saved state for this student's published lesson."""
    _bind_database()
    with database._db() as connection:
        row = connection.execute(
            "SELECT e.session_key FROM student.learning_events AS e "
            "JOIN student.student_sessions AS s ON s.session_key = e.session_key "
            "WHERE e.user_id = %s AND e.course_id = %s AND e.publication_id = %s "
            "AND s.revoked_at IS NULL AND s.publication_version = %s AND e.classroom_id = %s "
            "AND e.event_type = 'agent_state' AND e.payload->>'lessonId' = %s "
            "AND e.payload->>'phase' IN ('video', 'discussion', 'done', 'postclass', 'replay') "
            "ORDER BY e.id DESC LIMIT 1",
            (user_id, course_id, publication_id, publication_version, classroom_id, lesson_id),
        ).fetchone()
    return str(row[0]) if row else None


def classroom_scenes(classroom_id: str) -> list[dict]:
    """Reload old-session scenes through the platform contract."""
    from backend.infrastructure import platform_client

    try:
        return platform_client.fetch_classroom_scenes(classroom_id)
    except SessionError as error:
        if error.status_code in (401, 403):
            raise
        logging.getLogger(__name__).warning(
            "replay_scene_api_unavailable classroom_id=%s detail=%s",
            classroom_id, getattr(error, "detail", ""),
        )
        return []
