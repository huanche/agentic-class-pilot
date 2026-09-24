"""Learning-context endpoint contract tests (schemaVersion 1)."""
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app.api.routes.student_bridge import issue_launch_token
from app.core.db import engine

BRIDGE_KEY = "student-bridge-test-key"


@pytest.fixture(autouse=True)
def bridge_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings := __import__("app.core.config", fromlist=["settings"]).settings,
                        "STUDENT_SERVICE_KEY", BRIDGE_KEY)


@pytest.fixture(scope="module")
def context_world(db):
    """Course chain: published package + activated classroom + enrolled student."""
    student_id = uuid.uuid4()
    course_full = uuid.uuid4()      # package + classroom
    course_text = uuid.uuid4()      # package only
    course_draft = uuid.uuid4()     # draft package only
    classroom_id = f"ctx-{uuid.uuid4().hex[:8]}"
    now = int(time.time() * 1000)

    def course_row(course_id):
        return {"id": str(course_id), "owner": str(student_id), "title": f"课-{str(course_id)[:6]}"}

    with Session(engine) as session:
        session.execute(
            text("INSERT INTO public.user (email, hashed_password, role, is_active, is_superuser, id) "
                 "VALUES (:email, 'x', 'student', true, false, :id)"),
            {"email": f"ctx-{student_id.hex[:6]}@test.local", "id": str(student_id)})
        for course_id in (course_full, course_text, course_draft):
            session.execute(
                text("INSERT INTO public.course (id, owner_id, title, enroll_code, created_at) "
                     "VALUES (:id, :owner, :title, :code, now())"),
                {"id": str(course_id), "owner": str(student_id),
                 "title": course_row(course_id)["title"], "code": uuid.uuid4().hex[:8].upper()})
            session.execute(
                text("INSERT INTO teacher.mentra_courses (id, teacher_id, status, title, payload, created_at, updated_at) "
                     "VALUES (:id, :owner, 'active', :title, CAST(:payload AS jsonb), 1, 1) "
                     "ON CONFLICT (id) DO NOTHING"),
                {"id": str(course_id), "owner": str(student_id),
                 "title": course_row(course_id)["title"], "payload": json.dumps({"id": str(course_id)})})
            session.execute(
                text("INSERT INTO teacher_course_link (course_id, external_course_id) VALUES (:c, :e) "
                     "ON CONFLICT (course_id) DO NOTHING"),
                {"c": str(course_id), "e": str(course_id)})
            session.execute(
                text("INSERT INTO enrollment (id, course_id, student_id, created_at) VALUES (:eid, :c, :s, now())"),
                {"eid": str(uuid.uuid4()), "c": str(course_id), "s": str(student_id)})
        for course_id, status in ((course_full, "published"), (course_text, "published"), (course_draft, "draft")):
            session.execute(
                text("INSERT INTO teacher.mentra_knowledge_packages (id, course_id, teacher_id, version, status, payload, created_at) "
                     "VALUES (:id, :c, :t, 1, :status, CAST(:payload AS jsonb), 1)"),
                {"id": f"pkg-{course_id.hex[:8]}", "c": str(course_id), "t": str(student_id), "status": status,
                 "payload": json.dumps({"id": f"pkg-{course_id.hex[:8]}", "version": 1, "status": status,
                                        "entries": [{"id": "e1", "title": "条目一", "content": "内容一",
                                                     "citations": []}]})})
        session.execute(
            text("INSERT INTO teacher.mentra_classrooms (id, course_id, artifact_id, stage, scenes, payload, created_at, updated_at) "
                 "VALUES (:id, :c, NULL, CAST(:stage AS jsonb), CAST(:scenes AS jsonb), CAST('{}' AS jsonb), 1, 1)"),
            {"id": classroom_id, "c": str(course_full),
             "stage": json.dumps({"id": classroom_id, "name": "测试课堂"}),
             "scenes": json.dumps([{"id": "scene-1", "type": "slide", "order": 1, "title": "第一页",
                                    "actions": [{"id": "a1", "type": "speech", "text": "讲解一"}]}])})
        session.execute(
            text("INSERT INTO teacher.mentra_course_artifacts (id, job_id, course_id, teacher_id, artifact_type, status, payload, created_at, updated_at) "
                 "VALUES (:id, :job, :c, :t, 'lesson-courseware', 'published', CAST(:payload AS jsonb), 1, 1)"),
            {"id": f"art-{course_full.hex[:8]}", "job": "job-1", "c": str(course_full), "t": str(student_id),
             "payload": json.dumps({"id": f"art-{course_full.hex[:8]}", "classroomId": classroom_id,
                                    "classPublicationId": "CLS-A-ctx", "classPublishedAt": now})})
        session.commit()

    yield {"student_id": str(student_id), "course_full": str(course_full),
           "course_text": str(course_text), "course_draft": str(course_draft),
           "classroom_id": classroom_id}

    with Session(engine) as session:
        for course_id in (course_full, course_text, course_draft):
            session.execute(text("DELETE FROM enrollment WHERE course_id=:c"), {"c": str(course_id)})
            session.execute(text("DELETE FROM teacher_course_link WHERE course_id=:c"), {"c": str(course_id)})
            session.execute(text("DELETE FROM teacher.mentra_knowledge_packages WHERE course_id=:c"), {"c": str(course_id)})
            session.execute(text("DELETE FROM teacher.mentra_course_artifacts WHERE course_id=:c"), {"c": str(course_id)})
            session.execute(text("DELETE FROM teacher.mentra_courses WHERE id=:c"), {"c": str(course_id)})
            session.execute(text("DELETE FROM public.course WHERE id=:c"), {"c": str(course_id)})
        session.execute(text("DELETE FROM teacher.mentra_classrooms WHERE id=:id"), {"id": classroom_id})
        session.execute(text("DELETE FROM public.user WHERE id=:u"), {"u": str(student_id)})
        session.commit()


def _fetch(client: TestClient, token: str) -> object:
    return client.post("/api/v1/internal/student/learning-context",
                       headers={"X-Student-Service-Key": BRIDGE_KEY},
                       json={"launch_token": token})


def test_full_context_with_classroom_and_playback_grant(client: TestClient, context_world) -> None:
    token = issue_launch_token(uuid.UUID(context_world["student_id"]),
                               uuid.UUID(context_world["course_full"]),
                               context_world["classroom_id"],
                               {"publicationId": "pkg-x", "version": 1})
    response = _fetch(client, token)
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["schemaVersion"] == 1
    assert body["knowledgePackage"]["entries"][0]["title"] == "条目一"
    assert body["classroom"]["id"] == context_world["classroom_id"]
    assert body["classroom"]["scenes"][0]["actions"][0]["text"] == "讲解一"
    assert body["classroom"]["playerUrl"].endswith(f"/classroom-player/{context_world['classroom_id']}")
    assert body["classroom"]["playbackToken"]


def test_text_only_context_has_null_classroom(client: TestClient, context_world) -> None:
    token = issue_launch_token(uuid.UUID(context_world["student_id"]),
                               uuid.UUID(context_world["course_text"]),
                               "ignored", {"publicationId": "pkg-y", "version": 1})
    response = _fetch(client, token)
    assert response.status_code == 200
    assert response.json()["classroom"] is None


def test_draft_package_not_served(client: TestClient, context_world) -> None:
    token = issue_launch_token(uuid.UUID(context_world["student_id"]),
                               uuid.UUID(context_world["course_draft"]),
                               "x", {"publicationId": "pkg-z", "version": 1})
    response = _fetch(client, token)
    assert response.status_code == 409


def test_unenrolled_student_rejected(client: TestClient, context_world, db) -> None:
    outsider = uuid.uuid4()
    with Session(engine) as session:
        session.execute(text("INSERT INTO public.user (email, hashed_password, role, is_active, is_superuser, id) "
                             "VALUES ('ctx-out@test.local', 'x', 'student', true, false, :id)"), {"id": str(outsider)})
        session.commit()
    try:
        token = issue_launch_token(outsider, uuid.UUID(context_world["course_full"]),
                                   context_world["classroom_id"], {"publicationId": "p", "version": 1})
        response = _fetch(client, token)
        assert response.status_code == 403
    finally:
        with Session(engine) as session:
            session.execute(text("DELETE FROM public.user WHERE id=:id"), {"id": str(outsider)})
            session.commit()
