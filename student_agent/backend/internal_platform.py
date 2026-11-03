"""Authenticated platform commands that write only student-owned data."""

from __future__ import annotations

import hmac
import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from backend.infrastructure.database import _db

router = APIRouter()
log = logging.getLogger(__name__)


def _check_platform_service_key(value: str | None) -> None:
    expected = os.environ.get("STUDENT_SERVICE_KEY", "")
    if not expected or not hmac.compare_digest(value or "", expected):
        raise HTTPException(403, "Invalid service credentials")


class PublishedLessonKnowledgeRequest(BaseModel):
    courseId: str = Field(min_length=1, max_length=128)
    lessonId: str = Field(min_length=1, max_length=128)
    videoRevision: str = Field(pattern=r"^[0-9a-f]{64}$")
    classroomId: str = Field(min_length=1, max_length=128)
    scenes: list[dict] = Field(max_length=1000)


@router.post("/api/internal/platform/published-lesson-knowledge")
def enqueue_published_lesson_knowledge(
    body: PublishedLessonKnowledgeRequest,
    x_student_service_key: str | None = Header(default=None),
) -> dict[str, str]:
    _check_platform_service_key(x_student_service_key)
    try:
        with _db() as connection:
            connection.execute(
                "INSERT INTO student.published_lesson_knowledge "
                "(course_id, lesson_id, video_revision, classroom_id, scenes) "
                "VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (course_id, lesson_id, video_revision) DO NOTHING",
                (body.courseId, body.lessonId, body.videoRevision,
                 body.classroomId, Jsonb(body.scenes)),
            )
    except Exception as error:
        log.exception("Student knowledge queue storage failed")
        raise HTTPException(503, "Student knowledge queue unavailable") from error
    return {"courseId": body.courseId, "lessonId": body.lessonId,
            "videoRevision": body.videoRevision}


class LearningDataRequest(BaseModel):
    userIds: list[str] = Field(max_length=10000)


@router.post("/api/internal/platform/courses/{course_id}/learning-data")
def course_learning_data(
    course_id: str, body: LearningDataRequest,
    x_student_service_key: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return the same bounded learning rows used by the platform teacher view."""
    _check_platform_service_key(x_student_service_key)
    if not body.userIds:
        return {"sessions": [], "mastery": [], "eventSummary": {}}
    try:
        with _db() as connection:
            params = (body.userIds, course_id)
            sessions = connection.execute(
                "SELECT session_key, user_id, publication_version, classroom_id, "
                "started_at, last_active_at, ended_at IS NOT NULL AS ended "
                "FROM student.student_sessions WHERE user_id = ANY(%s) "
                "AND course_id=%s ORDER BY started_at DESC LIMIT 50", params,
            ).fetchall()
            mastery = connection.execute(
                "SELECT user_id, knowledge_point_id, stars, status, evidence, updated_at "
                "FROM student.knowledge_mastery WHERE user_id = ANY(%s) "
                "AND course_id=%s ORDER BY updated_at DESC LIMIT 100", params,
            ).fetchall()
            events = connection.execute(
                "SELECT event_type, count(*) FROM student.learning_events "
                "WHERE user_id = ANY(%s) AND course_id=%s GROUP BY event_type", params,
            ).fetchall()
    except Exception as error:
        log.exception("Student learning data read failed")
        raise HTTPException(503, "Student learning data unavailable") from error
    return {
        "sessions": [{"sessionKey": r[0], "userId": r[1], "publicationVersion": r[2],
                      "classroomId": r[3], "startedAt": str(r[4]), "lastActiveAt": str(r[5]),
                      "ended": bool(r[6])} for r in sessions],
        "mastery": [{"userId": r[0], "knowledgePointId": r[1], "stars": r[2],
                     "status": r[3], "evidence": r[4], "updatedAt": str(r[5])} for r in mastery],
        "eventSummary": {r[0]: r[1] for r in events},
    }


@router.get("/api/internal/platform/courses/{course_id}/users/{user_id}/progress")
def user_course_progress(
    course_id: str, user_id: str,
    x_student_service_key: str | None = Header(default=None),
) -> dict[str, Any]:
    """Student-owned portion of the per-course progress calculation."""
    _check_platform_service_key(x_student_service_key)
    try:
        with _db() as connection:
            learned = connection.execute(
                "SELECT count(DISTINCT classroom_id), max(last_active_at), count(*) "
                "FROM student.student_sessions WHERE user_id=%s AND course_id=%s",
                (user_id, course_id),
            ).fetchone()
            ended = connection.execute(
                "SELECT count(*) FROM student.student_sessions "
                "WHERE user_id=%s AND course_id=%s AND ended_at IS NOT NULL",
                (user_id, course_id),
            ).fetchone()
            stars = connection.execute(
                "SELECT coalesce(sum(stars),0) FROM student.knowledge_mastery "
                "WHERE user_id=%s AND course_id=%s", (user_id, course_id),
            ).fetchone()
    except Exception as error:
        log.exception("Student progress read failed")
        raise HTTPException(503, "Student progress unavailable") from error
    return {
        "learnedLessons": int(learned[0] or 0),
        "lastActiveAt": str(learned[1]) if learned[1] else None,
        "sessionCount": int(learned[2] or 0),
        "endedSessions": int(ended[0] or 0),
        "stars": int(stars[0] or 0),
    }


class ChatSessionsRequest(BaseModel):
    userIds: list[str] = Field(max_length=10000)
    limit: int = Field(default=300, ge=1, le=500)


@router.post("/api/internal/platform/courses/{course_id}/chat-sessions")
def course_chat_sessions(
    course_id: str, body: ChatSessionsRequest,
    x_student_service_key: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    """Return only sessions for student IDs already authorized by the platform."""
    _check_platform_service_key(x_student_service_key)
    if not body.userIds:
        return []
    try:
        with _db() as connection:
            rows = connection.execute(
                "SELECT s.session_key, s.user_id, s.classroom_id, s.started_at, "
                "s.last_active_at, s.ended_at, "
                "COALESCE(s.lesson_id, s.snapshot->>'lessonId', state.payload->>'lessonId'), "
                "(SELECT count(*) FROM student.student_messages m "
                " WHERE m.session_key=s.session_key) "
                "FROM student.student_sessions s "
                "LEFT JOIN LATERAL (SELECT event.payload FROM student.learning_events event "
                " WHERE event.session_key=s.session_key AND event.event_type='agent_state' "
                " ORDER BY event.created_at DESC, event.id DESC LIMIT 1) state ON true "
                "WHERE s.course_id=%s AND s.user_id=ANY(%s) AND s.revoked_at IS NULL "
                "ORDER BY s.last_active_at DESC, s.session_key DESC LIMIT %s",
                (course_id, body.userIds, body.limit),
            ).fetchall()
    except Exception as error:
        log.exception("Student chat session read failed")
        raise HTTPException(503, "Student chat records unavailable") from error
    return [{
        "sessionKey": row[0], "studentId": row[1], "classroomId": row[2],
        "startedAt": row[3].isoformat(), "lastActiveAt": row[4].isoformat(),
        "ended": row[5] is not None, "lessonId": row[6],
        "messageCount": int(row[7]),
    } for row in rows]


class ChatMessagesRequest(BaseModel):
    userIds: list[str] = Field(max_length=10000)
    phase: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=1000, ge=1, le=5000)
    offset: int = Field(default=0, ge=0)


@router.post("/api/internal/platform/courses/{course_id}/chat-sessions/{session_key}/messages")
def course_chat_messages(
    course_id: str, session_key: str, body: ChatMessagesRequest,
    x_student_service_key: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    """Keep existence of other students' sessions private from the caller."""
    _check_platform_service_key(x_student_service_key)
    if not body.userIds:
        raise HTTPException(404, "Student chat session not found")
    try:
        with _db() as connection:
            allowed = connection.execute(
                "SELECT 1 FROM student.student_sessions WHERE session_key=%s "
                "AND course_id=%s AND user_id=ANY(%s) AND revoked_at IS NULL",
                (session_key, course_id, body.userIds),
            ).fetchone()
            if not allowed:
                raise HTTPException(404, "Student chat session not found")
            phase_filter = " AND phase=%s" if body.phase is not None else ""
            params = (session_key, course_id, body.phase, body.limit, body.offset) if body.phase is not None else (
                session_key, course_id, body.limit, body.offset)
            rows = connection.execute(
                "SELECT seq, role, phase, content, created_at "
                "FROM student.student_messages WHERE session_key=%s AND course_id=%s"
                + phase_filter + " ORDER BY seq LIMIT %s OFFSET %s", params,
            ).fetchall()
    except HTTPException:
        raise
    except Exception as error:
        log.exception("Student chat message read failed")
        raise HTTPException(503, "Student chat records unavailable") from error
    return [{"seq": row[0], "role": row[1], "phase": row[2],
             "content": row[3], "createdAt": row[4].isoformat()} for row in rows]
