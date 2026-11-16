from collections.abc import Generator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlalchemy import text
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from app.core import security
from app.core.config import settings
from app.core.db import engine
from app.core.structured_logging import user_id_var
from app.models import TokenPayload, User

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token", auto_error=False
)


def get_db() -> Generator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str | None, Depends(reusable_oauth2)]


def _resolve_current_user(session: Session, token: str | None, request: Request) -> User:
    if token is None:
        from app.services.browser_sessions import read_browser_user
        return read_browser_user(session, request)
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    if not token_data.sub or not token_data.sid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
        )
    active_session = session.execute(
        text(
            "SELECT 1 FROM browser_session "
            "WHERE token_hash=:session_id AND user_id=:user_id AND expires_at > now()"
        ),
        {"session_id": token_data.sid, "user_id": token_data.sub},
    ).first()
    if not active_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
        )
    user = session.get(User, token_data.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


async def get_current_user(session: SessionDep, token: TokenDep, request: Request) -> User:
    # async so the user_id contextvar is set in the event-loop context the
    # logging middleware reads; the blocking DB work stays in the threadpool
    user = await run_in_threadpool(_resolve_current_user, session, token, request)
    user_id_var.set(str(user.id))
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user


def get_current_teacher(current_user: CurrentUser) -> User:
    """Only teachers (or superusers) may create/manage teaching content."""
    if not current_user.is_superuser and current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="仅教师角色可以执行此操作")
    return current_user


TeacherUser = Annotated[User, Depends(get_current_teacher)]


def get_current_observer(current_user: CurrentUser) -> User:
    """Internal read-only observers of the dev console.

    ``role == "observer"`` is never selectable at registration; it is granted
    out-of-band (see ``scripts/create_observer.py``). Superusers pass too, so
    the console is one boundary for both.
    """
    if not current_user.is_superuser and current_user.role != "observer":
        raise HTTPException(status_code=403, detail="仅内部观察角色可以访问")
    return current_user


ObserverUser = Annotated[User, Depends(get_current_observer)]
