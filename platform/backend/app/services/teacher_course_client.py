"""Platform adapter for generated teacher course provisioning."""

from __future__ import annotations

import uuid

import httpx

from app.core.config import settings
from app.generated.platform_teacher_api import AuthenticatedClient
from app.generated.platform_teacher_api.api.default.provision_teacher_course import (
    asyncio_detailed,
)
from app.generated.platform_teacher_api.models import (
    ProvisionTeacherCourseBody,
    ProvisionTeacherCourseResponse200,
    ProvisionTeacherCourseResponse201,
)


class TeacherCourseUnavailable(Exception):
    """The teacher service did not confirm the requested course."""


class TeacherCourseConflict(Exception):
    """The teacher service rejected this course's delegated owner."""


async def provision_teacher_course(
    external_id: str, owner_id: uuid.UUID, title: str, description: str | None
) -> str:
    if not settings.TEACHER_SERVICE_KEY:
        raise TeacherCourseUnavailable("Teacher service credential is missing")
    try:
        async with AuthenticatedClient(
            base_url=settings.TEACHER_URL.rstrip("/"),
            token=settings.TEACHER_SERVICE_KEY,
            prefix="",
            auth_header_name="X-Platform-Service-Key",
            headers={"X-Platform-Subject": str(owner_id)},
            timeout=httpx.Timeout(30.0, connect=3.0),
            follow_redirects=False,
            raise_on_unexpected_status=False,
            httpx_args={"trust_env": False},
        ) as client:
            response = await asyncio_detailed(
                client=client,
                body=ProvisionTeacherCourseBody(
                    id=external_id, title=title, description=description
                ),
            )
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise TeacherCourseUnavailable("Teacher course request failed") from error
    if response.status_code in (403, 409):
        raise TeacherCourseConflict("Teacher course owner conflicts with platform")
    if response.status_code not in (200, 201) or not isinstance(
        response.parsed,
        (ProvisionTeacherCourseResponse200, ProvisionTeacherCourseResponse201),
    ):
        raise TeacherCourseUnavailable("Teacher course response was rejected")
    result = response.parsed
    if result.success is not True or result.course.id != external_id:
        raise TeacherCourseUnavailable("Teacher course identity did not match request")
    return result.course.id
