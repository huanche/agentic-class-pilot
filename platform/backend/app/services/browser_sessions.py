"""Opaque, revocable browser sessions; credentials never enter frontend storage."""
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.models import User

COOKIE_NAME = "agentedu_session"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_browser_session(db: Session, user: User, response: Response) -> None:
    token = secrets.token_urlsafe(48)
    expires = datetime.now(UTC) + timedelta(hours=12)
    db.execute(text("INSERT INTO browser_session (token_hash,user_id,expires_at) VALUES (:token,:user,:expires)"),
               {"token": digest(token), "user": user.id, "expires": expires})
    db.commit()
    response.set_cookie(COOKIE_NAME, token, max_age=43200, httponly=True,
                        secure=settings.PLATFORM_URL.startswith("https:"), samesite="lax", path="/")


def user_for_cookie(db: Session, token: str | None) -> User:
    if not token:
        raise HTTPException(401, "请先登录平台")
    row = db.execute(text("SELECT user_id FROM browser_session WHERE token_hash=:token AND expires_at > now()"),
                     {"token": digest(token)}).first()
    user = db.get(User, row[0]) if row else None
    if not user or not user.is_active:
        raise HTTPException(401, "登录已失效，请重新登录")
    return user


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _loopback_equivalent(origin: str, frontend: str) -> bool:
    """本机开发：localhost / 127.0.0.1 / [::1] 视为同一来源（协议与端口须一致）。

    地址栏用 127.0.0.1 而配置是 localhost（或反之）是最常见的本地 403 坑；
    生产环境的正式域名不会落进回环集合，行为不变。"""
    try:
        o, f = urlsplit(origin), urlsplit(frontend)
    except ValueError:
        return False
    if o.scheme != f.scheme or o.port != f.port:
        return False
    return (o.hostname or "").lower() in _LOOPBACK_HOSTS and \
        (f.hostname or "").lower() in _LOOPBACK_HOSTS


def check_origin(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    allowed_origins = {settings.FRONTEND_HOST} | {
        value.strip() for value in settings.BROWSER_ALLOWED_ORIGINS.split(",") if value.strip()
    }
    if origin not in allowed_origins and \
            not any(_loopback_equivalent(origin or "", allowed) for allowed in allowed_origins):
        raise HTTPException(403, "请求来源不被允许")


def read_browser_user(db: Session, request: Request) -> User:
    check_origin(request)
    return user_for_cookie(db, request.cookies.get(COOKIE_NAME))


def revoke_browser_session(db: Session, request: Request, response: Response) -> None:
    check_origin(request)
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db.execute(text("DELETE FROM browser_session WHERE token_hash=:token"), {"token": digest(token)})
        db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
