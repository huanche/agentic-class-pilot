"""Generated teacher-service client for the published learning content snapshot.

One call replaces the platform's cross-schema reads of the teacher package,
entries, published lessons and classroom projections that feed the student
learning context. Failures keep the legacy semantics: a missing classroom
snapshot is the same 404 the legacy SQL raised; everything else fails closed.
"""

from __future__ import annotations

import uuid

import httpx

from app.core.config import settings
from app.generated.platform_teacher_api import AuthenticatedClient
from app.generated.platform_teacher_api.api.default.get_teacher_classroom_content import (
    sync_detailed as classroom_content_detailed,
)
from app.generated.platform_teacher_api.api.default.get_teacher_published_content import (
    sync_detailed,
)
from app.generated.platform_teacher_api.api.default.get_teacher_published_lesson import (
    sync_detailed as published_lesson_detailed,
)
from app.generated.platform_teacher_api.models import (
    GetTeacherClassroomContentResponse200,
    GetTeacherPublishedContentResponse200,
    GetTeacherPublishedLessonResponse200,
    PublishedClassroomView,
    PublishedLearningContent,
)


class TeacherLearningContentUnavailable(Exception):
    """The teacher service did not supply a trustworthy content snapshot."""


class TeacherLearningContentMissing(Exception):
    """A published lesson references a classroom snapshot that no longer exists."""


def get_teacher_published_content(
    course_id: uuid.UUID, owner_id: uuid.UUID,
) -> PublishedLearningContent | None:
    """Return the teacher-owned snapshot, or None when nothing is published."""
    if not settings.TEACHER_SERVICE_KEY:
        raise TeacherLearningContentUnavailable("Teacher service credential is missing")
    try:
        with AuthenticatedClient(
            base_url=settings.TEACHER_URL.rstrip("/"),
            token=settings.TEACHER_SERVICE_KEY,
            prefix="",
            auth_header_name="X-Platform-Service-Key",
            headers={"X-Platform-Subject": str(owner_id)},
            # The snapshot carries every published classroom's projected scenes,
            # so it is far larger than the other bridge calls.
            timeout=httpx.Timeout(15.0, connect=2.0),
            follow_redirects=False,
            raise_on_unexpected_status=False,
            httpx_args={"trust_env": False},
        ) as client:
            response = sync_detailed(str(course_id), client=client)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise TeacherLearningContentUnavailable("Teacher content request failed") from error
    if response.status_code == 404:
        raise TeacherLearningContentMissing("Published lesson snapshot is missing")
    if response.status_code != 200 or not isinstance(
        response.parsed, GetTeacherPublishedContentResponse200
    ):
        raise TeacherLearningContentUnavailable("Teacher content response was rejected")
    if not response.parsed.published or response.parsed.content is None:
        return None
    return response.parsed.content


def get_teacher_classroom_view(classroom_id: str) -> PublishedClassroomView | None:
    """Projected scenes for one classroom; None when the snapshot is missing."""
    if not settings.TEACHER_SERVICE_KEY:
        raise TeacherLearningContentUnavailable("Teacher service credential is missing")
    try:
        with AuthenticatedClient(
            base_url=settings.TEACHER_URL.rstrip("/"),
            token=settings.TEACHER_SERVICE_KEY,
            prefix="",
            auth_header_name="X-Platform-Service-Key",
            headers={"X-Platform-Subject": ""},
            timeout=httpx.Timeout(10.0, connect=2.0),
            follow_redirects=False,
            raise_on_unexpected_status=False,
            httpx_args={"trust_env": False},
        ) as client:
            response = classroom_content_detailed(classroom_id, client=client)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise TeacherLearningContentUnavailable("Teacher classroom request failed") from error
    if response.status_code != 200 or not isinstance(
        response.parsed, GetTeacherClassroomContentResponse200
    ):
        raise TeacherLearningContentUnavailable("Teacher classroom response was rejected")
    return response.parsed.classroom


def get_teacher_published_lesson(
    artifact_id: str, owner_id: uuid.UUID,
) -> tuple[dict | None, str | None]:
    """Return (lesson dict, reason) for a teacher-verified published lesson video.

    lesson is None when the artifact is not a currently published lesson video;
    reason then mirrors the legacy failure: not-published, not-a-lesson-video
    or classroom-missing.
    """
    if not settings.TEACHER_SERVICE_KEY:
        raise TeacherLearningContentUnavailable("Teacher service credential is missing")
    try:
        with AuthenticatedClient(
            base_url=settings.TEACHER_URL.rstrip("/"),
            token=settings.TEACHER_SERVICE_KEY,
            prefix="",
            auth_header_name="X-Platform-Service-Key",
            headers={"X-Platform-Subject": str(owner_id)},
            timeout=httpx.Timeout(10.0, connect=2.0),
            follow_redirects=False,
            raise_on_unexpected_status=False,
            httpx_args={"trust_env": False},
        ) as client:
            response = published_lesson_detailed(artifact_id, client=client)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise TeacherLearningContentUnavailable("Teacher lesson request failed") from error
    if response.status_code != 200 or not isinstance(
        response.parsed, GetTeacherPublishedLessonResponse200
    ):
        raise TeacherLearningContentUnavailable("Teacher lesson response was rejected")
    if not response.parsed.published or response.parsed.lesson is None:
        return None, str(response.parsed.reason) if response.parsed.reason else "not-published"
    lesson = response.parsed.lesson
    return {
        "courseId": lesson.course_id,
        "lessonId": lesson.lesson_id,
        "classroomId": lesson.classroom_id,
        "publishedAt": lesson.published_at if lesson.published_at is not None else None,
        "classroom": lesson.classroom,
    }, None
