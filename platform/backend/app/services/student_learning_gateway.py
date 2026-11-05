"""Fixed-destination platform-to-student transport; never forwards browser credentials."""
import uuid

import httpx
from fastapi import HTTPException
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.models import User
from app.services.browser_learning_auth import BrowserStudent, reject
from app.services.course_access import get_student_course

_client: httpx.AsyncClient | None = None
# Keep redirects and proxy environment disabled for internal traffic.


async def close_client() -> None:
    global _client
    if _client:
        client, _client = _client, None
        await client.aclose()


async def student_request(method: str, path: str, identity: BrowserStudent,
                    course_id: str = "", body: dict | None = None,
                    *, command: bool = False, request_id: str = "") -> tuple[int, dict]:
    global _client
    if not settings.PLATFORM_TO_STUDENT_KEY:
        raise reject(503, "UPSTREAM_UNAVAILABLE", "课堂内部连接尚未配置")
    if _client is None:
        # No await until assignment: initialization is atomic within the server event loop.
        _client = httpx.AsyncClient(base_url=settings.STUDENT_URL.rstrip("/"), trust_env=False,
                                   follow_redirects=False, limits=httpx.Limits(max_connections=50))
    headers = {"X-Platform-Learning-Key": settings.PLATFORM_TO_STUDENT_KEY,
               "X-Platform-User-Id": str(identity.user_id),
               "X-Platform-Course-Id": course_id,
               "X-Platform-Protocol": "platform-cookie-v1", "X-Request-Id": request_id}
    try:
        response = await _client.request(method, path, json=body, headers=headers,
            timeout=httpx.Timeout(settings.STUDENT_COMMAND_TIMEOUT_SECONDS if command else 20.0,
                                  connect=3.0, pool=3.0))
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid upstream response")
        return response.status_code, data
    except httpx.TimeoutException as error:
        raise reject(504, "COMMAND_RESULT_UNKNOWN" if command else "UPSTREAM_UNAVAILABLE",
                     "请求超时，请查询原提交结果" if command else "课堂服务暂不可用") from error
    except (httpx.HTTPError, ValueError) as error:
        raise reject(503, "UPSTREAM_UNAVAILABLE", "课堂服务暂不可用，请稍后重试") from error


def course_access(identity: BrowserStudent, course_id: str) -> None:
    try:
        _course_access(identity, course_id)
    except HTTPException as error:
        if error.status_code == 403 and isinstance(error.detail, str):
            raise reject(403, "COURSE_ACCESS_DENIED", error.detail) from error
        raise
    except Exception as error:
        raise reject(503, "STORAGE_UNAVAILABLE", "课程权限暂不可用，请稍后重试") from error


def _course_access(identity: BrowserStudent, course_id: str) -> None:
    try:
        course_uuid = uuid.UUID(course_id)
    except ValueError as error:
        raise reject(422, "INVALID_PAYLOAD", "课程编号无效") from error
    with Session(engine) as db:
        user = db.get(User, identity.user_id)
        if not user or not user.is_active:
            raise reject(403, "ACCOUNT_DISABLED", "账号不可用")
        course = get_student_course(db, user, course_uuid)
        owner_id = course.owner_id
    from app.services.teacher_publication_client import (
        TeacherPublicationUnavailable,
        get_teacher_publication,
    )
    try:
        if get_teacher_publication(course_uuid, owner_id) is None:
            raise reject(403, "COURSE_ACCESS_DENIED", "课程暂未开放学习")
    except TeacherPublicationUnavailable as error:
        raise reject(503, "UPSTREAM_UNAVAILABLE", "课程发布状态暂不可用") from error
