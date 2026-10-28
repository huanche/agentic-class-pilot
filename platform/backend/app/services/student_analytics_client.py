"""Generated client adapter for student-owned learning data."""

from __future__ import annotations

import uuid

import httpx

from app.core.config import settings
from app.generated.platform_student_api import AuthenticatedClient
from app.generated.platform_student_api.api.default.get_student_course_learning_data import (
    sync_detailed as learning_data_request,
)
from app.generated.platform_student_api.api.default.get_student_course_progress import (
    sync_detailed as progress_request,
)
from app.generated.platform_student_api.models import (
    GetStudentCourseLearningDataBody,
    GetStudentCourseLearningDataResponse200,
    GetStudentCourseProgressResponse200,
)


class StudentAnalyticsUnavailable(Exception):
    """The student service did not supply trusted learning data."""


def _client() -> AuthenticatedClient:
    if not settings.STUDENT_SERVICE_KEY:
        raise StudentAnalyticsUnavailable("Student service credential is missing")
    return AuthenticatedClient(
        base_url=settings.STUDENT_URL.rstrip("/"),
        token=settings.STUDENT_SERVICE_KEY,
        prefix="",
        auth_header_name="X-Student-Service-Key",
        timeout=httpx.Timeout(5.0, connect=2.0),
        follow_redirects=False,
        raise_on_unexpected_status=False,
        httpx_args={"trust_env": False},
    )


def get_course_learning_data(
    course_id: uuid.UUID, user_ids: list[str],
) -> dict:
    try:
        with _client() as client:
            response = learning_data_request(
                str(course_id), client=client,
                body=GetStudentCourseLearningDataBody(user_ids=user_ids),
            )
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise StudentAnalyticsUnavailable("Student learning data request failed") from error
    if response.status_code != 200 or not isinstance(
        response.parsed, GetStudentCourseLearningDataResponse200
    ):
        raise StudentAnalyticsUnavailable("Student learning data response was rejected")
    result = response.parsed.to_dict()
    if (not isinstance(result.get("sessions"), list)
            or not isinstance(result.get("mastery"), list)
            or not isinstance(result.get("eventSummary"), dict)):
        raise StudentAnalyticsUnavailable("Student learning data shape was rejected")
    return result


def get_user_course_progress(course_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    try:
        with _client() as client:
            response = progress_request(str(course_id), str(user_id), client=client)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise StudentAnalyticsUnavailable("Student progress request failed") from error
    if response.status_code != 200 or not isinstance(
        response.parsed, GetStudentCourseProgressResponse200
    ):
        raise StudentAnalyticsUnavailable("Student progress response was rejected")
    result = response.parsed.to_dict()
    if any(type(result.get(key)) is not int or result[key] < 0 for key in (
        "learnedLessons", "sessionCount", "endedSessions", "stars",
    )):
        raise StudentAnalyticsUnavailable("Student progress metrics were rejected")
    return result
