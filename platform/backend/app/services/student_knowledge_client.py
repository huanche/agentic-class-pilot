"""Platform adapter for the student-owned published knowledge job API."""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.generated.platform_student_api import AuthenticatedClient
from app.generated.platform_student_api.api.default.enqueue_published_lesson_knowledge_at_student import (
    sync_detailed,
)
from app.generated.platform_student_api.models import (
    EnqueuePublishedLessonKnowledgeAtStudentBody,
    EnqueuePublishedLessonKnowledgeAtStudentBodyScenesItem,
    EnqueuePublishedLessonKnowledgeAtStudentResponse200,
)


class StudentKnowledgeUnavailable(Exception):
    """The student service did not confirm durable job registration."""


def enqueue_student_knowledge(
    course_id: str, lesson_id: str, revision: str, classroom_id: str,
    scenes: list[dict],
) -> None:
    if not settings.STUDENT_SERVICE_KEY:
        raise StudentKnowledgeUnavailable("Student service credential is missing")
    try:
        body = EnqueuePublishedLessonKnowledgeAtStudentBody(
            course_id=course_id,
            lesson_id=lesson_id,
            video_revision=revision,
            classroom_id=classroom_id,
            scenes=[EnqueuePublishedLessonKnowledgeAtStudentBodyScenesItem.from_dict(scene)
                    for scene in scenes],
        )
        with AuthenticatedClient(
            base_url=settings.STUDENT_URL.rstrip("/"),
            token=settings.STUDENT_SERVICE_KEY,
            prefix="",
            auth_header_name="X-Student-Service-Key",
            timeout=httpx.Timeout(7.0, connect=2.0),
            follow_redirects=False,
            raise_on_unexpected_status=False,
            httpx_args={"trust_env": False},
        ) as client:
            response = sync_detailed(client=client, body=body)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise StudentKnowledgeUnavailable("Student knowledge request failed") from error
    if response.status_code != 200 or not isinstance(
        response.parsed, EnqueuePublishedLessonKnowledgeAtStudentResponse200
    ):
        raise StudentKnowledgeUnavailable("Student knowledge response was rejected")
    result = response.parsed
    if (result.course_id, result.lesson_id, result.video_revision) != (
        course_id, lesson_id, revision
    ):
        raise StudentKnowledgeUnavailable("Student knowledge identity did not match")
