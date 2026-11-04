"""Explicit Cookie BFF routes. Mounted at /api/session, outside /api/v1."""
import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.services import student_learning_gateway as gateway
from app.services.browser_learning_auth import BrowserStudent, browser_student, reject

router = APIRouter(prefix="/api/session", tags=["student-learning"])
Identity = Annotated[BrowserStudent, Depends(browser_student)]


def result(status: int, data: dict, request_id: str) -> JSONResponse:
    # Only expose the documented public error fields, never arbitrary service exceptions.
    if status >= 400 and "commandId" not in data:
        detail = data.get("detail", "课堂请求失败")
        if isinstance(detail, dict):
            data = {"detail": detail.get("detail", "课堂请求失败"), "code": detail.get("code")}
        elif isinstance(detail, str):
            data = {"detail": detail, "code": data.get("code")}
        else:
            data = {"detail": "请求参数无效", "code": "INVALID_PAYLOAD"}
    return JSONResponse(data | {"requestId": request_id}, status_code=status,
                        headers={"Cache-Control": "no-store", "X-Request-Id": request_id})


@router.get("/identity")
def identity(user: Identity):
    return result(200, {"userId": str(user.user_id), "expiresAt": user.expires_at.isoformat(),
        "csrfToken": user.csrf, "authProtocol": "platform-cookie-v1",
        "platformUrl": settings.FRONTEND_HOST.rstrip("/"), "demoEnabled": False}, uuid.uuid4().hex)


@router.get("/platform-entry")
def platform_entry():
    return result(200, {"platformUrl": settings.FRONTEND_HOST.rstrip("/"),
                        "demoEnabled": False, "authProtocol": "platform-cookie-v1"}, uuid.uuid4().hex)


async def forward(request: Request, user: BrowserStudent, sid: str | None = None):
    from starlette.concurrency import run_in_threadpool
    try:
        body = await request.json() if request.method == "POST" and await request.body() else {}
    except (ValueError, UnicodeError) as error:
        raise reject(422, "INVALID_PAYLOAD", "请求参数无效") from error
    if not isinstance(body, dict):
        raise reject(422, "INVALID_PAYLOAD", "请求参数无效")
    if "launch_token" in body:
        raise reject(426, "CLIENT_RELOAD_REQUIRED", "课堂已更新，请刷新页面")
    if any(key in body for key in ("userId", "user_id", "role", "isAdmin")):
        raise reject(422, "INVALID_PAYLOAD", "请求参数无效")
    request_id = uuid.uuid4().hex
    course_id = str(body.get("course_id") or "")
    if sid:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", sid):
            raise reject(404, "LEARNING_RECORD_NOT_FOUND", "学习记录不存在")
        status, scope = await gateway.student_request("GET",
            f"/api/internal/platform/sessions/{sid}/scope", user, request_id=request_id)
        if status != 200:
            return result(status, scope, request_id)
        course_id = str(scope.get("courseId") or "")
    await run_in_threadpool(gateway.course_access, user, course_id)
    status, data = await gateway.student_request(request.method,
        request.url.path, user, course_id, body if request.method == "POST" else None,
        command=request.url.path.endswith("/commands"), request_id=request_id)
    return result(status, data, request_id)


@router.post("/start", name="start")
@router.post("/resume", name="resume")
async def entry(request: Request, user: Identity):
    return await forward(request, user)


@router.post("/browser-restore")
async def retired_restore(_user: Identity):
    raise reject(410, "LEGACY_RESTORE_DISABLED", "请从课时列表恢复学习记录")


@router.get("/{sid}", name="read")
@router.get("/{sid}/feedback", name="feedback")
@router.post("/{sid}/commands", name="execute_command")
@router.post("/{sid}/learning-records", name="learning_records")
@router.post("/{sid}/playback", name="playback")
@router.post("/{sid}/prepare", name="retry_preparation")
async def session_request(sid: str, request: Request, user: Identity):
    # Identifiers are bounded to one path component by FastAPI's route matcher.
    return await forward(request, user, sid)


@router.post("/{sid}/begin/{lesson_id}")
async def begin(sid: str, lesson_id: str, request: Request, user: Identity):
    del lesson_id
    return await forward(request, user, sid)


@router.post("/{sid}/commands/{command_id}/status")
async def command_status(sid: str, command_id: str, request: Request, user: Identity):
    del command_id
    return await forward(request, user, sid)


@router.post("/{sid}/discussion", include_in_schema=False)
@router.post("/{sid}/message", include_in_schema=False)
@router.post("/{sid}/end", include_in_schema=False)
@router.post("/{sid}/reset", include_in_schema=False)
@router.post("/{sid}/postclass/start", include_in_schema=False)
@router.post("/{sid}/postclass/message", include_in_schema=False)
async def retired_command(sid: str, _user: Identity):
    del sid
    raise reject(410, "LEGACY_ENDPOINT_DISABLED", "课堂已更新，请刷新页面")
