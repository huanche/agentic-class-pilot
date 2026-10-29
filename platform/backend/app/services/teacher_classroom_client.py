"""Generated teacher-service client for the current published classroom ID."""

from __future__ import annotations

import uuid

import httpx

from app.core.config import settings
from app.generated.platform_teacher_api import AuthenticatedClient
from app.generated.platform_teacher_api.api.default.get_teacher_latest_classroom import (
    sync_detailed,
)
from app.generated.platform_teacher_api.models import (
    GetTeacherLatestClassroomResponse200,
)


class TeacherClassroomUnavailable(Exception):
    """The teacher service did not supply a trustworthy classroom verdict."""


def get_latest_classroom(course_id: uuid.UUID, owner_id: uuid.UUID) -> str | None:
    if not settings.TEACHER_SERVICE_KEY:
        raise TeacherClassroomUnavailable("Teacher service credential is missing")
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
        raise TeacherClassroomUnavailable("Teacher classroom request failed") from error
    if response.status_code != 200 or not isinstance(
        response.parsed, GetTeacherLatestClassroomResponse200
    ):
        raise TeacherClassroomUnavailable("Teacher classroom response was rejected")
    classroom_id = response.parsed.classroom_id
    if classroom_id is not None and (not isinstance(classroom_id, str) or not classroom_id):
        raise TeacherClassroomUnavailable("Teacher classroom ID was invalid")
    return classroom_id
