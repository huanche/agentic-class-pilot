"""Student adapter for the generated platform learning-context client."""

from __future__ import annotations

import json
import os
import uuid

import httpx
from fastapi import HTTPException

from generated.student_platform_api import AuthenticatedClient
from generated.student_platform_api.api.default.get_student_learning_context import (
    sync_detailed,
)
from generated.student_platform_api.models import GetStudentLearningContextBody
from generated.student_platform_api.api.default.report_student_learning_progress import (
    sync_detailed as report_progress_detailed,
)
from generated.student_platform_api.models import (
    ReportStudentLearningProgressBody,
    ReportStudentLearningProgressBodyEvent,
    ReportStudentLearningProgressResponse200,
)


def learning_context(
    token: str, lesson_id: str | None = None, refresh_session: bool = False
) -> dict:
    base = os.environ.get("PLATFORM_AUTH_URL", "").rstrip("/")
    key = os.environ.get("STUDENT_SERVICE_KEY", "")
    if not base or not key:
        raise HTTPException(503, "请配置 PLATFORM_AUTH_URL 和 STUDENT_SERVICE_KEY")
    if not base.endswith("/api/v1"):
        base += "/api/v1"
    try:
        with AuthenticatedClient(
            base_url=base,
            token=key,
            prefix="",
            auth_header_name="X-Student-Service-Key",
            timeout=httpx.Timeout(20.0),
            follow_redirects=False,
            raise_on_unexpected_status=False,
            httpx_args={"trust_env": False},
        ) as client:
            response = sync_detailed(
                client=client,
                body=GetStudentLearningContextBody(
                    launch_token=token,
                    lesson_id=lesson_id,
                    refresh_session=refresh_session,
                ),
            )
    except (httpx.HTTPError, TimeoutError) as error:
        raise HTTPException(503, "平台服务暂不可用") from error
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise HTTPException(503, "平台课堂响应无效") from error
    if response.status_code != 200:
        raise HTTPException(int(response.status_code), "平台课堂读取失败或启动令牌已过期")
    if response.parsed is None:
        raise HTTPException(503, "平台课堂响应无效")
    try:
        # Preserve the exact wire shape, including future optional fields.
        result = json.loads(response.content)
    except (ValueError, TypeError) as error:
        raise HTTPException(503, "平台课堂响应无效") from error
    if not isinstance(result, dict):
        raise HTTPException(503, "平台课堂响应无效")
    return result


def report_learning_progress(
    user_id: str, course_id: str, session_key: str,
    classroom_id: str, event: str,
) -> bool:
    """Send one progress event through the platform contract; never retry here."""
    base = os.environ.get("PLATFORM_AUTH_URL", "").rstrip("/")
    key = os.environ.get("STUDENT_SERVICE_KEY", "")
    if not base or not key:
        raise HTTPException(503, "请配置 PLATFORM_AUTH_URL 和 STUDENT_SERVICE_KEY")
    if not base.endswith("/api/v1"):
        base += "/api/v1"
    with AuthenticatedClient(
        base_url=base,
        token=key,
        prefix="",
        auth_header_name="X-Student-Service-Key",
        timeout=httpx.Timeout(8.0),
        follow_redirects=False,
        raise_on_unexpected_status=False,
        httpx_args={"trust_env": False},
    ) as client:
        response = report_progress_detailed(
            client=client,
            body=ReportStudentLearningProgressBody(
                user_id=uuid.UUID(str(user_id)),
                course_id=uuid.UUID(str(course_id)),
                session_key=session_key,
                classroom_id=classroom_id,
                event=ReportStudentLearningProgressBodyEvent(event),
            ),
        )
    if response.status_code != 200:
        raise HTTPException(int(response.status_code), "平台学习进度上报失败")
    if not isinstance(response.parsed, ReportStudentLearningProgressResponse200):
        raise HTTPException(503, "平台学习进度响应无效")
    return response.parsed.pushed_to_teacher
