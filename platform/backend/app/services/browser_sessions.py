"""Opaque, revocable browser sessions; credentials never enter frontend storage."""
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response
from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlmodel import Session

from app.core.config import settings
from app.models import User

COOKIE_NAME = "agentedu_session"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_browser_session(db: Session, user: User, response: Response) -> str:
    """Replace every existing session for this account with one new session.

    The user-row lock serializes simultaneous login attempts across application
    workers. The returned opaque session identifier is safe to bind into a
    signed JWT: it is a hash, never the cookie credential itself.
    """
    token = secrets.token_urlsafe(48)
    token_hash = digest(token)
    expires = datetime.now(UTC) + timedelta(hours=12)
    db.execute(text('SELECT id FROM "user" WHERE id=:user FOR UPDATE'), {"user": user.id})
    db.execute(text("DELETE FROM browser_session WHERE user_id=:user"), {"user": user.id})
    db.execute(
        text(
            "INSERT INTO browser_session (token_hash,user_id,expires_at) "
            "VALUES (:token,:user,:expires)"
        ),
        {"token": token_hash, "user": user.id, "expires": expires},
    )
    db.commit()
    response.set_cookie(COOKIE_NAME, token, max_age=43200, httponly=True,
                        secure=settings.PLATFORM_URL.startswith("https:"), samesite="lax", path="/")
    return token_hash


def user_for_cookie(db: Session, token: str | None) -> User:
    if not token:
        raise HTTPException(401, "请先登录平台")
    token_hash = digest(token)
    row = db.execute(text("SELECT user_id FROM browser_session WHERE token_hash=:token AND expires_at > now()"),
                     {"token": token_hash}).first()
    user = db.get(User, row[0]) if row else None
    if not user or not user.is_active:
        raise HTTPException(401, "登录已失效，请重新登录")
    # presence: stamp last-seen at most once a minute (dev console 在线统计用)
    updated = cast(CursorResult[Any], db.execute(
        text("UPDATE browser_session SET last_seen_at=now() "
             "WHERE token_hash=:token AND last_seen_at < now() - interval '60 seconds'"),
        {"token": token_hash}))
    if updated.rowcount:
        db.commit()
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
