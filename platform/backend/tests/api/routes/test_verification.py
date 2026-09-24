"""Email verification code: sending rules and signup validation."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import EmailVerification, User
from tests.utils.utils import random_email, random_lower_string
from tests.utils.verification import insert_verification_code

CODE_URL = f"{settings.API_V1_STR}/users/send-verification-code"
SIGNUP_URL = f"{settings.API_V1_STR}/users/signup"


def test_send_code_success(client: TestClient, db: Session) -> None:
    email = random_email()
    with patch("app.api.routes.users.send_email") as mock_send:
        r = client.post(CODE_URL, json={"email": email})
    assert r.status_code == 200
    mock_send.assert_called_once()
    record = db.exec(
        select(EmailVerification).where(EmailVerification.email == email)
    ).one()
    assert len(record.code_hash) == 64  # hashed, not plaintext


def test_send_code_rejects_registered_email(client: TestClient) -> None:
    r = client.post(CODE_URL, json={"email": settings.FIRST_SUPERUSER})
    assert r.status_code == 400
    assert "已被注册" in r.json()["detail"]


def test_send_code_resend_cooldown(client: TestClient, db: Session) -> None:
    email = random_email()
    insert_verification_code(db, email, "123456")  # just sent
    r = client.post(CODE_URL, json={"email": email})
    assert r.status_code == 429
    assert "频繁" in r.json()["detail"]


def test_send_code_daily_limit(client: TestClient, db: Session) -> None:
    email = random_email()
    # simulate 10 codes already sent today (older than cooldown)
    for _ in range(10):
        rec = insert_verification_code(db, email, "123456")
        rec.created_at = datetime.now(UTC) - timedelta(minutes=5)
        db.add(rec)
    db.commit()
    r = client.post(CODE_URL, json={"email": email})
    assert r.status_code == 429
    assert "上限" in r.json()["detail"]


def test_signup_with_valid_code(client: TestClient, db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    insert_verification_code(db, email, "654321")
    r = client.post(
        SIGNUP_URL,
        json={"email": email, "password": password, "code": "654321"},
    )
    assert r.status_code == 200
    assert r.json()["email"] == email
    # code is consumed
    remaining = db.exec(
        select(EmailVerification).where(EmailVerification.email == email)
    ).all()
    assert remaining == []


def test_signup_without_code_fails(client: TestClient) -> None:
    r = client.post(
        SIGNUP_URL,
        json={"email": random_email(), "password": random_lower_string()},
    )
    assert r.status_code == 422  # missing required field


def test_signup_with_wrong_code_fails(client: TestClient, db: Session) -> None:
    email = random_email()
    insert_verification_code(db, email, "654321")
    r = client.post(
        SIGNUP_URL,
        json={"email": email, "password": random_lower_string(), "code": "000000"},
    )
    assert r.status_code == 400
    assert "验证码错误" in r.json()["detail"]
    # attempt counter went up
    record = db.exec(
        select(EmailVerification).where(EmailVerification.email == email)
    ).one()
    assert record.attempts == 1
    # user not created
    assert db.exec(select(User).where(User.email == email)).first() is None


def test_signup_with_expired_code_fails(client: TestClient, db: Session) -> None:
    email = random_email()
    insert_verification_code(db, email, "654321", expired=True)
    r = client.post(
        SIGNUP_URL,
        json={"email": email, "password": random_lower_string(), "code": "654321"},
    )
    assert r.status_code == 400
    assert "过期" in r.json()["detail"]


def test_signup_code_attempts_limit(client: TestClient, db: Session) -> None:
    email = random_email()
    insert_verification_code(db, email, "654321")
    for _ in range(5):
        r = client.post(
            SIGNUP_URL,
            json={"email": email, "password": random_lower_string(), "code": "000000"},
        )
        assert r.status_code == 400
    # now even the correct code is rejected
    r = client.post(
        SIGNUP_URL,
        json={"email": email, "password": random_lower_string(), "code": "654321"},
    )
    assert r.status_code == 400
    assert "次数过多" in r.json()["detail"]
