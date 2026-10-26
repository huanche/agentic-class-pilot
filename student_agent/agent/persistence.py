"""Reuse the previous student's public persistence functions and tables."""
from __future__ import annotations

import os
import json
from uuid import uuid4

from . import database


def fresh_session_mode() -> bool:
    """Prefer signed browser snapshots while keeping lesson-scoped DB recovery."""
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


def discard_lesson_session(session: dict, replacement: dict) -> None:
    """Remove this session's obsolete records and store its new video atomically."""
    _bind_database()
    context = replacement["context"]
    scope = (session["id"], str(context["userId"]), str(context["courseId"]))
    snapshot = {key: value for key, value in replacement.items() if key not in {"lock", "launchToken"}}
    with database._db() as connection:
        for table in ("student_messages", "learning_events", "playback_progress",
                      "knowledge_mastery", "task_submissions", "after_class_reports", "student_sessions"):
            connection.execute(f"DELETE FROM student.{table} WHERE session_key=%s AND user_id=%s AND course_id=%s", scope)
        connection.execute(
            "INSERT INTO student.student_sessions "
            "(session_key,user_id,course_id,publication_id,publication_version,classroom_id) VALUES (%s,%s,%s,%s,%s,%s)",
            (*scope, str(context["publication"]["id"]), int(context["publication"].get("version") or 1), replacement["classroomId"]))
        connection.execute(
            "INSERT INTO student.learning_events "
            "(session_key,user_id,course_id,publication_id,classroom_id,event_type,event_id,payload) "
            "VALUES (%s,%s,%s,%s,%s,'agent_state',%s,%s)",
            (*scope, str(context["publication"]["id"]), replacement["classroomId"],
             f"video-reset:{uuid4().hex}", json.dumps(snapshot, ensure_ascii=False)))
        connection.commit()


def reset_lesson(user_id: str, course_id: str, lesson_id: str,
                 current_session_key: str, active_session_keys: list[str] | None = None) -> list[str]:
    """Delete only this student's sessions and learning data for one lesson."""
    _bind_database()
    with database._db() as connection:
        rows = connection.execute(
            "SELECT DISTINCT session_key FROM student.learning_events "
            "WHERE user_id=%s AND course_id=%s AND event_type='agent_state' "
            "AND payload->>'lessonId'=%s",
            (user_id, course_id, lesson_id),
        ).fetchall()
        keys = list(dict.fromkeys([current_session_key, *(active_session_keys or []),
                                   *(str(row[0]) for row in rows)]))
        for table in ("student_messages", "learning_events", "playback_progress",
                      "knowledge_mastery", "task_submissions", "after_class_reports", "student_sessions"):
            connection.execute(
                f"DELETE FROM student.{table} "
                "WHERE session_key = ANY(%s) AND user_id=%s AND course_id=%s",
                (keys, user_id, course_id),
            )
        connection.commit()
    return keys


def save(session: dict, old_count: int) -> None:
    """Persist messages before committing a resumable state snapshot."""
    if not session.get("context"):
        return  # Explicit demo player has no platform identity.
    _bind_database()
    ids = _ids(session)
    context = session["context"]
    database.upsert_session(**ids,
        publication_version=int(context["publication"].get("version") or 1),
        classroom_id=session.get("classroomId"))
    for index, item in enumerate(session["messages"][old_count:], old_count + 1):
        database.upsert_message(**ids, seq=index, role=item["role"],
            phase=item.get("phase"), content=item["text"])
    mastery = {"mastered": (4, "掌握"), "verify": (3, "待独立验证"),
               "partial": (2, "部分理解"), "misconception": (1, "存在误区")}
    previous = ({} if fresh_session_mode() else
                database.read_mastery(ids["user_id"], ids["course_id"], ids["publication_id"]))
    for point in (session.get("dialogue") or {}).get("points") or []:
        if point.get("status") in mastery:
            stars, status = mastery[point["status"]]
            if previous.get(point["id"], 0) > stars:
                continue
            database.upsert_mastery(**ids,
                knowledge_point_id=point["id"], stars=stars, status=status,
                evidence=point.get("evidence"), source=point.get("source"))
    identity = {key: context[key] for key in ("userId", "courseId", "publication")}
    snapshot = {"id": session["id"], "context": identity, "courses": session["courses"],
                "phase": session["phase"], "lessonId": session.get("lessonId"),
                "classroomId": session.get("classroomId"),
                "messages": session["messages"], "dialogue": session.get("dialogue"),
                "preparation": session.get("preparation", "ready"),
                "preparationError": session.get("preparationError", ""),
                "preparationErrorCode": session.get("preparationErrorCode", ""),
                "preparationRequestId": session.get("preparationRequestId", ""),
                "preparationCoverage": session.get("preparationCoverage"),
                "preparationMaterials": session.get("preparationMaterials", []),
                "feedback": session.get("feedback"),
                "classroomFeedback": session.get("classroomFeedback"),
                "postclassStage": session.get("postclassStage"),
                "videoRevision": session.get("videoRevision"),
                "videoUpdated": session.get("videoUpdated", False),
                "contentGeneration": session.get("contentGeneration", 0),
                "version": len(session["messages"])}
    if session["phase"] == "done" and session.get("feedback"):
        # These three writes form one completion. A failure cannot leave a
        # completed session without its individual feedback or resumable result.
        with database._db() as connection:
            write_completion(connection, session, snapshot)
            connection.commit()
        return
    database.record_event(**ids, classroom_id=session.get("classroomId"),
        event_type="agent_state", event_id=f"{session['phase']}:{snapshot['version']}:{uuid4().hex}", payload=snapshot)
    if session["phase"] == "done":
        database.finish_session(session["id"])


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
            "SELECT payload FROM student.learning_events "
            "WHERE session_key = %s AND event_type = 'agent_state' "
            "ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
    if not row:
        return None
    result = dict(row[0])
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
            "AND s.publication_version = %s AND e.classroom_id = %s "
            "AND e.event_type = 'agent_state' AND e.payload->>'lessonId' = %s "
            "AND e.payload->>'phase' IN ('video', 'discussion', 'done') "
            "ORDER BY e.id DESC LIMIT 1",
            (user_id, course_id, publication_id, publication_version, classroom_id, lesson_id),
        ).fetchone()
    return str(row[0]) if row else None


def classroom_scenes(classroom_id: str) -> list[dict]:
    """Reload the published player's source for sessions saved before scene grounding."""
    _bind_database()
    with database._db() as connection:
        row = connection.execute(
            "SELECT scenes FROM teacher.mentra_classrooms WHERE id = %s",
            (classroom_id,),
        ).fetchone()
    return list(row[0] or []) if row else []
