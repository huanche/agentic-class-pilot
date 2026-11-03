"""Learning-context route tests with teacher data behind the service boundary."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app.api.routes import student_bridge
from app.api.routes.student_bridge import issue_launch_token
from app.core.config import settings
from app.core.db import engine
from app.services import course_publication

BRIDGE_KEY = "student-bridge-test-key"


@pytest.fixture
def context_world(db, monkeypatch):
    student_id = uuid.uuid4()
    full, text_only, draft = (uuid.uuid4() for _ in range(3))
    room = f"ctx-{uuid.uuid4().hex[:8]}"
    courses = (full, text_only, draft)
    monkeypatch.setattr(settings, "STUDENT_SERVICE_KEY", BRIDGE_KEY)

    def publication(course_id, owner_id):
        assert owner_id == student_id
        if course_id == draft:
            return None
        return {"publicationId": f"pkg-{course_id.hex[:8]}", "version": 1}

    def content(_session, course_id, _user_id):
        if course_id == draft:
            return None, []
        package = {"id": f"pkg-{course_id.hex[:8]}", "version": 1,
                   "entries": [{"id": "e1", "title": "条目一", "content": "内容一",
                                "scope": {"type": "lesson", "lessonId": "lesson-1"}}]}
        if course_id == text_only:
            return package, []
        classroom = {"id": room, "title": "测试课堂",
                     "scenes": [{"id": "scene-1", "type": "slide", "order": 1,
                                 "title": "第一页", "actions": [{"id": "a1", "type": "speech",
                                                           "text": "讲解一"}]}],
                     "playerUrl": f"{settings.TEACHER_PUBLIC_URL.rstrip('/')}/classroom-player/{room}"}
        return package, [{"id": "lesson-1", "title": "第一课", "order": 1,
                          "week": 1, "lessonNumber": 1, "publishedAt": 1,
                          "classroom": classroom}]

    monkeypatch.setattr(course_publication, "get_teacher_publication", publication)
    # Snapshot projection has separate unit tests; here we exercise the route.
    monkeypatch.setattr(student_bridge, "_load_published_content", content)
    monkeypatch.setattr(student_bridge, "ensure_published_knowledge_job",
                        lambda *_args: "test-revision")

    with Session(engine) as session:
        session.execute(text("INSERT INTO public.user "
                             "(email, hashed_password, role, is_active, is_superuser, id) "
                             "VALUES (:email, 'x', 'student', true, false, :id)"),
                        {"email": f"ctx-{student_id.hex[:8]}@test.local", "id": str(student_id)})
        for course_id in courses:
            session.execute(text("INSERT INTO public.course "
                                 "(id, owner_id, title, enroll_code, created_at) "
                                 "VALUES (:id, :owner, :title, :code, now())"),
                            {"id": str(course_id), "owner": str(student_id),
                             "title": f"课-{course_id.hex[:6]}", "code": course_id.hex[:8].upper()})
            session.execute(text("INSERT INTO public.enrollment "
                                 "(id, course_id, student_id, created_at) "
                                 "VALUES (:id, :course, :student, now())"),
                            {"id": str(uuid.uuid4()), "course": str(course_id),
                             "student": str(student_id)})
        session.commit()

    yield {"student_id": str(student_id), "course_full": str(full),
           "course_text": str(text_only), "course_draft": str(draft),
           "classroom_id": room, "lesson_id": "lesson-1"}

    with Session(engine) as session:
        for course_id in courses:
            session.execute(text("DELETE FROM public.enrollment WHERE course_id=:id"),
                            {"id": str(course_id)})
            session.execute(text("DELETE FROM public.course WHERE id=:id"),
                            {"id": str(course_id)})
        session.execute(text("DELETE FROM public.user WHERE id=:id"),
                        {"id": str(student_id)})
        session.commit()


def _fetch(client: TestClient, token: str, lesson_id: str | None = None):
    return client.post("/api/v1/internal/student/learning-context",
                       headers={"X-Student-Service-Key": BRIDGE_KEY},
                       json={"launch_token": token, "lesson_id": lesson_id})


def _token(world, course_key):
    return issue_launch_token(uuid.UUID(world["student_id"]),
                              uuid.UUID(world[course_key]), world["classroom_id"],
                              {"publicationId": "pkg-test", "version": 1})


def test_full_context_with_classroom(client: TestClient, context_world):
    response = _fetch(client, _token(context_world, "course_full"), context_world["lesson_id"])
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["schemaVersion"] == 1
    assert body["knowledgePackage"]["entries"][0]["title"] == "条目一"
    assert body["classroom"]["id"] == context_world["classroom_id"]
    assert body["classroom"]["scenes"][0]["actions"][0]["text"] == "讲解一"
    assert body["classroom"]["playerUrl"].endswith(f"/classroom-player/{context_world['classroom_id']}")
    assert "playbackToken" not in body["classroom"]


def test_text_only_context_has_null_classroom(client: TestClient, context_world):
    response = _fetch(client, _token(context_world, "course_text"))
    assert response.status_code == 200
    assert response.json()["classroom"] is None


def test_draft_package_not_served(client: TestClient, context_world):
    assert _fetch(client, _token(context_world, "course_draft")).status_code == 409


def test_unenrolled_student_rejected(client: TestClient, context_world):
    token = issue_launch_token(uuid.uuid4(), uuid.UUID(context_world["course_full"]),
                               context_world["classroom_id"],
                               {"publicationId": "pkg-test", "version": 1})
    assert _fetch(client, token).status_code == 403
