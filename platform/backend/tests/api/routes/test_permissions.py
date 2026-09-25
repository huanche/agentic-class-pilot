"""Permission boundaries: students must not create/manage teaching content."""

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import Course, UserCreate
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


def test_student_cannot_create_course(client: TestClient, db: Session) -> None:
    email, password = _create_user(db, role="student")
    headers = user_authentication_headers(client=client, email=email, password=password)
    r = client.post(
        f"{settings.API_V1_STR}/courses/",
        headers=headers,
        json={"title": "学生的课"},
    )
    assert r.status_code == 403
    assert "教师" in r.json()["detail"]


def test_teacher_can_create_course(client: TestClient, db: Session) -> None:
    email, password = _create_user(db, role="teacher")
    headers = user_authentication_headers(client=client, email=email, password=password)
    r = client.post(
        f"{settings.API_V1_STR}/courses/",
        headers=headers,
        json={"title": "教师的课"},
    )
    assert r.status_code == 200
    assert r.json()["enroll_code"]


def test_signup_rejects_invalid_role(client: TestClient) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={
            "email": random_email(),
            "password": random_lower_string(),
            "role": "admin",
        },
    )
    assert r.status_code == 422


def test_signup_accepts_student_role(client: TestClient, db: Session) -> None:
    from tests.utils.verification import insert_verification_code

    email = random_email()
    insert_verification_code(db, email, "123456")
    r = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={
            "email": email,
            "password": random_lower_string(),
            "role": "student",
            "code": "123456",
        },
    )
    assert r.status_code == 200
    assert r.json()["role"] == "student"


def test_signup_accepts_teacher_role(client: TestClient, db: Session) -> None:
    from tests.utils.verification import insert_verification_code

    email = random_email()
    insert_verification_code(db, email, "123456")
    r = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={
            "email": email,
            "password": random_lower_string(),
            "role": "teacher",
            "code": "123456",
        },
    )
    assert r.status_code == 200
    assert r.json()["role"] == "teacher"


def test_student_cannot_read_unenrolled_course(
    client: TestClient, db: Session
) -> None:
    t_email, _ = _create_user(db, role="teacher")
    course = _create_course(db, owner_email=t_email)

    s_email, s_password = _create_user(db, role="student")
    s_headers = user_authentication_headers(
        client=client, email=s_email, password=s_password
    )
    r = client.get(f"{settings.API_V1_STR}/courses/{course.id}", headers=s_headers)
    assert r.status_code == 403
    r = client.get(
        f"{settings.API_V1_STR}/courses/{course.id}/chapters", headers=s_headers
    )
    assert r.status_code == 403


def test_join_with_invalid_code(client: TestClient, db: Session) -> None:
    s_email, s_password = _create_user(db, role="student")
    s_headers = user_authentication_headers(
        client=client, email=s_email, password=s_password
    )
    r = client.post(
        f"{settings.API_V1_STR}/enrollments/join",
        headers=s_headers,
        json={"code": "NOPE123"},
    )
    assert r.status_code == 404
