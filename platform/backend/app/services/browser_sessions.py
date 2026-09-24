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


def check_origin(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    # Cookie-authenticated writes originate from the single public frontend.
    if origin != settings.FRONTEND_HOST:
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
