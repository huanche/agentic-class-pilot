import secrets
import string
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import EmailStr, field_validator
from sqlalchemy import DateTime
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


def new_enroll_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def normalize_title(value: str | None) -> str | None:
    """Strip titles and reject whitespace-only ones (None = field not updated)."""
    if value is not None:
        value = value.strip()
        if not value:
            raise ValueError("标题不能为空白")
    return value


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)
    # teacher | student — picked at registration
    role: str = Field(default="student", max_length=20)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    role: Literal["student", "teacher"] = "student"
    code: str = Field(min_length=6, max_length=6)


# Email verification codes for registration (single active code per email)
class EmailVerification(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(index=True, max_length=255)
    code_hash: str = Field(max_length=64)
    attempts: int = 0
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    expires_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class SendVerificationCode(SQLModel):
    email: EmailStr = Field(max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(SQLModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    is_superuser: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    items: list[Item] = Relationship(back_populates="owner", cascade_delete=True)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Shared properties
class ItemBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Properties to receive on item creation
class ItemCreate(ItemBase):
    pass


# Properties to receive on item update
class ItemUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Database model, database table inferred from class name
class Item(ItemBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="items")


# Properties to return via API, id is always required
class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int


# Shared properties
class CourseBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    check_title = field_validator("title")(normalize_title)


# Properties to receive on course creation
class CourseCreate(CourseBase):
    pass


# Properties to receive on course update, all are optional
class CourseUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    check_title = field_validator("title")(normalize_title)


# Database model
class Course(CourseBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    # 8-char code students use to enroll
    enroll_code: str | None = Field(
        default_factory=new_enroll_code, unique=True, index=True, max_length=8
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship()
    chapters: list[Chapter] = Relationship(back_populates="course", cascade_delete=True)


# Properties to return via API, id is always required
class CoursePublic(CourseBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    enroll_code: str | None = None
    created_at: datetime | None = None


class CoursesPublic(SQLModel):
    data: list[CoursePublic]
    count: int


# Enrollment: a student joins a course via its enroll code
class Enrollment(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    course_id: uuid.UUID = Field(
        foreign_key="course.id", nullable=False, ondelete="CASCADE"
    )
    student_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class EnrollByCode(SQLModel):
    code: str = Field(min_length=4, max_length=8)


# A course card in the student's "my courses" list, with progress
class EnrolledCoursePublic(CoursePublic):
    total_chapters: int = 0
    completed_chapters: int = 0


class EnrolledCoursesPublic(SQLModel):
    data: list[EnrolledCoursePublic]
    count: int


class CourseMemberPublic(SQLModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None = None
    enrolled_at: datetime | None = None
    completed_chapters: int = 0
    total_chapters: int = 0


class CourseMembersPublic(SQLModel):
    data: list[CourseMemberPublic]
    count: int


# Chapter-level learning progress (student marks a chapter as learned)
class ChapterProgress(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    chapter_id: uuid.UUID = Field(
        foreign_key="chapter.id", nullable=False, ondelete="CASCADE"
    )
    student_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    completed_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# ----- Unified agent sessions (docs/agent-isolation-plan.md §3, §12) -----


class AgentSession(SQLModel, table=True):
    """Identity/ownership row for every agent conversation.

    The LangGraph checkpointer stays the only message store; this row maps
    (owner, agent, business scope) onto the checkpoint ``thread_id`` partition
    key, and carries the run lease that serializes concurrent sends across
    worker processes (plan §7.2, decision 12.4). ``agent_key``/``scope_type``
    are registry-validated strings, not DB enums; ``scope_id`` is the
    canonical string form of the business object id (decision 12.1).
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # immutable storage address; legacy rows keep their old formats
    thread_id: str = Field(unique=True, index=True, max_length=100)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    agent_key: str = Field(max_length=50)
    scope_type: str = Field(max_length=50)
    scope_id: str = Field(max_length=64)
    title: str = Field(default="", max_length=255)
    status: str = Field(default="active", max_length=20)  # active | deleting
    state_version: int = Field(default=1)
    idempotency_key: str | None = Field(default=None, max_length=100)
    # run lease — NULL/absent means idle; see decision 12.4
    run_token: str | None = Field(default=None, max_length=64)
    run_expires_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)  # type: ignore
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class AgentSessionPublic(SQLModel):
    id: uuid.UUID
    agent_key: str
    scope_type: str
    scope_id: str
    title: str
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentSessionsPublic(SQLModel):
    data: list[AgentSessionPublic]
    count: int


# Shared properties
class ChapterBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    order_index: int = Field(default=0)
    check_title = field_validator("title")(normalize_title)


# Properties to receive on chapter creation
class ChapterCreate(ChapterBase):
    pass


# Properties to receive on chapter update, all are optional
class ChapterUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    order_index: int | None = None
    check_title = field_validator("title")(normalize_title)


# Database model
class Chapter(ChapterBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    course_id: uuid.UUID = Field(
        foreign_key="course.id", nullable=False, ondelete="CASCADE"
    )
    course: Course | None = Relationship(back_populates="chapters")


# Properties to return via API, id is always required
class ChapterPublic(ChapterBase):
    id: uuid.UUID
    course_id: uuid.UUID
    created_at: datetime | None = None
    # only populated for students: whether they marked this chapter as learned
    completed: bool | None = None


class ChaptersPublic(SQLModel):
    data: list[ChapterPublic]
    count: int


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
