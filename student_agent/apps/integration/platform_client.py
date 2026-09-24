"""HTTP client for platform internal APIs (service-key authenticated).

- urllib based (no extra dependency, mirrors orchestrator's LLM client style)
- explicit timeouts, bounded retries on transient failures only
- maps platform status codes to typed errors
- never logs tokens, cookies, or service keys
"""
import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from .config import IntegrationConfigError, platform_auth_url, student_service_key

CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 15
RETRY_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 0.5


class PlatformClientError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _map_status(status: int, detail: str) -> PlatformClientError:
    meaning = {
        400: "请求无效",
        401: "启动令牌无效或已过期",
        403: "无权访问该课程（未选课或身份不符）",
        404: "课程或发布内容不存在",
        409: "课程状态冲突（如未发布）",
        503: "平台服务暂不可用",
    }.get(status, "平台请求失败")
    return PlatformClientError(status, f"{meaning}（HTTP {status}）{detail}".strip())


def _post_json(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    base = platform_auth_url().rstrip("/")
    url = f"{base}{path}"
    body = json.dumps(payload).encode("utf-8")
    last_error: Optional[PlatformClientError] = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        request = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "X-Student-Service-Key": student_service_key(),
        })
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=CONNECT_TIMEOUT_SECONDS + READ_TIMEOUT_SECONDS) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:200]
            try:
                detail = json.loads(detail).get("detail", detail)
            except json.JSONDecodeError:
                pass
            raise _map_status(error.code, str(detail)) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = PlatformClientError(0, f"平台连接失败：{error}")
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECONDS)
    raise last_error or PlatformClientError(0, "平台连接失败")


def fetch_learning_context(launch_token: str) -> Dict[str, Any]:
    """POST /internal/student/learning-context → raw platform payload."""
    if not platform_auth_url() or not student_service_key():
        raise IntegrationConfigError("平台客户端未配置（PLATFORM_AUTH_URL / STUDENT_SERVICE_KEY）")
    return _post_json("/internal/student/learning-context", {"launch_token": launch_token})
