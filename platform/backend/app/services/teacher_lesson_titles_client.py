"""Generated-client read of teacher-owned lesson titles."""
from __future__ import annotations

import uuid

import httpx

from app.core.config import settings
from app.generated.platform_teacher_api import AuthenticatedClient
from app.generated.platform_teacher_api.api.default.get_teacher_lesson_titles import (
    sync_detailed,
)
from app.generated.platform_teacher_api.models import GetTeacherLessonTitlesResponse200


class TeacherLessonTitlesUnavailable(Exception):
    pass


def get_lesson_titles(course_id: uuid.UUID, owner_id: uuid.UUID) -> dict[str, str]:
    if not settings.TEACHER_SERVICE_KEY:
        raise TeacherLessonTitlesUnavailable("Teacher service credential is missing")
    try:
        with AuthenticatedClient(
            base_url=settings.TEACHER_URL.rstrip("/"),
            token=settings.TEACHER_SERVICE_KEY, prefix="",
            auth_header_name="X-Platform-Service-Key",
            headers={"X-Platform-Subject": str(owner_id)},
            timeout=httpx.Timeout(5.0, connect=2.0),
            follow_redirects=False, raise_on_unexpected_status=False,
            httpx_args={"trust_env": False},
        ) as client:
            response = sync_detailed(str(course_id), client=client)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise TeacherLessonTitlesUnavailable("Teacher lesson titles request failed") from error
    if response.status_code != 200 or not isinstance(
        response.parsed, GetTeacherLessonTitlesResponse200,
    ):
        raise TeacherLessonTitlesUnavailable("Teacher lesson titles response was rejected")
    titles = response.parsed.to_dict().get("titles")
    if not isinstance(titles, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in titles.items()
    ):
        raise TeacherLessonTitlesUnavailable("Teacher lesson titles shape was rejected")
    return titles
