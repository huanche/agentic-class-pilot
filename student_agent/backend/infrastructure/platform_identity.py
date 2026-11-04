"""Request-local identity accepted only over the authenticated platform channel."""
import hmac
import os
from contextvars import ContextVar
from dataclasses import dataclass

from backend.contracts import SessionError


@dataclass(frozen=True)
class PlatformIdentity:
    user_id: str
    course_id: str = ""


current_identity: ContextVar[PlatformIdentity | None] = ContextVar("platform_identity", default=None)


def local_demo(request) -> bool:
    """A separate loopback-only preview, never an authentication fallback."""
    return (os.environ.get("STUDENT_DEMO_MODE", "").lower() in {"1", "true"}
            and bool(os.environ.get("STUDENT_NEW_DEMO_PLAYER_URL"))
            and not os.environ.get("PLATFORM_AUTH_URL")
            and not os.environ.get("PLATFORM_TO_STUDENT_KEY")
            and request.url.hostname in {"localhost", "127.0.0.1", "::1"}
            and request.client is not None
            and request.client.host in {"localhost", "127.0.0.1", "::1", "testclient"})


def authenticate(headers) -> PlatformIdentity:
    expected = os.environ.get("PLATFORM_TO_STUDENT_KEY", "")
    if not expected:
        raise SessionError(503, "课堂内部连接尚未配置", code="UPSTREAM_UNAVAILABLE")
    if not hmac.compare_digest(headers.get("x-platform-learning-key", "").encode(), expected.encode()):
        raise SessionError(403, "无效的内部调用", code="ACCESS_DENIED")
    if headers.get("x-platform-protocol") != "platform-cookie-v1":
        raise SessionError(426, "内部协议版本不兼容", code="CLIENT_RELOAD_REQUIRED")
    user_id = headers.get("x-platform-user-id", "")
    course_id = headers.get("x-platform-course-id", "")
    if not user_id or len(user_id) > 128 or len(course_id) > 128:
        raise SessionError(403, "内部身份无效", code="ACCESS_DENIED")
    return PlatformIdentity(user_id, course_id)


def session_scope(sid: str, actor: PlatformIdentity) -> dict:
    from backend.infrastructure import commands, persistence
    from backend.session import service
    # Catalog sessions can be rebuilt after a restart; formal state is always read from storage.
    with service.session_lock:
        cached = service.sessions.get(sid)
    if cached and cached.get("phase") == "idle" and "stateVersion" not in cached:
        context = cached.get("context") or {}
        if str(context.get("userId")) != actor.user_id:
            raise SessionError(404, "学习记录不存在", code="LEARNING_RECORD_NOT_FOUND")
        return {"courseId": str(context["courseId"]), "lessonId": None}
    try:
        record = commands.scope(sid)
    except persistence.RecordConflict as error:
        raise SessionError(404, "学习记录不存在", code="LEARNING_RECORD_NOT_FOUND") from error
    except Exception as error:
        raise SessionError(503, "读取学习记录失败", code="STORAGE_UNAVAILABLE") from error
    if str(record["user_id"]) != actor.user_id:
        raise SessionError(404, "学习记录不存在", code="LEARNING_RECORD_NOT_FOUND")
    return {"courseId": str(record["course_id"]), "lessonId": record.get("lesson_id"),
            "classroomId": record.get("classroom_id")}


def check_scope(sid: str, actor: PlatformIdentity) -> dict:
    scope = session_scope(sid, actor)
    if actor.course_id != scope["courseId"]:
        raise SessionError(403, "学习记录与当前课程不匹配", code="ACCESS_DENIED")
    return scope
