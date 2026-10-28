"""Authenticated platform commands that write only student-owned data."""

from __future__ import annotations

import hmac
import logging
import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from agent.database import _db

router = APIRouter()
log = logging.getLogger(__name__)


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
    expected = os.environ.get("STUDENT_SERVICE_KEY", "")
    if not expected or not hmac.compare_digest(x_student_service_key or "", expected):
        raise HTTPException(403, "Invalid service credentials")
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
