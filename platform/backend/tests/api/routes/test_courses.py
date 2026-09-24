"""Course/chapter update endpoints: renaming, permissions, and title validation."""

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import Chapter, Course, UserCreate
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _create_user(db: Session, *, role: str) -> tuple[str, str]:
    email = random_email()
    password = random_lower_string()
    crud.create_user(
        session=db, user_create=UserCreate(email=email, password=password, role=role)
    )
    return email, password


def _create_course(db: Session, *, owner_email: str) -> Course:
    owner = crud.get_user_by_email(session=db, email=owner_email)
    assert owner is not None
    course = Course(title="测试课程", owner_id=owner.id)
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


def _create_chapter(db: Session, *, course_id) -> Chapter:
    chapter = Chapter(title="章节", course_id=course_id)
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


def test_teacher_can_rename_own_course(client: TestClient, db: Session) -> None:
    t_email, t_password = _create_user(db, role="teacher")
    course = _create_course(db, owner_email=t_email)
    headers = user_authentication_headers(
        client=client, email=t_email, password=t_password
    )

    r = client.patch(
        f"{settings.API_V1_STR}/courses/{course.id}",
        headers=headers,
        json={"title": "新课程名", "description": "新简介"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "新课程名"
    assert data["description"] == "新简介"

    r = client.get(f"{settings.API_V1_STR}/courses/{course.id}", headers=headers)
    assert r.json()["title"] == "新课程名"


def test_teacher_can_rename_own_chapter(client: TestClient, db: Session) -> None:
    t_email, t_password = _create_user(db, role="teacher")
    course = _create_course(db, owner_email=t_email)
    chapter = _create_chapter(db, course_id=course.id)
    headers = user_authentication_headers(
        client=client, email=t_email, password=t_password
    )

    r = client.patch(
        f"{settings.API_V1_STR}/courses/chapters/{chapter.id}",
        headers=headers,
        json={"title": "新章节名", "description": "新说明"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "新章节名"
    assert data["description"] == "新说明"

    r = client.get(
        f"{settings.API_V1_STR}/courses/{course.id}/chapters", headers=headers
    )
    assert r.json()["data"][0]["title"] == "新章节名"


def test_update_title_strips_whitespace(client: TestClient, db: Session) -> None:
    t_email, t_password = _create_user(db, role="teacher")
    course = _create_course(db, owner_email=t_email)
    headers = user_authentication_headers(
        client=client, email=t_email, password=t_password
    )

    r = client.patch(
        f"{settings.API_V1_STR}/courses/{course.id}",
        headers=headers,
        json={"title": "  前后带空格  "},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "前后带空格"


def test_other_teacher_cannot_rename_course(client: TestClient, db: Session) -> None:
    owner_email, _ = _create_user(db, role="teacher")
    course = _create_course(db, owner_email=owner_email)

    other_email, other_password = _create_user(db, role="teacher")
    headers = user_authentication_headers(
        client=client, email=other_email, password=other_password
    )
    r = client.patch(
        f"{settings.API_V1_STR}/courses/{course.id}",
        headers=headers,
        json={"title": "别人的课"},
    )
    assert r.status_code == 403


def test_student_cannot_rename_course_or_chapter(
    client: TestClient, db: Session
) -> None:
    t_email, _ = _create_user(db, role="teacher")
    course = _create_course(db, owner_email=t_email)
    chapter = _create_chapter(db, course_id=course.id)

    s_email, s_password = _create_user(db, role="student")
    headers = user_authentication_headers(
        client=client, email=s_email, password=s_password
    )
    r = client.patch(
        f"{settings.API_V1_STR}/courses/{course.id}",
        headers=headers,
        json={"title": "学生的改名"},
    )
    assert r.status_code == 403

    r = client.patch(
        f"{settings.API_V1_STR}/courses/chapters/{chapter.id}",
        headers=headers,
        json={"title": "学生的改名"},
    )
    assert r.status_code == 403


def test_update_rejects_blank_title(client: TestClient, db: Session) -> None:
    t_email, t_password = _create_user(db, role="teacher")
    course = _create_course(db, owner_email=t_email)
    chapter = _create_chapter(db, course_id=course.id)
    headers = user_authentication_headers(
        client=client, email=t_email, password=t_password
    )

    r = client.patch(
        f"{settings.API_V1_STR}/courses/{course.id}",
        headers=headers,
        json={"title": "   "},
    )
    assert r.status_code == 422

    r = client.patch(
        f"{settings.API_V1_STR}/courses/chapters/{chapter.id}",
        headers=headers,
        json={"title": "   "},
    )
    assert r.status_code == 422


def test_update_ignores_explicit_null_title(client: TestClient, db: Session) -> None:
    """An explicit null must be a no-op, not a 500 from writing NULL."""
    t_email, t_password = _create_user(db, role="teacher")
    course = _create_course(db, owner_email=t_email)
    headers = user_authentication_headers(
        client=client, email=t_email, password=t_password
    )

    r = client.patch(
        f"{settings.API_V1_STR}/courses/{course.id}",
        headers=headers,
        json={"title": None},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "测试课程"
