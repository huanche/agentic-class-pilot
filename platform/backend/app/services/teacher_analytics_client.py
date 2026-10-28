"""Generated client adapter for teacher-owned publication counts."""

from __future__ import annotations

import uuid

import httpx

from app.core.config import settings
from app.generated.platform_teacher_api import AuthenticatedClient
from app.generated.platform_teacher_api.api.default.get_teacher_publication_counts import (
    sync_detailed,
)
from app.generated.platform_teacher_api.models import (
    GetTeacherPublicationCountsResponse200,
)


class TeacherAnalyticsUnavailable(Exception):
    """Teacher service could not supply trusted counts."""


def get_teacher_publication_counts(
    course_id: uuid.UUID, owner_id: uuid.UUID,
) -> dict[str, int]:
    if not settings.TEACHER_SERVICE_KEY:
        raise TeacherAnalyticsUnavailable("Teacher service credential is missing")
    try:
        with AuthenticatedClient(
            base_url=settings.TEACHER_URL.rstrip("/"),
            token=settings.TEACHER_SERVICE_KEY,
            prefix="",
            auth_header_name="X-Platform-Service-Key",
            headers={"X-Platform-Subject": str(owner_id)},
            timeout=httpx.Timeout(5.0, connect=2.0),
            follow_redirects=False,
            raise_on_unexpected_status=False,
            httpx_args={"trust_env": False},
        ) as client:
            response = sync_detailed(str(course_id), client=client)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise TeacherAnalyticsUnavailable("Teacher publication count request failed") from error
    if response.status_code != 200 or not isinstance(
        response.parsed, GetTeacherPublicationCountsResponse200
    ):
        raise TeacherAnalyticsUnavailable("Teacher publication count response was rejected")
    result = response.parsed
    if (type(result.distinct_classrooms) is not int or result.distinct_classrooms < 0
            or type(result.published_artifacts_with_classroom) is not int
            or result.published_artifacts_with_classroom < 0):
        raise TeacherAnalyticsUnavailable("Teacher publication counts were invalid")
    return {"distinctClassrooms": result.distinct_classrooms,
            "publishedArtifactsWithClassroom": result.published_artifacts_with_classroom}
