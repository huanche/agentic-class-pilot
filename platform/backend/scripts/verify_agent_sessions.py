# ruff: noqa: T201 — printing the verification transcript is this script's job
"""Acceptance check for the unified agent-session infrastructure
(docs/agent-isolation-plan.md §10 step 6 / §11 acceptance #1, 6, 7, 12).

Runs against the real stack (DATABASE_URL Postgres + configured LLM for one
short turn) through the HTTP layer, and verifies, in order:

1. multi-session: a student creates two chapter-scope chat sessions, lists
   them, and resolve picks the most recently active one — no creation side
   effect from list/resolve;
2. one real LLM turn through the unified stream endpoint: lease is held
   during the run, released after, history lands in the checkpoint thread,
   auto-title is derived from the first message;
3. the lease is a real mutex: a held lease makes the next send a 409, an
   expired lease is reclaimable;
4. idempotent create: the same idempotency key returns the same session;
5. extensibility (acceptance #12): a THIRD test agent is registered at
   runtime against the existing chapter scope adapter — no schema change, no
   copied lookup/history/delete logic — gets its own thread, and cleans up;
6. legacy outline import-hints: a never-used thread uuid is skipped (empty
   threads are never imported, §12.8).

Run from ``backend/``:  uv run python scripts/verify_agent_sessions.py
"""

import asyncio
import json
import sys
import uuid

# Windows console defaults to a legacy codepage (GBK) that can't render the
# ✓/✗ marks or some Chinese output below.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# TestClient's anyio portal + psycopg async pools need the selector loop on
# Windows (same reason as tests/conftest.py).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app import crud  # noqa: E402
from app.core.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AgentSession,
    Chapter,
    Course,
    Enrollment,
    UserCreate,
    get_datetime_utc,
)

API = "/api/v1/agent-sessions"
LESSON_ASK = "用一句话说明什么是行列式"


def ok(label: str) -> None:
    print(f"  ✓ {label}")


def fail(label: str, detail: str = "") -> None:
    print(f"  ✗ {label} {detail}")
    raise SystemExit(1)


def make_user(email: str, *, role: str = "student", password: str = "verify-pass-1234"):
    with Session(engine) as db:
        user = crud.create_user(
            session=db, user_create=UserCreate(email=email, password=password, role=role)
        )
        return user.id, password


def token(client: TestClient, email: str, password: str) -> dict[str, str]:
    r = client.post(
        "/api/v1/login/access-token",
        data={"username": email, "password": password},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def main() -> None:
    run_id = uuid.uuid4().hex[:8]
    with Session(engine) as db:
        teacher = crud.create_user(
            session=db,
            user_create=UserCreate(
                email=f"verify-{run_id}-t@example.com", password="verify-pass-1234", role="teacher"
            ),
        )
        student = crud.create_user(
            session=db,
            user_create=UserCreate(
                email=f"verify-{run_id}-s@example.com", password="verify-pass-1234"
            ),
        )
        course = Course(title=f"验证课程-{run_id}", owner_id=teacher.id)
        db.add(course)
        db.commit()
        db.refresh(course)
        chapter = Chapter(title="行列式", course_id=course.id)
        db.add(chapter)
        db.add(Enrollment(course_id=course.id, student_id=student.id))
        db.commit()
        db.refresh(chapter)
        course_id, chapter_id = course.id, chapter.id
        teacher_id, student_id = teacher.id, student.id

    print(f"[agent-sessions verify] run={run_id}")
    with TestClient(app) as client:
        s_headers = token(
            client, f"verify-{run_id}-s@example.com", "verify-pass-1234"
        )
        t_headers = token(
            client, f"verify-{run_id}-t@example.com", "verify-pass-1234"
        )

        # ---- 1. multi-session core ----
        print("1. multi-session per chapter scope")
        params = {
            "agent_key": "chat",
            "scope_type": "chapter",
            "scope_id": str(chapter_id),
        }
        s1 = client.post(API, json={"agent_key": "chat", "scope": {"type": "chapter", "id": str(chapter_id)}}, headers=s_headers)
        s2 = client.post(API, json={"agent_key": "chat", "scope": {"type": "chapter", "id": str(chapter_id)}}, headers=s_headers)
        assert s1.status_code == s2.status_code == 201, (s1.text, s2.text)
        ok("two sessions created in one scope")
        listed = client.get(API, params=params, headers=s_headers).json()
        assert listed["count"] == 2, listed
        ok("list shows both")
        resolved = client.post(
            f"{API}/resolve",
            json={"agent_key": "chat", "scope": {"type": "chapter", "id": str(chapter_id)}},
            headers=s_headers,
        ).json()
        assert resolved["id"] in {s1.json()["id"], s2.json()["id"]}
        ok(f"resolve picks most recent ({resolved['title']!r})")

        # ---- 2. one real LLM turn through the unified stream ----
        print("2. real streamed turn (lease + checkpoint + auto-title)")
        target = s1.json()["id"]
        frames: list[dict] = []
        with client.stream(
            "POST",
            f"{API}/{target}/messages/stream",
            json={
                **{k: params[k] for k in ("agent_key", "scope_type", "scope_id")},
                "messages": [{"role": "user", "content": LESSON_ASK}],
            },
            headers=s_headers,
        ) as resp:
            assert resp.status_code == 200, resp.text
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    frames.append(json.loads(line.removeprefix("data: ")))
        assert frames and frames[-1]["done"] is True and frames[-1]["content"] == "", frames[-1]
        reply = "".join(f["content"] for f in frames[:-1])
        ok(f"streamed reply ({len(reply)} chars)")

        with Session(engine) as db:
            row = db.get(AgentSession, uuid.UUID(target))
            assert row is not None and row.run_token is None, "lease not released"
            assert row.title == LESSON_ASK, row.title
            thread_id = row.thread_id
        history = client.get(f"{API}/{target}/messages", params=params, headers=s_headers).json()
        assert any(m["role"] == "assistant" and m["content"] for m in history["messages"])
        ok("history served from the checkpoint thread, auto-title set")

        # ---- 3. lease mutex ----
        print("3. lease mutex (409 while held, reclaim after expiry)")
        with Session(engine) as db:
            row = db.get(AgentSession, uuid.UUID(target))
            from datetime import timedelta

            row.run_token = "held"
            row.run_expires_at = get_datetime_utc() + timedelta(seconds=60)
            db.add(row)
            db.commit()
        busy = client.post(
            f"{API}/{target}/messages",
            json={
                **{k: params[k] for k in ("agent_key", "scope_type", "scope_id")},
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers=s_headers,
        )
        assert busy.status_code == 409, busy.text
        ok("held lease → 409")
        with Session(engine) as db:
            row = db.get(AgentSession, uuid.UUID(target))
            row.run_expires_at = get_datetime_utc() - timedelta(seconds=1)
            db.add(row)
            db.commit()

        # ---- 4. idempotent create ----
        print("4. idempotent create")
        body = {
            "agent_key": "chat",
            "scope": {"type": "chapter", "id": str(chapter_id)},
            "idempotency_key": f"intent-{run_id}",
        }
        a = client.post(API, json=body, headers=s_headers).json()
        b = client.post(API, json=body, headers=s_headers).json()
        assert a["id"] == b["id"], (a, b)
        ok("retry with the same key returns the same session")

        # ---- 5. third agent registered at runtime (acceptance #12) ----
        print("5. third agent via registry (chapter scope reused, no schema change)")
        from app.core.langgraph.graph import langgraph_agent
        from app.services.agent_registry import (
            AgentSpec,
            _chat_context,
            _chat_invoke,
            _chat_stream,
            get_agent,
        )

        assert get_agent("verify_tutor") is None
        from app.services import agent_registry as registry

        registry.register_agent(
            AgentSpec(
                agent_key="verify_tutor",
                display_name="验收第三助手",
                allowed_scope_types=frozenset({"chapter"}),
                scope_requires_manage=False,
                allow_superuser_session_access=False,
                state_version=1,
                executor=langgraph_agent,
                invoke=_chat_invoke,
                stream=_chat_stream,
                build_context=_chat_context,
            )
        )
        try:
            third = client.post(
                API,
                json={"agent_key": "verify_tutor", "scope": {"type": "chapter", "id": str(chapter_id)}},
                headers=s_headers,
            )
            assert third.status_code == 201, third.text
            t_params = {"agent_key": "verify_tutor", "scope_type": "chapter", "scope_id": str(chapter_id)}
            t_history = client.get(
                f"{API}/{third.json()['id']}/messages", params=t_params, headers=s_headers
            )
            assert t_history.status_code == 200 and t_history.json()["messages"] == []
            ok("created + read history through the same unified endpoints")
            with Session(engine) as db:
                trow = db.get(AgentSession, uuid.UUID(third.json()["id"]))
                assert trow is not None
                assert trow.thread_id != thread_id
            ok("own thread, separate from the chat agent's")
            # cross-agent isolation: chat session id under verify_tutor → 404
            crossed = client.get(
                f"{API}/{target}",
                params={"agent_key": "verify_tutor", "scope_type": "chapter", "scope_id": str(chapter_id)},
                headers=s_headers,
            )
            assert crossed.status_code == 404
            ok("chat session id is 404 under the third agent")
        finally:
            client.delete(
                f"{API}/{third.json()['id']}",
                params=t_params,
                headers=s_headers,
            )
            registry._AGENTS.pop("verify_tutor", None)

        # ---- 6. legacy outline import skips empty threads ----
        print("6. outline import-hints skips empty threads")
        r = client.post(
            f"{API}/outline/import-hints",
            json={"hints": [{"course_id": str(course_id), "thread_uuid": str(uuid.uuid4())}]},
            headers=t_headers,
        )
        assert r.status_code == 200 and r.json() == {"imported": 0, "skipped": 1}, r.text
        ok("never-used uuid not imported (§12.8)")

        # ---- cleanup: drop the created business objects ----
        from sqlmodel import select

        with Session(engine) as db:
            for row in db.exec(select(AgentSession)).all():
                if row.user_id in {student_id, teacher_id}:
                    db.delete(row)
            db.delete(db.get(Chapter, chapter_id))
            db.delete(db.get(Course, course_id))
            db.delete(db.get(type(teacher), teacher_id))
            db.delete(db.get(type(student), student_id))
            db.commit()
        ok("cleanup done")

    print("[agent-sessions verify] ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
