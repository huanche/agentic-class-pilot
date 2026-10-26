"""Platform adapter for the generated teacher publication API client."""

from __future__ import annotations

import uuid

import httpx

from app.core.config import settings
from app.generated.platform_teacher_api import AuthenticatedClient
from app.generated.platform_teacher_api.api.default.get_teacher_publication_verdict import (
    sync_detailed,
)
from app.generated.platform_teacher_api.models import (
    GetTeacherPublicationVerdictResponse200,
)


class TeacherPublicationUnavailable(Exception):
    """The teacher service could not provide a trustworthy current verdict."""


def get_teacher_publication(
    course_id: uuid.UUID, owner_id: uuid.UUID
) -> dict[str, str | int] | None:
    """Return the current published version, or None when explicitly unpublished."""
    if not settings.TEACHER_SERVICE_KEY:
        raise TeacherPublicationUnavailable("Teacher service credential is missing")
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
        raise TeacherPublicationUnavailable("Teacher publication request failed") from error
    if response.status_code != 200 or not isinstance(
        response.parsed, GetTeacherPublicationVerdictResponse200
    ):
        raise TeacherPublicationUnavailable("Teacher publication response was rejected")
    verdict = response.parsed
    if verdict.published is False and verdict.publication is None:
        return None
    if verdict.published is not True or verdict.publication is None:
        raise TeacherPublicationUnavailable("Teacher publication response is inconsistent")
    publication = verdict.publication
    if not hasattr(publication, "publication_id") or not hasattr(publication, "version"):
        raise TeacherPublicationUnavailable("Teacher publication response is malformed")
    if not isinstance(publication.publication_id, str) or not publication.publication_id:
        raise TeacherPublicationUnavailable("Teacher publication ID is invalid")
    if type(publication.version) is not int or publication.version < 1:
        raise TeacherPublicationUnavailable("Teacher publication version is invalid")
    return {"publicationId": publication.publication_id, "version": publication.version}
