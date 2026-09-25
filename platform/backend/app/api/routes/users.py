import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col, delete, func, select

from app import crud
from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)
from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.models import (
    EmailVerification,
    Item,
    Message,
    SendVerificationCode,
    UpdatePassword,
    User,
    UserCreate,
    UserPublic,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
    get_datetime_utc,
)
from app.services import agent_sessions
from app.utils import (
    generate_new_account_email,
    generate_verification_code_email,
    send_email,
)

router = APIRouter(prefix="/users", tags=["users"])

# Registration verification-code policy
VERIFICATION_CODE_TTL_MINUTES = 10
VERIFICATION_RESEND_COOLDOWN_SECONDS = 60
VERIFICATION_DAILY_SEND_LIMIT = 10
VERIFICATION_MAX_ATTEMPTS = 5


def _hash_code(email: str, code: str) -> str:
    # salt with the email so identical codes for different emails differ
    return hashlib.sha256(f"{email.lower()}:{code}".encode()).hexdigest()


@router.post("/send-verification-code", response_model=Message)
def send_verification_code(
    *, session: SessionDep, body: SendVerificationCode
) -> Any:
    """Send a 6-digit verification code for registration."""
    email = str(body.email).lower()

    if crud.get_user_by_email(session=session, email=email):
        raise HTTPException(status_code=400, detail="该邮箱已被注册")

    now = get_datetime_utc()
    existing = session.exec(
        select(EmailVerification)
        .where(EmailVerification.email == email)
        .order_by(EmailVerification.created_at.desc())  # type: ignore
    ).all()

    # daily send limit
    day_ago = now - timedelta(days=1)
    sent_today = sum(1 for r in existing if r.created_at and r.created_at > day_ago)
    if sent_today >= VERIFICATION_DAILY_SEND_LIMIT:
        raise HTTPException(
            status_code=429, detail="今天发送验证码次数已达上限，请明天再试"
        )

    # resend cooldown
    if existing:
        latest = existing[0]
        if latest.created_at and (now - latest.created_at).total_seconds() < (
            VERIFICATION_RESEND_COOLDOWN_SECONDS
        ):
            raise HTTPException(
                status_code=429, detail="发送过于频繁，请 60 秒后再试"
            )

    # only one active code per email: drop old records
    for record in existing:
        session.delete(record)

    code = f"{secrets.randbelow(1000000):06d}"
    record = EmailVerification(
        email=email,
        code_hash=_hash_code(email, code),
        expires_at=now + timedelta(minutes=VERIFICATION_CODE_TTL_MINUTES),
    )
    session.add(record)
    session.commit()

    email_data = generate_verification_code_email(
        email_to=email, code=code, valid_minutes=VERIFICATION_CODE_TTL_MINUTES
    )
    send_email(
        email_to=email,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )
    return Message(message="验证码已发送，请查收邮件")


def _verify_registration_code(session: SessionDep, email: str, code: str) -> None:
    """Validate the latest verification code for the email; raise on failure."""
    record = session.exec(
        select(EmailVerification)
        .where(EmailVerification.email == email.lower())
        .order_by(EmailVerification.created_at.desc())  # type: ignore
    ).first()
    if not record or not record.expires_at or record.expires_at < get_datetime_utc():
        raise HTTPException(
            status_code=400, detail="验证码不存在或已过期，请重新获取"
        )
    if record.attempts >= VERIFICATION_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=400, detail="验证码错误次数过多，请重新获取"
        )
    if record.code_hash != _hash_code(email, code):
        record.attempts += 1
        session.add(record)
        session.commit()
        raise HTTPException(status_code=400, detail="验证码错误")
    # success: consume the code
    session.delete(record)


@router.get(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UsersPublic,
)
def read_users(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
    """
    Retrieve users.
    """

    count_statement = select(func.count()).select_from(User)
    count = session.exec(count_statement).one()

    statement = (
        select(User).order_by(col(User.created_at).desc()).offset(skip).limit(limit)
    )
    users = session.exec(statement).all()

    users_public = [UserPublic.model_validate(user) for user in users]
    return UsersPublic(data=users_public, count=count)


@router.post(
    "/", dependencies=[Depends(get_current_active_superuser)], response_model=UserPublic
)
def create_user(*, session: SessionDep, user_in: UserCreate) -> Any:
    """
    Create new user.
    """
    user = crud.get_user_by_email(session=session, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="该邮箱已被注册",
        )

    user = crud.create_user(session=session, user_create=user_in)
    if settings.emails_enabled and user_in.email:
        email_data = generate_new_account_email(
            email_to=user_in.email, username=user_in.email, password=user_in.password
        )
        send_email(
            email_to=user_in.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    return user


@router.patch("/me", response_model=UserPublic)
def update_user_me(
    *, session: SessionDep, user_in: UserUpdateMe, current_user: CurrentUser
) -> Any:
    """
    Update own user.
    """

    if user_in.email:
        existing_user = crud.get_user_by_email(session=session, email=user_in.email)
        if existing_user and existing_user.id != current_user.id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )
    user_data = user_in.model_dump(exclude_unset=True)
    current_user.sqlmodel_update(user_data)
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user


@router.patch("/me/password", response_model=Message)
def update_password_me(
    *, session: SessionDep, body: UpdatePassword, current_user: CurrentUser
) -> Any:
    """
    Update own password.
    """
    verified, _ = verify_password(body.current_password, current_user.hashed_password)
    if not verified:
        raise HTTPException(status_code=400, detail="Incorrect password")
    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=400, detail="New password cannot be the same as the current one"
        )
    hashed_password = get_password_hash(body.new_password)
    current_user.hashed_password = hashed_password
    session.add(current_user)
    session.commit()
    return Message(message="Password updated successfully")


@router.get("/me", response_model=UserPublic)
def read_user_me(current_user: CurrentUser) -> Any:
    """
    Get current user.
    """
    return current_user


@router.delete("/me", response_model=Message)
async def delete_user_me(session: SessionDep, current_user: CurrentUser) -> Any:
    """
    Delete own user.
    """
    if current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        )
    # purge the user's agent sessions (checkpoints included) before the FK
    # cascade drops the identity rows — plan §12.11
    await agent_sessions.purge_user_sessions(session, current_user.id)
    session.delete(current_user)
    session.commit()
    return Message(message="User deleted successfully")


@router.post("/signup", response_model=UserPublic)
def register_user(session: SessionDep, user_in: UserRegister) -> Any:
    """
    Create new user without the need to be logged in.
    Requires a valid email verification code (see /send-verification-code).
    """
    user = crud.get_user_by_email(session=session, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="该邮箱已被注册",
        )
    _verify_registration_code(session, str(user_in.email), user_in.code)
    # The verified signup form lets the user choose a student or teacher account.
    # UserRegister restricts the value to those two roles.
    user_create = UserCreate.model_validate(user_in, update={"role": user_in.role})
    user = crud.create_user(session=session, user_create=user_create)
    return user


@router.get("/{user_id}", response_model=UserPublic)
def read_user_by_id(
    user_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    """
    Get a specific user by id.
    """
    user = session.get(User, user_id)
    if user == current_user:
        return user
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="The user doesn't have enough privileges",
        )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch(
    "/{user_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UserPublic,
)
def update_user(
    *,
    session: SessionDep,
    user_id: uuid.UUID,
    user_in: UserUpdate,
) -> Any:
    """
    Update a user.
    """

    db_user = session.get(User, user_id)
    if not db_user:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        )
    if user_in.email:
        existing_user = crud.get_user_by_email(session=session, email=user_in.email)
        if existing_user and existing_user.id != user_id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )

    db_user = crud.update_user(session=session, db_user=db_user, user_in=user_in)
    return db_user


@router.delete("/{user_id}", dependencies=[Depends(get_current_active_superuser)])
async def delete_user(
    session: SessionDep, current_user: CurrentUser, user_id: uuid.UUID
) -> Message:
    """
    Delete a user.
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user == current_user:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        )
    # purge agent sessions (checkpoints included) before the FK cascade drops
    # the identity rows — same path as /me (review finding #6)
    await agent_sessions.purge_user_sessions(session, user_id)
    statement = delete(Item).where(col(Item.owner_id) == user_id)
    session.exec(statement)
    session.delete(user)
    session.commit()
    return Message(message="User deleted successfully")
