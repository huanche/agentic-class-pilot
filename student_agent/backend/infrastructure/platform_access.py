"""Platform HTTP adapter: existing context and best-effort progress contracts."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from backend.contracts import SessionError
from backend.infrastructure import platform_client

logger = logging.getLogger(__name__)


def _post(path: str, payload: dict) -> dict:
    base = os.environ.get("PLATFORM_AUTH_URL", "").rstrip("/")
    key = os.environ.get("STUDENT_SERVICE_KEY", "")
    if not base or not key:
        raise SessionError(503, "请配置 PLATFORM_AUTH_URL 和 STUDENT_SERVICE_KEY")
    # The teacher service shares PLATFORM_AUTH_URL but treats it as the host
    # base; the local student launcher may already include /api/v1.
    if not base.endswith("/api/v1"):
        base += "/api/v1"
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Student-Service-Key": key},
        method="POST",
    )
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise SessionError(error.code, "平台课堂读取失败或启动令牌已过期") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise SessionError(503, "平台服务暂不可用") from error


def platform_context(token: str, lesson_id: str | None = None, refresh_session: bool = False) -> dict:
    return platform_client.learning_context(token, lesson_id, refresh_session)


def authorize_student(token: str) -> dict:
    """Verify current enrollment with the existing lightweight platform contract."""
    return _post("/internal/student/authorize", {"launch_token": token})


def report_learning_progress(session: dict, event: str) -> bool:
    """Sync persisted lesson progress to the teacher roster without blocking class."""
    context = session.get("context") or {}
    if not all((context.get("userId"), context.get("courseId"), session.get("classroomId"))):
        return False
    if not os.environ.get("PLATFORM_AUTH_URL") or not os.environ.get("STUDENT_SERVICE_KEY"):
        logger.warning("Learning progress sync skipped: platform connection is unconfigured")
        return False
    try:
        pushed = platform_client.report_learning_progress(
            str(context["userId"]), str(context["courseId"]),
            str(session["id"]), str(session["classroomId"]), event,
        )
        if not pushed:
            logger.warning("Learning progress saved but teacher sync failed: course=%s student=%s",
                           context["courseId"], context["userId"])
        return pushed
    except Exception:
        logger.exception("Learning progress sync failed: course=%s student=%s event=%s",
                         context["courseId"], context["userId"], event)
        return False
