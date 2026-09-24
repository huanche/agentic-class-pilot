"""Authorization rules of the teacher bridge for the new teacher service entries.

Covers: service key validation, anonymous/role rejection, write-origin control,
course ownership, classroom-scoped resolution (API query, media path, player
page), and the legacy admin-only rule for unscoped APIs.
"""
import hashlib
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.models import User

BRIDGE_KEY = "bridge-test-key"
ALLOWED_ORIGIN = "http://localhost:3200"


def make_user(role: str, email: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        hashed_password="not-a-real-hash",
        role=role,
        is_active=True,
        is_superuser=False,
    )


def issue_session_token(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(48)
    db.execute(
        text("INSERT INTO browser_session (token_hash,user_id,expires_at) VALUES (:t,:u,now() + interval '1 hour')"),
        {"t": hashlib.sha256(token.encode()).hexdigest(), "u": user.id},
    )
    db.commit()
    return token


@pytest.fixture(autouse=True)
def bridge_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TEACHER_SERVICE_KEY", BRIDGE_KEY)
    monkeypatch.setattr(settings, "TEACHER_ALLOWED_ORIGINS", ALLOWED_ORIGIN)
    monkeypatch.setattr(settings, "FRONTEND_HOST", "http://platform.test:8080")


@pytest.fixture(scope="module")
def bridge_world(db: Session):
    """Teacher/student identities plus teacher-schema rows.

    The teacher schema itself is owned by the final02 migration (run by
    check_backend.py / pytest_route.py before pytest); tests only insert rows.
    Self-healing: rows from an earlier aborted run are removed first so a
    once-broken teardown cannot poison every later run.
    """
    db.execute(text("DELETE FROM teacher.mentra_classrooms"))
    db.execute(text("DELETE FROM teacher.mentra_courses"))
    db.execute(text("DELETE FROM browser_session WHERE user_id IN (SELECT id FROM \"user\" WHERE email LIKE 'bridge-%')"))
    db.execute(text("DELETE FROM \"user\" WHERE email LIKE 'bridge-%'"))
    db.commit()
    teacher_a = make_user("teacher", "bridge-a@test.local")
    teacher_b = make_user("teacher", "bridge-b@test.local")
    student = make_user("student", "bridge-student@test.local")
    db.add_all([teacher_a, teacher_b, student])
    db.commit()
    course_a, course_b = str(uuid.uuid4()), str(uuid.uuid4())
    classroom_a = str(uuid.uuid4())
    db.execute(
        text("INSERT INTO teacher.mentra_courses (id,teacher_id,status,title,payload,created_at,updated_at) "
             "VALUES (:id,:t,'draft',:ti,CAST(:p AS jsonb),:now,:now)"),
        [{"id": course_a, "t": str(teacher_a.id), "ti": "Course A", "p": "{}", "now": 1},
         {"id": course_b, "t": str(teacher_b.id), "ti": "Course B", "p": "{}", "now": 1}],
    )
    db.execute(
        text("INSERT INTO teacher.mentra_classrooms (id,course_id,stage,scenes,payload,created_at,updated_at) "
             "VALUES (:id,:c,CAST('[]' AS jsonb),CAST('[]' AS jsonb),CAST('{}' AS jsonb),1,1)"),
        [{"id": classroom_a, "c": course_a}, {"id": str(uuid.uuid4()), "c": None}],
    )
    db.commit()
    yield {
        "teacher_a": teacher_a,
        "teacher_b": teacher_b,
        "student": student,
        "course_a": course_a,
        "course_b": course_b,
        "classroom_a": classroom_a,
        "token_a": issue_session_token(db, teacher_a),
        "token_b": issue_session_token(db, teacher_b),
        "token_student": issue_session_token(db, student),
    }
    db.execute(text("DELETE FROM teacher.mentra_classrooms"))
    db.execute(text("DELETE FROM teacher.mentra_courses"))
    db.execute(text("DELETE FROM browser_session WHERE user_id IN (:a,:b,:s)"),
               {"a": teacher_a.id, "b": teacher_b.id, "s": student.id})
    for user in (teacher_a, teacher_b, student):
        db.delete(user)
    db.commit()


def authorize(client: TestClient, *, path: str, method: str = "GET",
              cookie: str | None = None, origin: str | None = None,
              service_user_id: str | None = None, service_key: str | None = BRIDGE_KEY):
    return client.post(
        "/api/v1/internal/teacher/authorize",
        json={"cookie": cookie, "path": path, "method": method, "origin": origin,
              "service_user_id": service_user_id},
        headers={"X-Teacher-Service-Key": service_key or ""},
    )


def test_rejects_wrong_service_key(client: TestClient, bridge_world) -> None:
    assert authorize(client, path="/api/course-space", service_key="wrong").status_code == 403


def test_rejects_anonymous(client: TestClient, bridge_world) -> None:
    assert authorize(client, path="/api/course-space").status_code == 401


def test_rejects_student_role(client: TestClient, bridge_world) -> None:
    assert authorize(client, path="/api/course-space", cookie=bridge_world["token_student"]).status_code == 403


def test_allows_teacher_on_unscoped_course_space(client: TestClient, bridge_world) -> None:
    response = authorize(client, path="/api/course-space", cookie=bridge_world["token_a"])
    assert response.status_code == 200
    assert response.json()["userId"] == str(bridge_world["teacher_a"].id)


def test_enforces_write_origins(client: TestClient, bridge_world) -> None:
    assert authorize(client, path="/api/course-space", method="POST",
                     cookie=bridge_world["token_a"], origin="http://evil.test").status_code == 403
    assert authorize(client, path="/api/course-space", method="POST",
                     cookie=bridge_world["token_a"], origin=ALLOWED_ORIGIN).status_code == 200
    assert authorize(client, path="/api/course-space", method="POST",
                     cookie=bridge_world["token_a"], origin="http://platform.test:8080").status_code == 200


def test_course_ownership(client: TestClient, bridge_world) -> None:
    own = authorize(client, path=f"/api/course-space/{bridge_world['course_a']}", cookie=bridge_world["token_a"])
    other = authorize(client, path=f"/api/course-space/{bridge_world['course_b']}", cookie=bridge_world["token_a"])
    missing = authorize(client, path="/api/course-space/00000000-0000-0000-0000-000000000000", cookie=bridge_world["token_a"])
    assert own.status_code == 200
    assert other.status_code == 403
    assert missing.status_code == 404


def test_classroom_api_scope_uses_query_id(client: TestClient, bridge_world) -> None:
    own = authorize(client, path=f"/api/classroom?id={bridge_world['classroom_a']}", cookie=bridge_world["token_a"])
    other = authorize(client, path=f"/api/classroom?id={bridge_world['classroom_a']}", cookie=bridge_world["token_b"])
    missing = authorize(client, path="/api/classroom?id=does-not-exist", cookie=bridge_world["token_a"])
    assert own.status_code == 200
    assert other.status_code == 403
    assert missing.status_code == 404


def test_classroom_media_scope(client: TestClient, bridge_world) -> None:
    own = authorize(client, path=f"/api/classroom-media/{bridge_world['classroom_a']}/audio/a.mp3", cookie=bridge_world["token_a"])
    other = authorize(client, path=f"/api/classroom-media/{bridge_world['classroom_a']}/audio/a.mp3", cookie=bridge_world["token_b"])
    assert own.status_code == 200
    assert other.status_code == 403


def test_player_page_scope(client: TestClient, bridge_world) -> None:
    own = authorize(client, path=f"/classroom-player/{bridge_world['classroom_a']}", cookie=bridge_world["token_a"])
    other = authorize(client, path=f"/classroom-player/{bridge_world['classroom_a']}", cookie=bridge_world["token_b"])
    legacy = authorize(client, path=f"/classroom/{bridge_world['classroom_a']}", cookie=bridge_world["token_a"])
    assert own.status_code == 200
    assert other.status_code == 403
    assert legacy.status_code == 200


def test_classes_api_is_course_scoped(client: TestClient, bridge_world) -> None:
    own = authorize(client, path=f"/api/classes/{bridge_world['course_a']}", cookie=bridge_world["token_a"])
    other = authorize(client, path=f"/api/classes/{bridge_world['course_a']}", cookie=bridge_world["token_b"])
    assert own.status_code == 200
    assert other.status_code == 403


def test_legacy_unscoped_api_stays_teacher_denied(client: TestClient, bridge_world) -> None:
    blocked = authorize(client, path="/api/generate/image", cookie=bridge_world["token_a"])
    delegated = authorize(client, path="/api/generate/image", service_user_id=str(bridge_world["teacher_a"].id))
    assert blocked.status_code == 403
    assert delegated.status_code == 200


def test_service_delegation_skips_origin_check(client: TestClient, bridge_world) -> None:
    response = authorize(client, path="/api/course-space", method="POST",
                         service_user_id=str(bridge_world["teacher_a"].id), origin="http://evil.test")
    assert response.status_code == 200
    assert response.json()["userId"] == str(bridge_world["teacher_a"].id)
