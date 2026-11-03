"""Generated teacher-service clients for the authorization-boundary reads.

These replace the direct teacher-schema reads inside authorize: material
visibility, classroom visibility, and job→course resolution. Course
ownership is not here — the platform already owns it via ``course.owner_id``
recorded at registration time.
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.generated.platform_teacher_api import AuthenticatedClient
from app.generated.platform_teacher_api.api.default.get_teacher_classroom_visibility import (
    sync_detailed as classroom_visibility_detailed,
)
from app.generated.platform_teacher_api.api.default.get_teacher_job_course_ref import (
    sync_detailed as job_course_ref_detailed,
)
from app.generated.platform_teacher_api.api.default.get_teacher_material_visibility import (
    sync_detailed as material_visibility_detailed,
)
from app.generated.platform_teacher_api.models import (
    GetTeacherClassroomVisibilityResponse200,
    GetTeacherJobCourseRefResponse200,
    GetTeacherMaterialVisibilityResponse200,
    GetTeacherJobCourseRefKind,
)


class TeacherAuthzUnavailable(Exception):
    """The teacher service did not supply a trustworthy authorization verdict."""


def _client(owner_id):
    return AuthenticatedClient(
        base_url=settings.TEACHER_URL.rstrip("/"),
        token=settings.TEACHER_SERVICE_KEY,
        prefix="",
        auth_header_name="X-Platform-Service-Key",
        headers={"X-Platform-Subject": str(owner_id)},
        timeout=httpx.Timeout(5.0, connect=2.0),
        follow_redirects=False,
        raise_on_unexpected_status=False,
        httpx_args={"trust_env": False},
    )


def _guard(response, parsed_type):
    if response.status_code != 200 or not isinstance(response.parsed, parsed_type):
        raise TeacherAuthzUnavailable("Teacher authorization read was rejected")


def classroom_visibility(classroom_id: str, owner_id) -> tuple[str | None, bool]:
    """Return (teacher course reference, currently-published verdict)."""
    if not settings.TEACHER_SERVICE_KEY:
        raise TeacherAuthzUnavailable("Teacher service credential is missing")
    try:
        with _client(owner_id) as client:
            response = classroom_visibility_detailed(classroom_id, client=client)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise TeacherAuthzUnavailable("Teacher classroom visibility failed") from error
    _guard(response, GetTeacherClassroomVisibilityResponse200)
    return response.parsed.course_id, response.parsed.published


def material_visibility(course_ref: str, material_id: str, owner_id) -> bool:
    if not settings.TEACHER_SERVICE_KEY:
        raise TeacherAuthzUnavailable("Teacher service credential is missing")
    try:
        with _client(owner_id) as client:
            response = material_visibility_detailed(course_ref, material_id, client=client)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise TeacherAuthzUnavailable("Teacher material visibility failed") from error
    _guard(response, GetTeacherMaterialVisibilityResponse200)
    return response.parsed.visible


def job_course_ref(job_id: str, kind: str, owner_id) -> str:
    """Return the owning course reference, or raise NotFound-style ValueError."""
    if not settings.TEACHER_SERVICE_KEY:
        raise TeacherAuthzUnavailable("Teacher service credential is missing")
    try:
        with _client(owner_id) as client:
            response = job_course_ref_detailed(
                job_id, client=client, kind=GetTeacherJobCourseRefKind(kind))
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise TeacherAuthzUnavailable("Teacher job lookup failed") from error
    if response.status_code == 404:
        raise LookupError("Task not found")
    _guard(response, GetTeacherJobCourseRefResponse200)
    return response.parsed.course_id
