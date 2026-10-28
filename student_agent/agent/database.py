"""Database operations for the student classroom.

The student service owns learning records in the student schema. This module
keeps its database access local to the service.
"""
from __future__ import annotations

import json
import os


def _db():
    import psycopg

    url = (os.environ.get("STUDENT_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError("请配置 STUDENT_DATABASE_URL 或 DATABASE_URL")
    return psycopg.connect(url.replace("+psycopg", ""), autocommit=False)


def upsert_session(session_key: str, user_id: str, course_id: str,
                   publication_id: str, publication_version: int,
                   classroom_id: str | None = None) -> None:
    with _db() as connection:
        connection.execute(
            "INSERT INTO student.student_sessions "
            "(session_key, user_id, course_id, publication_id, publication_version, classroom_id) "
            "VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (session_key) DO UPDATE SET last_active_at = now()",
            (session_key, user_id, course_id, publication_id, publication_version, classroom_id),
        )
        connection.commit()


def upsert_message(session_key: str, user_id: str, course_id: str,
                   publication_id: str, seq: int, role: str,
                   phase: str | None, content: str) -> None:
    with _db() as connection:
        connection.execute(
            "INSERT INTO student.student_messages "
            "(session_key, user_id, course_id, publication_id, seq, role, phase, content) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (session_key, seq) DO NOTHING",
            (session_key, user_id, course_id, publication_id, seq, role, phase, content),
        )
        connection.commit()


def read_mastery(user_id: str, course_id: str, publication_id: str) -> dict[str, int]:
    with _db() as connection:
        rows = connection.execute(
            "SELECT knowledge_point_id, stars FROM student.knowledge_mastery "
            "WHERE user_id = %s AND course_id = %s AND publication_id = %s",
            (user_id, course_id, publication_id),
        ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def upsert_mastery(session_key: str, user_id: str, course_id: str,
                   publication_id: str, knowledge_point_id: str,
                   stars: int, status: str, evidence: str | None = None,
                   source: str | None = None) -> None:
    with _db() as connection:
        connection.execute(
            "INSERT INTO student.knowledge_mastery "
            "(session_key, user_id, course_id, publication_id, knowledge_point_id, stars, status, evidence, source) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (user_id, course_id, publication_id, knowledge_point_id) DO UPDATE SET "
            "stars = GREATEST(student.knowledge_mastery.stars, EXCLUDED.stars), "
            "status = EXCLUDED.status, evidence = EXCLUDED.evidence, "
            "source = EXCLUDED.source, updated_at = now()",
            (session_key, user_id, course_id, publication_id, knowledge_point_id,
             stars, status, evidence, source),
        )
        connection.commit()


def record_event(session_key: str, user_id: str, course_id: str,
                 publication_id: str, event_type: str, payload: dict,
                 classroom_id: str | None = None, event_id: str | None = None) -> None:
    with _db() as connection:
        connection.execute(
            "INSERT INTO student.learning_events "
            "(session_key, user_id, course_id, publication_id, classroom_id, event_type, event_id, payload) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (session_key, event_type, event_id) DO NOTHING",
            (session_key, user_id, course_id, publication_id, classroom_id,
             event_type, event_id, json.dumps(payload, ensure_ascii=False)),
        )
        connection.commit()


def finish_session(session_key: str) -> None:
    with _db() as connection:
        connection.execute(
            "UPDATE student.student_sessions "
            "SET ended_at = COALESCE(ended_at, now()), last_active_at = now() "
            "WHERE session_key = %s",
            (session_key,),
        )
        connection.commit()
