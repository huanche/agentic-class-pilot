"""Unified agent-session API: resolver, permission chain, idempotency,
lease, consistency assertions, legacy outline import, purge hooks.

Agent methods are stubbed on the module-level singletons (same pattern as
test_chat.py) so no real LLM is called. Map coverage: acceptance criteria
#1-3, 5-7, 9-15 of docs/agent-isolation-plan.md §11.
"""

import json
import uuid
from collections.abc import AsyncGenerator
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.langgraph.graph import langgraph_agent
from app.core.langgraph.outline import outline_agent
from app.models import (
    AgentSession,
    Chapter,
    Course,
    Enrollment,
    UserCreate,
    get_datetime_utc,
)
from app.schemas.chat import HistoryMessage
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

API = "/api/v1/agent-sessions"


def _create_user(db: Session, *, role: str = "student") -> dict[str, str]:
    email = random_email()
    password = random_lower_string()
    crud.create_user(
        session=db, user_create=UserCreate(email=email, password=password, role=role)
    )
    return {"email": email, "password": password}


def _headers(client: TestClient, user: dict[str, str]) -> dict[str, str]:
    return user_authentication_headers(
        client=client, email=user["email"], password=user["password"]
    )


def _uid(db: Session, user: dict[str, str]) -> Any:
    db_user = crud.get_user_by_email(session=db, email=user["email"])
    assert db_user is not None
    return db_user.id


def _make_course_with_chapter(db: Session, owner_id: Any) -> Course:
    course = Course(title="线性代数", description="数学基础课", owner_id=owner_id)
    db.add(course)
    db.commit()
    db.refresh(course)
    chapter = Chapter(title="行列式", course_id=course.id)
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    course.chapters = [chapter]  # type: ignore[attr-defined]
    return course


def _stub(monkeypatch: Any, target: Any, method: str, stub: Any) -> None:
    monkeypatch.setattr(target, method, stub, raising=True)


def _create_session(
    client: TestClient,
    headers: dict[str, str],
    *,
    agent_key: str,
    scope_type: str,
    scope_id: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    r = client.post(
        API,
        json={
            "agent_key": agent_key,
            "scope": {"type": scope_type, "id": scope_id},
            **({"idempotency_key": idempotency_key} if idempotency_key else {}),
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ----- Multi-session core (acceptance #1, #2) -----


def test_multiple_sessions_per_scope_and_switch(
    client: TestClient, db: Session, monkeypatch: Any
) -> None:
    teacher = _create_user(db, role="teacher")
    headers = _headers(client, teacher)
    course = _make_course_with_chapter(db, _uid(db, teacher))

    s1 = _create_session(
        client, headers, agent_key="outline", scope_type="course", scope_id=str(course.id)
    )
    s2 = _create_session(
        client, headers, agent_key="outline", scope_type="course", scope_id=str(course.id)
    )
    assert s1["id"] != s2["id"]

    listed = client.get(
        API,
        params={"agent_key": "outline", "scope_type": "course", "scope_id": str(course.id)},
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()["count"] == 2

    # histories are independent threads: s1 has history, s2 is empty
    row1 = db.get(AgentSession, uuid.UUID(s1["id"]))
    threads = {row1.thread_id: [HistoryMessage(role="assistant", content="旧大纲")]}

    async def fake_history(thread_id: str) -> list[HistoryMessage]:
        return threads.get(thread_id, [])

    _stub(monkeypatch, outline_agent, "get_chat_history", fake_history)

    r1 = client.get(
        f"{API}/{s1['id']}/messages",
        params={"agent_key": "outline", "scope_type": "course", "scope_id": str(course.id)},
        headers=headers,
    )
    r2 = client.get(
        f"{API}/{s2['id']}/messages",
        params={"agent_key": "outline", "scope_type": "course", "scope_id": str(course.id)},
        headers=headers,
    )
    assert [m["content"] for m in r1.json()["messages"]] == ["旧大纲"]
    assert r2.json()["messages"] == []


# ----- Resolve semantics (acceptance #15, §4.2) -----


def test_resolve_empty_scope_returns_null_without_creating(
    client: TestClient, db: Session
) -> None:
    teacher = _create_user(db, role="teacher")
    headers = _headers(client, teacher)
    course = _make_course_with_chapter(db, _uid(db, teacher))

    r = client.post(
        f"{API}/resolve",
        json={"agent_key": "outline", "scope": {"type": "course", "id": str(course.id)}},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json() is None
    # no creation side effect
    listed = client.get(
        API,
        params={"agent_key": "outline", "scope_type": "course", "scope_id": str(course.id)},
        headers=headers,
    )
    assert listed.json()["count"] == 0


def test_resolve_preferred_mismatch_is_404_not_fallback(
    client: TestClient, db: Session
) -> None:
    teacher = _create_user(db, role="teacher")
    headers = _headers(client, teacher)
    course = _make_course_with_chapter(db, _uid(db, teacher))
    other = _make_course_with_chapter(db, _uid(db, teacher))

    created = _create_session(
        client, headers, agent_key="outline", scope_type="course", scope_id=str(course.id)
    )
    # preferred session exists but belongs to another scope → 404, no silent
    # switch to another session of the requested scope
    r = client.post(
        f"{API}/resolve",
        json={
            "agent_key": "outline",
            "scope": {"type": "course", "id": str(other.id)},
            "preferred_session_id": created["id"],
        },
        headers=headers,
    )
    assert r.status_code == 404


def test_resolve_without_preferred_returns_most_recent(
    client: TestClient, db: Session
) -> None:
    teacher = _create_user(db, role="teacher")
    headers = _headers(client, teacher)
    course = _make_course_with_chapter(db, _uid(db, teacher))

    first = _create_session(
        client, headers, agent_key="outline", scope_type="course", scope_id=str(course.id)
    )
    second = _create_session(
        client, headers, agent_key="outline", scope_type="course", scope_id=str(course.id)
    )
    # backdate the first so the second is the most recently active
    row = db.get(AgentSession, uuid.UUID(first["id"]))
    row.updated_at = get_datetime_utc() - timedelta(hours=1)
    db.add(row)
    db.commit()

    r = client.post(
        f"{API}/resolve",
        json={"agent_key": "outline", "scope": {"type": "course", "id": str(course.id)}},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["id"] == second["id"]


# ----- Consistency assertions & cross-agent isolation (acceptance #3, #14) -----


def test_wrong_scope_or_agent_assertion_is_404(
    client: TestClient, db: Session
) -> None:
    teacher = _create_user(db, role="teacher")
    headers = _headers(client, teacher)
    course = _make_course_with_chapter(db, _uid(db, teacher))
    chapter: Chapter = course.chapters[0]  # type: ignore[index]

    created = _create_session(
        client, headers, agent_key="chat", scope_type="chapter", scope_id=str(chapter.id)
    )
    base = f"{API}/{created['id']}"
    # wrong scope_id
    assert (
        client.get(
            base,
            params={"agent_key": "chat", "scope_type": "chapter", "scope_id": str(course.id)},
            headers=headers,
        ).status_code
        == 404
    )
    # wrong agent (chat session asked-for as outline)
    assert (
        client.get(
            base,
            params={"agent_key": "outline", "scope_type": "chapter", "scope_id": str(chapter.id)},
            headers=headers,
        ).status_code
        == 404
    )
    # right assertion works
    assert (
        client.get(
            base,
            params={"agent_key": "chat", "scope_type": "chapter", "scope_id": str(chapter.id)},
            headers=headers,
        ).status_code
        == 200
    )


def test_unknown_agent_key_is_404(client: TestClient, db: Session) -> None:
    teacher = _create_user(db, role="teacher")
    r = client.post(
        API,
        json={
            "agent_key": "nope",
            "scope": {"type": "course", "id": str(uuid.uuid4())},
        },
        headers=_headers(client, teacher),
    )
    assert r.status_code == 404


def test_outline_rejects_student_and_foreign_course(
    client: TestClient, db: Session
) -> None:
    owner = _create_user(db, role="teacher")
    student = _create_user(db)
    stranger = _create_user(db, role="teacher")
    course = _make_course_with_chapter(db, _uid(db, owner))

    # student cannot even resolve the outline scope (teacher gate, 403)
    r = client.post(
        f"{API}/resolve",
        json={"agent_key": "outline", "scope": {"type": "course", "id": str(course.id)}},
        headers=_headers(client, student),
    )
    assert r.status_code == 403
    # another teacher does not own the course
    r = client.post(
        f"{API}/resolve",
        json={"agent_key": "outline", "scope": {"type": "course", "id": str(course.id)}},
        headers=_headers(client, stranger),
    )
    assert r.status_code == 403


# ----- Ownership rules (acceptance #3, #5, §5) -----


def test_foreign_session_is_404_for_users_and_200_for_superuser_on_chat(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    teacher = _create_user(db, role="teacher")
    course = _make_course_with_chapter(db, _uid(db, teacher))
    chapter: Chapter = course.chapters[0]  # type: ignore[index]
    stranger = _create_user(db)

    created = _create_session(
        client,
        _headers(client, teacher),
        agent_key="chat",
        scope_type="chapter",
        scope_id=str(chapter.id),
    )
    url = f"{API}/{created['id']}"
    params = {"agent_key": "chat", "scope_type": "chapter", "scope_id": str(chapter.id)}
    # foreign user: indistinguishable from missing
    assert client.get(url, params=params, headers=_headers(client, stranger)).status_code == 404
    # superuser keeps the legacy chat exception
    assert client.get(url, params=params, headers=superuser_token_headers).status_code == 200


def test_outline_sessions_stay_owner_only_even_for_superuser(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    teacher = _create_user(db, role="teacher")
    course = _make_course_with_chapter(db, _uid(db, teacher))

    created = _create_session(
        client,
        _headers(client, teacher),
        agent_key="outline",
        scope_type="course",
        scope_id=str(course.id),
    )
    # superuser may own courses but has no entrance into a teacher's outline
    # history (维持现状, §5)
    r = client.get(
        f"{API}/{created['id']}",
        params={"agent_key": "outline", "scope_type": "course", "scope_id": str(course.id)},
        headers=superuser_token_headers,
    )
    assert r.status_code == 404


def test_chat_scope_access_requires_enrollment(
    client: TestClient, db: Session
) -> None:
    teacher = _create_user(db, role="teacher")
    student = _create_user(db)
    course = _make_course_with_chapter(db, _uid(db, teacher))
    chapter: Chapter = course.chapters[0]  # type: ignore[index]

    # not enrolled → creating a chapter-scope chat session is 403
    r = client.post(
        API,
        json={"agent_key": "chat", "scope": {"type": "chapter", "id": str(chapter.id)}},
        headers=_headers(client, student),
    )
    assert r.status_code == 403
    # enrolled → allowed
    db.add(Enrollment(course_id=course.id, student_id=_uid(db, student)))
    db.commit()
    r = client.post(
        API,
        json={"agent_key": "chat", "scope": {"type": "chapter", "id": str(chapter.id)}},
        headers=_headers(client, student),
    )
    assert r.status_code == 201


# ----- Idempotent creation (acceptance #6, §7.1) -----


def test_idempotency_key_returns_same_session(
    client: TestClient, db: Session
) -> None:
    teacher = _create_user(db, role="teacher")
    headers = _headers(client, teacher)
    course = _make_course_with_chapter(db, _uid(db, teacher))

    a = _create_session(
        client,
        headers,
        agent_key="outline",
        scope_type="course",
        scope_id=str(course.id),
        idempotency_key="intent-1",
    )
    b = _create_session(
        client,
        headers,
        agent_key="outline",
        scope_type="course",
        scope_id=str(course.id),
        idempotency_key="intent-1",
    )
    assert a["id"] == b["id"]
    # a new intent creates a new session
    c = _create_session(
        client,
        headers,
        agent_key="outline",
        scope_type="course",
        scope_id=str(course.id),
        idempotency_key="intent-2",
    )
    assert c["id"] != a["id"]


# ----- Run lease (acceptance #7, §7.2 / §12.4) -----


def _hold_lease(db: Session, session_id: str, *, seconds: int = 300) -> None:
    row = db.get(AgentSession, uuid.UUID(session_id))
    row.run_token = "held-by-other"
    row.run_expires_at = get_datetime_utc() + timedelta(seconds=seconds)
    db.add(row)
    db.commit()


def test_busy_session_returns_409_until_lease_expires(
    client: TestClient, db: Session, monkeypatch: Any
) -> None:
    teacher = _create_user(db, role="teacher")
    headers = _headers(client, teacher)
    course = _make_course_with_chapter(db, _uid(db, teacher))
    created = _create_session(
        client, headers, agent_key="outline", scope_type="course", scope_id=str(course.id)
    )

    _hold_lease(db, created["id"])
    r = client.post(
        f"{API}/{created['id']}/messages",
        json={
            "agent_key": "outline",
            "scope_type": "course",
            "scope_id": str(course.id),
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers=headers,
    )
    assert r.status_code == 409
    assert "正在回复" in r.json()["detail"]

    # expired lease is reclaimable
    row = db.get(AgentSession, uuid.UUID(created["id"]))
    row.run_expires_at = get_datetime_utc() - timedelta(seconds=1)
    db.add(row)
    db.commit()

    async def fake_response(*_a: Any, **_k: Any) -> list[HistoryMessage]:
        return [HistoryMessage(role="assistant", content="ok")]

    _stub(monkeypatch, outline_agent, "get_response", fake_response)
    r = client.post(
        f"{API}/{created['id']}/messages",
        json={
            "agent_key": "outline",
            "scope_type": "course",
            "scope_id": str(course.id),
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text


def test_delete_busy_session_returns_409(client: TestClient, db: Session) -> None:
    teacher = _create_user(db, role="teacher")
    headers = _headers(client, teacher)
    course = _make_course_with_chapter(db, _uid(db, teacher))
    created = _create_session(
        client, headers, agent_key="outline", scope_type="course", scope_id=str(course.id)
    )
    _hold_lease(db, created["id"])
    r = client.delete(
        f"{API}/{created['id']}",
        params={"agent_key": "outline", "scope_type": "course", "scope_id": str(course.id)},
        headers=headers,
    )
    assert r.status_code == 409


# ----- Send contract: context, auto-title, thread identity -----


def test_outline_send_uses_stored_thread_and_course_context(
    client: TestClient, db: Session, monkeypatch: Any
) -> None:
    teacher = _create_user(db, role="teacher")
    headers = _headers(client, teacher)
    course = _make_course_with_chapter(db, _uid(db, teacher))
    created = _create_session(
        client, headers, agent_key="outline", scope_type="course", scope_id=str(course.id)
    )
    row = db.get(AgentSession, uuid.UUID(created["id"]))

    captured: dict[str, Any] = {}

    async def fake_response(messages: Any, thread_id: str, **kwargs: Any) -> list[HistoryMessage]:
        captured["messages"] = messages
        captured["thread_id"] = thread_id
        captured.update(kwargs)
        return [HistoryMessage(role="assistant", content="大纲 v1")]

    _stub(monkeypatch, outline_agent, "get_response", fake_response)

    r = client.post(
        f"{API}/{created['id']}/messages",
        json={
            "agent_key": "outline",
            "scope_type": "course",
            "scope_id": str(course.id),
            "messages": [{"role": "user", "content": "帮我生成大纲"}],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    # the executor got the stored thread id, not the session id / a client value
    assert captured["thread_id"] == row.thread_id
    assert captured["thread_id"].startswith("sess:")
    assert "课程标题：线性代数" in captured["course_context"]
    # auto-title from the first user message (§12.6)
    db.refresh(row)
    assert row.title == "帮我生成大纲"


def test_stream_frames_and_release(client: TestClient, db: Session, monkeypatch: Any) -> None:
    teacher = _create_user(db, role="teacher")
    headers = _headers(client, teacher)
    course = _make_course_with_chapter(db, _uid(db, teacher))
    created = _create_session(
        client, headers, agent_key="outline", scope_type="course", scope_id=str(course.id)
    )
    row = db.get(AgentSession, uuid.UUID(created["id"]))

    async def fake_stream(*_a: Any, **_k: Any) -> AsyncGenerator[str]:
        yield "第一单元"
        yield "：行列式"

    _stub(monkeypatch, outline_agent, "get_stream_response", fake_stream)

    with client.stream(
        "POST",
        f"{API}/{created['id']}/messages/stream",
        json={
            "agent_key": "outline",
            "scope_type": "course",
            "scope_id": str(course.id),
            "messages": [{"role": "user", "content": "生成大纲"}],
        },
        headers=headers,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        frames = [
            json.loads(line.removeprefix("data: "))
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]
    assert frames[0] == {"content": "第一单元", "done": False}
    assert frames[-1] == {"content": "", "done": True}
    # lease released after the stream finished
    db.refresh(row)
    assert row.run_token is None
    # auto-title landed
    assert row.title == "生成大纲"


# ----- Legacy outline import (acceptance #9, §8.2) -----


def test_import_hints_binds_verifiable_threads_only(
    client: TestClient, db: Session, monkeypatch: Any
) -> None:
    teacher = _create_user(db, role="teacher")
    headers = _headers(client, teacher)
    stranger = _create_user(db, role="teacher")
    owned = _make_course_with_chapter(db, _uid(db, teacher))
    other_owned = _make_course_with_chapter(db, _uid(db, teacher))
    foreign = _make_course_with_chapter(db, _uid(db, stranger))

    good, empty, foreign_uuid, ambiguous = (uuid.uuid4() for _ in range(4))
    teacher_id = _uid(db, teacher)

    async def fake_has(thread_id: str) -> bool:
        # only the "good" thread has checkpoint rows
        return thread_id == f"outline:{teacher_id}:{good}"

    async def fake_history(thread_id: str) -> list[HistoryMessage]:
        assert thread_id == f"outline:{teacher_id}:{good}"
        return [
            HistoryMessage(role="user", content="给线性代数课程出一份 48 学时大纲"),
            HistoryMessage(role="assistant", content="……"),
        ]

    _stub(monkeypatch, outline_agent, "thread_has_history", fake_has)
    _stub(monkeypatch, outline_agent, "get_chat_history", fake_history)

    r = client.post(
        f"{API}/outline/import-hints",
        json={
            "hints": [
                {"course_id": str(owned.id), "thread_uuid": str(good)},
                {"course_id": str(owned.id), "thread_uuid": str(empty)},
                {"course_id": str(foreign.id), "thread_uuid": str(foreign_uuid)},
                {"course_id": str(owned.id), "thread_uuid": str(ambiguous)},
                {"course_id": str(other_owned.id), "thread_uuid": str(ambiguous)},
            ]
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"imported": 1, "skipped": 4}

    # the imported row keeps its legacy thread id and gains a real title
    imported = db.exec(
        select(AgentSession).where(
            AgentSession.thread_id == f"outline:{teacher_id}:{good}"
        )
    ).first()
    assert imported is not None
    assert imported.scope_type == "course"
    assert imported.scope_id == str(owned.id)
    assert imported.title == "给线性代数课程出一份 48 学时大纲"

    # re-reporting the same uuid is a no-op skip
    r = client.post(
        f"{API}/outline/import-hints",
        json={"hints": [{"course_id": str(owned.id), "thread_uuid": str(good)}]},
        headers=headers,
    )
    assert r.json() == {"imported": 0, "skipped": 1}


# ----- Purge hooks (acceptance #10, §12.11) -----


def test_chapter_delete_purges_sessions_and_checkpoints(
    client: TestClient, db: Session, monkeypatch: Any
) -> None:
    teacher = _create_user(db, role="teacher")
    headers = _headers(client, teacher)
    course = _make_course_with_chapter(db, _uid(db, teacher))
    chapter: Chapter = course.chapters[0]  # type: ignore[index]
    student = _create_user(db)
    db.add(Enrollment(course_id=course.id, student_id=_uid(db, student)))
    db.commit()

    created = _create_session(
        client,
        _headers(client, student),
        agent_key="chat",
        scope_type="chapter",
        scope_id=str(chapter.id),
    )
    row = db.get(AgentSession, uuid.UUID(created["id"]))
    thread_id = row.thread_id
    row_id = row.id

    cleared: list[str] = []

    async def fake_clear(thread_id: str) -> None:
        cleared.append(thread_id)

    _stub(monkeypatch, langgraph_agent, "clear_chat_history", fake_clear)

    r = client.delete(
        f"/api/v1/courses/chapters/{chapter.id}", headers=headers
    )
    assert r.status_code == 200, r.text
    assert cleared == [thread_id]
    # expire the identity-map copy: the delete happened in the route's session
    db.expire_all()
    assert db.get(AgentSession, row_id) is None


def test_send_refuses_incompatible_state_version(
    client: TestClient, db: Session
) -> None:
    teacher = _create_user(db, role="teacher")
    headers = _headers(client, teacher)
    course = _make_course_with_chapter(db, _uid(db, teacher))
    created = _create_session(
        client, headers, agent_key="outline", scope_type="course", scope_id=str(course.id)
    )
    # simulate a session written by a future graph version
    row = db.get(AgentSession, uuid.UUID(created["id"]))
    row.state_version = 99
    db.add(row)
    db.commit()

    r = client.post(
        f"{API}/{created['id']}/messages",
        json={
            "agent_key": "outline",
            "scope_type": "course",
            "scope_id": str(course.id),
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers=headers,
    )
    assert r.status_code == 409
    assert "版本不兼容" in r.json()["detail"]
    # history reads stay allowed (retention is separate from the run gate)
    r = client.get(
        f"{API}/{created['id']}/messages",
        params={"agent_key": "outline", "scope_type": "course", "scope_id": str(course.id)},
        headers=headers,
    )
    assert r.status_code == 200
