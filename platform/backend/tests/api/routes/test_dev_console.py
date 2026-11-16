"""Dev console authorization and aggregation using an isolated platform test DB.

The session-scoped ``db`` fixture has no per-test teardown, so every test
cleans up the rows it creates — otherwise leaked enrollments/courses break
the endpoints' global aggregations in later tests.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete as sa_delete
from sqlmodel import Session

from app import crud
from app.models import Course, Enrollment, User, UserCreate
from app.services import (
    student_analytics_client,
    student_chat_records_client,
    teacher_publication_client,
)
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

BASE = "/api/v1/dev-console"


def create_user(db: Session, role: str, *, superuser: bool = False):
    email = random_email()
    password = random_lower_string()
    user = crud.create_user(session=db, user_create=UserCreate(email=email, password=password, role=role))
    if superuser:
        user.is_superuser = True
        db.add(user)
        db.commit()
        db.refresh(user)
    return user, email, password


def seed_course(db: Session, teacher, title: str, students) -> Course:
    course = Course(title=title, owner_id=teacher.id)
    db.add(course)
    db.commit()
    db.refresh(course)
    db.add_all([Enrollment(course_id=course.id, student_id=s.id) for s in students])
    db.commit()
    return course


def cleanup(db: Session, courses, users) -> None:
    """Delete this test's courses and users (DB-level FKs cascade the rest)."""
    for course in courses:
        db.execute(sa_delete(Enrollment).where(Enrollment.course_id == course.id))
        db.execute(sa_delete(Course).where(Course.id == course.id))
    for user in users:
        db.execute(sa_delete(Enrollment).where(Enrollment.student_id == user.id))
        db.execute(sa_delete(User).where(User.id == user.id))
    db.commit()


def _session_row(student, key=None, last="2026-01-02T00:00:00+00:00"):
    return {"sessionKey": key or str(uuid.uuid4()),
            "studentId": str(student.id), "classroomId": None,
            "startedAt": "2026-01-01T00:00:00+00:00", "lastActiveAt": last,
            "ended": False, "lessonId": None, "messageCount": 3}


def test_dev_console_is_observer_or_superuser_only(client: TestClient, db: Session) -> None:
    _, student_email, student_password = create_user(db, "student")
    _, teacher_email, teacher_password = create_user(db, "teacher")
    _, observer_email, observer_password = create_user(db, "observer")

    student_headers = user_authentication_headers(client=client, email=student_email, password=student_password)
    teacher_headers = user_authentication_headers(client=client, email=teacher_email, password=teacher_password)
    observer_headers = user_authentication_headers(client=client, email=observer_email, password=observer_password)

    for path in (
        f"{BASE}/overview",
        f"{BASE}/course-health",
        f"{BASE}/student-activity",
        f"{BASE}/chat-sessions",
    ):
        assert client.get(path).status_code in (401, 403)
        assert client.get(path, headers=student_headers).status_code == 403
        assert client.get(path, headers=teacher_headers).status_code == 403
        assert client.get(path, headers=observer_headers).status_code == 200


def test_superuser_passes_observer_boundary(client: TestClient, db: Session) -> None:
    _, email, password = create_user(db, "teacher", superuser=True)
    headers = user_authentication_headers(client=client, email=email, password=password)
    assert client.get(f"{BASE}/overview", headers=headers).status_code == 200


def test_chat_sessions_merge_names_search_and_scope(
    client: TestClient, db: Session, monkeypatch,
) -> None:
    _, observer_email, observer_password = create_user(db, "observer")
    teacher, _, _ = create_user(db, "teacher")
    student_a, _, _ = create_user(db, "student")
    student_b, _, _ = create_user(db, "student")
    course_a = seed_course(db, teacher, "诊断课程A", [student_a])
    course_b = seed_course(db, teacher, "诊断课程B", [student_b])
    key_a = str(uuid.uuid4())

    def sessions(course_id, user_ids, _limit):
        if course_id == course_a.id:
            assert user_ids == [str(student_a.id)]
            return [_session_row(student_a, key_a)]
        return []

    monkeypatch.setattr(student_chat_records_client, "get_chat_sessions", sessions)
    monkeypatch.setattr(
        teacher_publication_client, "get_teacher_publication",
        lambda course_id, owner_id: {"publicationId": "p1", "version": 2},
    )
    headers = user_authentication_headers(client=client, email=observer_email, password=observer_password)

    merged = client.get(f"{BASE}/chat-sessions", headers=headers).json()
    assert merged["unavailableCourses"] == []
    assert [row["sessionKey"] for row in merged["sessions"]] == [key_a]
    row = merged["sessions"][0]
    assert row["course"] == "诊断课程A"
    assert row["student"]

    by_q = client.get(
        f"{BASE}/chat-sessions", params={"q": "课程A"}, headers=headers,
    ).json()
    assert [r["sessionKey"] for r in by_q["sessions"]] == [key_a]
    miss = client.get(
        f"{BASE}/chat-sessions", params={"q": "不存在的词"}, headers=headers,
    ).json()
    assert miss["sessions"] == []

    scoped = client.get(
        f"{BASE}/chat-sessions", params={"course_id": str(course_b.id)}, headers=headers,
    ).json()
    assert scoped["sessions"] == []

    cleanup(db, [course_a, course_b], [teacher, student_a, student_b])


def test_overview_counts_and_pending(client: TestClient, db: Session, monkeypatch) -> None:
    _, observer_email, observer_password = create_user(db, "observer")
    teacher, _, _ = create_user(db, "teacher")
    student, _, _ = create_user(db, "student")
    course = seed_course(db, teacher, "待发布课程", [student])

    # chat service down for every course → chat stats must be None, not zeros
    def boom(_course_id, _user_ids, _limit):
        raise student_chat_records_client.StudentChatUnavailable("down")

    monkeypatch.setattr(student_chat_records_client, "get_chat_sessions", boom)
    monkeypatch.setattr(
        teacher_publication_client, "get_teacher_publication",
        lambda course_id, owner_id: None,  # explicitly unpublished
    )
    headers = user_authentication_headers(client=client, email=observer_email, password=observer_password)

    data = client.get(f"{BASE}/overview", headers=headers).json()
    assert data["users"]["teachers"] >= 1
    assert data["users"]["students"] >= 1
    assert data["courses"] >= 1
    assert data["chat"] is None
    kinds = {item["kind"] for item in data["pending"]}
    assert "publication" in kinds  # enrolled but explicitly unpublished

    cleanup(db, [course], [teacher, student])


def test_overview_reports_inactive_students(client: TestClient, db: Session, monkeypatch) -> None:
    _, observer_email, observer_password = create_user(db, "observer")
    teacher, _, _ = create_user(db, "teacher")
    active, _, _ = create_user(db, "student")
    idle, _, _ = create_user(db, "student")
    course = seed_course(db, teacher, "活跃度课程", [active, idle])

    def sessions(_course_id, user_ids, _limit):
        # only this test's active student ever chatted, and recently
        if str(active.id) in user_ids:
            return [_session_row(active, last="2100-01-01T00:00:00+00:00")]
        return []

    monkeypatch.setattr(student_chat_records_client, "get_chat_sessions", sessions)
    monkeypatch.setattr(
        teacher_publication_client, "get_teacher_publication",
        lambda course_id, owner_id: {"publicationId": "p1", "version": 1},
    )
    headers = user_authentication_headers(client=client, email=observer_email, password=observer_password)

    data = client.get(f"{BASE}/overview", headers=headers).json()
    assert data["chat"]["total"] == 1
    inactive = next(item for item in data["pending"] if item["kind"] == "inactive")
    assert inactive["count"] == 1  # only the idle student

    cleanup(db, [course], [teacher, active, idle])


def test_course_health_risk_mapping(client: TestClient, db: Session, monkeypatch) -> None:
    _, observer_email, observer_password = create_user(db, "observer")
    teacher, _, _ = create_user(db, "teacher")
    learner, _, _ = create_user(db, "student")
    published = seed_course(db, teacher, "健康课程", [learner])
    unpublished = seed_course(db, teacher, "停滞课程", [learner])

    def learning(course_id, _user_ids):
        if course_id == published.id:
            return {"sessions": [_session_row(learner,
                    last="2100-01-01T00:00:00+00:00")], "mastery": [], "eventSummary": {}}
        return {"sessions": [], "mastery": [], "eventSummary": {}}

    def publication(course_id, _owner_id):
        return {"publicationId": "p1", "version": 1} if course_id == published.id else None

    monkeypatch.setattr(student_analytics_client, "get_course_learning_data", learning)
    monkeypatch.setattr(teacher_publication_client, "get_teacher_publication", publication)
    headers = user_authentication_headers(client=client, email=observer_email, password=observer_password)

    rows = {row["title"]: row for row in client.get(
        f"{BASE}/course-health", headers=headers,
    ).json()}
    assert rows["健康课程"]["risk"] == "正常"
    assert rows["健康课程"]["published"] is True
    assert rows["健康课程"]["sessionCount"] == 1
    # 已选课未发布 is the root-cause risk and outranks 无会话
    assert rows["停滞课程"]["risk"] == "已选课未发布"
    assert rows["停滞课程"]["published"] is False

    cleanup(db, [published, unpublished], [teacher, learner])


def test_student_activity_risk_mapping(client: TestClient, db: Session, monkeypatch) -> None:
    _, observer_email, observer_password = create_user(db, "observer")
    teacher, _, _ = create_user(db, "teacher")
    active, _, _ = create_user(db, "student")
    idle, _, _ = create_user(db, "student")
    course = seed_course(db, teacher, "活跃课程", [active, idle])

    def sessions(_course_id, user_ids, _limit):
        if str(active.id) in user_ids:
            return [_session_row(active, last="2100-01-01T00:00:00+00:00")]
        return []

    monkeypatch.setattr(student_chat_records_client, "get_chat_sessions", sessions)
    headers = user_authentication_headers(client=client, email=observer_email, password=observer_password)

    rows = {row["name"]: row for row in client.get(
        f"{BASE}/student-activity", headers=headers,
    ).json()}
    assert rows[active.full_name or active.email]["risk"] == "正常"
    assert rows[idle.full_name or idle.email]["risk"] == "从未学习"

    cleanup(db, [course], [teacher, active, idle])


def test_chat_messages_pass_through_and_scope(client: TestClient, db: Session, monkeypatch) -> None:
    _, observer_email, observer_password = create_user(db, "observer")
    teacher, _, _ = create_user(db, "teacher")
    student, _, _ = create_user(db, "student")
    course = seed_course(db, teacher, "消息课程", [student])
    key = str(uuid.uuid4())

    def messages(_course_id, session_key, user_ids, phase, _limit, _offset):
        assert user_ids == [str(student.id)]
        if session_key != key:
            raise student_chat_records_client.StudentChatMissing()
        if phase == "bad":
            raise student_chat_records_client.StudentChatUnavailable("down")
        return [{"seq": 1, "role": "student", "phase": "recall",
                 "content": "hello", "createdAt": "2026-01-01T00:00:00"}]

    monkeypatch.setattr(student_chat_records_client, "get_chat_messages", messages)
    headers = user_authentication_headers(client=client, email=observer_email, password=observer_password)
    path = f"{BASE}/courses/{course.id}/chat-sessions/{{key}}/messages"

    body = client.get(path.format(key=key), headers=headers).json()
    assert body[0]["content"] == "hello"
    assert "id" not in body[0]

    assert client.get(path.format(key=key), params={"phase": "bad"}, headers=headers).status_code == 503
    assert client.get(path.format(key=str(uuid.uuid4())), headers=headers).status_code == 404
    assert client.get(
        f"{BASE}/courses/{uuid.uuid4()}/chat-sessions/{key}/messages", headers=headers,
    ).status_code == 404

    cleanup(db, [course], [teacher, student])
