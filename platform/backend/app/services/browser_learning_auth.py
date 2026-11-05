"""Cookie-only classroom identity and session-bound CSRF checks."""
import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.models import User
from app.services.browser_sessions import COOKIE_NAME, check_origin, digest


def reject(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status, {"code": code, "detail": detail})


def csrf_value(cookie: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(),
                    ("learning-csrf:v1:" + digest(cookie)).encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class BrowserStudent:
    user_id: uuid.UUID
    is_admin: bool
    expires_at: datetime
    csrf: str


def browser_student(request: Request) -> BrowserStudent:
    return browser_identity(request, student_only=True)


def browser_identity(request: Request, *, student_only: bool = False) -> BrowserStudent:
    try:
        return _read_browser_identity(request, student_only=student_only)
    except HTTPException:
        raise
    except Exception as error:
        raise reject(503, "STORAGE_UNAVAILABLE", "登录服务暂不可用，请稍后重试") from error


def _read_browser_identity(request: Request, *, student_only: bool) -> BrowserStudent:
    """Close the DB transaction before any downstream service request."""
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        raise reject(401, "AUTH_REQUIRED", "请先登录平台")
    with Session(engine) as db:
        row = db.execute(text(
            "SELECT user_id,expires_at FROM browser_session "
            "WHERE token_hash=:token AND expires_at>now()"), {"token": digest(cookie)}).first()
        if not row:
            raise reject(401, "SESSION_EXPIRED", "登录已失效，请重新登录")
        user = db.get(User, row[0])
        if not user or not user.is_active:
            raise reject(403, "ACCOUNT_DISABLED", "账号不可用")
        if student_only and user.role != "student" and not user.is_superuser:
            raise reject(403, "COURSE_ACCESS_DENIED", "请使用学生账号进入课堂")
        identity = BrowserStudent(user.id, user.is_superuser, row[1], csrf_value(cookie))
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_browser_write(request, cookie)
    return identity


def check_browser_write(request: Request, cookie: str | None = None) -> None:
    try:
        check_origin(request)
    except HTTPException as error:
        raise reject(403, "ORIGIN_REJECTED", "请求来源不被允许") from error
    cookie = cookie or request.cookies.get(COOKIE_NAME)
    supplied = request.headers.get("x-csrf-token", "")
    if not cookie or not hmac.compare_digest(supplied.encode(), csrf_value(cookie).encode()):
        raise reject(403, "CSRF_REJECTED", "页面验证已失效，请刷新后重试")
