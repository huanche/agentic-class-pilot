"""Generated-client reads of student-owned chat history."""
from __future__ import annotations

import uuid

import httpx

from app.core.config import settings
from app.generated.platform_student_api import AuthenticatedClient
from app.generated.platform_student_api.api.default.get_student_chat_sessions import (
    sync_detailed as sessions_request,
)
from app.generated.platform_student_api.api.default.get_student_chat_messages import (
    sync_detailed as messages_request,
)
from app.generated.platform_student_api.models import (
    GetStudentChatSessionsBody, GetStudentChatSessionsResponse200Item,
    GetStudentChatMessagesBody, GetStudentChatMessagesResponse200Item,
)


class StudentChatUnavailable(Exception):
    pass


class StudentChatMissing(Exception):
    pass


def _client() -> AuthenticatedClient:
    if not settings.STUDENT_SERVICE_KEY:
        raise StudentChatUnavailable("Student service credential is missing")
    return AuthenticatedClient(
        base_url=settings.STUDENT_URL.rstrip("/"),
        token=settings.STUDENT_SERVICE_KEY,
        prefix="", auth_header_name="X-Student-Service-Key",
        timeout=httpx.Timeout(8.0, connect=2.0), follow_redirects=False,
        raise_on_unexpected_status=False, httpx_args={"trust_env": False},
    )


def get_chat_sessions(course_id: uuid.UUID, user_ids: list[str], limit: int) -> list[dict]:
    try:
        with _client() as client:
            response = sessions_request(
                str(course_id), client=client,
                body=GetStudentChatSessionsBody(user_ids=user_ids, limit=limit),
            )
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise StudentChatUnavailable("Student chat sessions request failed") from error
    if response.status_code != 200 or not isinstance(response.parsed, list) or not all(
        isinstance(item, GetStudentChatSessionsResponse200Item) for item in response.parsed
    ):
        raise StudentChatUnavailable("Student chat sessions response was rejected")
    return [item.to_dict() for item in response.parsed]


def get_chat_messages(
    course_id: uuid.UUID, session_key: str, user_ids: list[str],
    phase: str | None, limit: int, offset: int,
) -> list[dict]:
    try:
        with _client() as client:
            response = messages_request(
                str(course_id), session_key, client=client,
                body=GetStudentChatMessagesBody(
                    user_ids=user_ids, phase=phase, limit=limit, offset=offset,
                ),
            )
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise StudentChatUnavailable("Student chat messages request failed") from error
    if response.status_code == 404:
        raise StudentChatMissing("Student chat session not found")
    if response.status_code != 200 or not isinstance(response.parsed, list) or not all(
        isinstance(item, GetStudentChatMessagesResponse200Item) for item in response.parsed
    ):
        raise StudentChatUnavailable("Student chat messages response was rejected")
    return [item.to_dict() for item in response.parsed]
