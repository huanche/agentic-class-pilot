"""Real browser BFF -> student ASGI boundary, with only storage/remote content replaced."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import asyncio
import json
import os
import sys
import uuid

import pytest
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "platform/backend"), str(ROOT / "student_agent")]
for name, value in {"PROJECT_NAME": "cookie-boundary-test", "SECRET_KEY": "synthetic-csrf-secret",
    "DATABASE_URL": "postgresql://test:test@127.0.0.1:1/unused_test",
    "FIRST_SUPERUSER": "test@example.com", "FIRST_SUPERUSER_PASSWORD": "synthetic-password"}.items():
    os.environ.setdefault(name, value)

from app.services import browser_learning_auth as auth
from app.services import student_learning_gateway as gateway
from app.api.routes.student_learning import router
from app.core.config import settings
from backend import main as student
from backend.infrastructure import commands, platform_access, persistence
from backend.infrastructure.platform_identity import current_identity
from backend.session import service

USER = uuid.UUID(int=1)
OTHER = uuid.UUID(int=2)
COURSE = uuid.UUID(int=3)


@pytest.fixture
def system(monkeypatch):
    monkeypatch.setenv("PLATFORM_TO_STUDENT_KEY", "synthetic-channel-key")
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "synthetic-reverse-key")
    monkeypatch.setattr(settings, "PLATFORM_TO_STUDENT_KEY", "synthetic-channel-key")
    monkeypatch.setattr(settings, "FRONTEND_HOST", "https://class.test")
    monkeypatch.setattr(settings, "BROWSER_ALLOWED_ORIGINS", "")
    monkeypatch.setattr(service, "sessions", {})
    state = {"active": True, "allowed": True, "user": USER, "role": "student", "account_active": True}

    class DB:
        def __init__(self, *_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def execute(self, statement, params):
            if str(statement).startswith("DELETE"):
                state["active"] = False
            valid = state["active"] and params.get("token") == auth.digest("synthetic-cookie")
            return SimpleNamespace(first=lambda: (state["user"], datetime.now(UTC)+timedelta(hours=12)) if valid else None)
        def commit(self): pass
        def get(self, *_):
            return SimpleNamespace(id=state["user"], is_active=state["account_active"], role=state["role"], is_superuser=False)
    monkeypatch.setattr(auth, "Session", DB)
    access = []
    def course_access(user, course):
        access.append((user.user_id, course))
        if not state["allowed"]:
            raise auth.reject(403, "COURSE_ACCESS_DENIED", "已撤销选课")
    monkeypatch.setattr(gateway, "course_access", course_access)

    def context(credential, lesson_id=None, refresh_session=False):
        assert credential.user_id == str(state["user"])
        assert credential.course_id == str(COURSE)
        lesson = {"id": "lesson", "title": "课时", "classroom": {"id": "room", "playerUrl": "https://class.test/player", "scenes": []}}
        return {"userId": str(state["user"]), "courseId": str(COURSE), "courseTitle": "课程",
                "publication": {"id": "pub", "version": 1}, "selectedLessonId": lesson_id,
                "lessonCatalog": [lesson], "lessons": [lesson] if lesson_id else []}
    monkeypatch.setattr(platform_access, "platform_context", context)
    internal = TestClient(student.app)
    requests = []
    async def transport(request):
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, body))
        assert "cookie" not in request.headers and "authorization" not in request.headers
        assert request.headers["x-platform-learning-key"] == "synthetic-channel-key"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=student.app), base_url="http://student") as api:
            return await api.request(request.method, request.url.path, content=request.content, headers=request.headers)
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(transport), base_url="http://student")
    monkeypatch.setattr(gateway, "_client", upstream)
    app = FastAPI()
    app.include_router(router)
    from app.api.routes.login import router as login_router
    from app.api.deps import get_db
    app.include_router(login_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: DB()
    @app.exception_handler(HTTPException)
    async def error(_request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail},
                            status_code=exc.status_code, headers={"Cache-Control": "no-store"})
    client = TestClient(app, base_url="https://class.test")
    client.cookies.set("agentedu_session", "synthetic-cookie")
    headers = {"Origin": "https://class.test", "X-CSRF-Token": auth.csrf_value("synthetic-cookie")}
    yield client, headers, state, internal, requests, access
    asyncio.run(upstream.aclose())


def test_cookie_course_entry_works_without_any_launch_token(system):
    client, headers, _, _, requests, _ = system
    identity = client.get("/api/session/identity")
    assert identity.status_code == 200 and identity.headers["cache-control"] == "no-store"
    response = client.post("/api/session/start", headers=headers, json={"course_id": str(COURSE)})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["phase"] == "idle" and data["userId"] == str(USER)
    assert "launch_token" not in str(requests)
    assert service.sessions[data["sessionId"]]["launchToken"] is None


@pytest.mark.parametrize("credential", ["bearer", "launch", "playback"])
def test_browser_credentials_cannot_replace_cookie(system, credential):
    client, headers, *_ = system
    client.cookies.clear()
    response = client.post("/api/session/start", headers=headers | {"Authorization": "Bearer old-jwt"},
                           json={"course_id": str(COURSE), "launch_token": credential})
    assert response.status_code == 401


def test_expiration_and_revocation_do_not_reset_progress(system):
    client, headers, state, _, requests, _ = system
    response = client.post("/api/session/start", headers=headers, json={"course_id": str(COURSE)})
    sid = response.json()["sessionId"]
    state["active"] = False
    assert client.get(f"/api/session/{sid}").status_code == 401
    assert service.sessions[sid]["phase"] == "idle"
    state["active"] = True
    state["allowed"] = False
    denied = client.get(f"/api/session/{sid}")
    assert denied.status_code == 403
    assert requests[-1][1].endswith("/scope")  # No business request after the permission rejection.


@pytest.mark.parametrize("override", [{"X-CSRF-Token": "wrong"}, {"Origin": "https://evil.test"}])
def test_csrf_or_origin_failure_never_reaches_student(system, override):
    client, headers, _, _, requests, _ = system
    response = client.post("/api/session/start", headers=headers | override, json={"course_id": str(COURSE)})
    assert response.status_code == 403 and requests == []


def test_other_account_cannot_resolve_cached_catalog(system):
    client, headers, state, *_ = system
    sid = client.post("/api/session/start", headers=headers, json={"course_id": str(COURSE)}).json()["sessionId"]
    state["user"] = OTHER
    assert client.get(f"/api/session/{sid}").status_code == 404


def test_service_rejects_direct_browser_and_forged_identity(system):
    _, _, _, internal, *_ = system
    response = internal.post("/api/session/start", headers={"X-Platform-User-Id": str(USER)},
                             json={"course_id": str(COURSE)})
    assert response.status_code == 403
    assert current_identity.get() is None


def test_legacy_browser_routes_and_token_payload_are_rejected(system):
    client, headers, _, _, requests, _ = system
    assert client.post("/api/session/s/message", headers=headers, json={"text": "x"}).status_code == 410
    assert client.post("/api/session/browser-restore", headers=headers, json={"snapshot": "old"}).status_code == 410
    assert client.post("/api/session/start", headers=headers,
                       json={"launch_token": "old", "course_id": str(COURSE)}).status_code == 426
    assert requests == []


def test_scope_tombstone_stays_queryable_for_reset_receipt(system, monkeypatch):
    client, headers, _, _, _, _ = system
    record = {"user_id": str(USER), "course_id": str(COURSE), "lesson_id": "lesson", "classroom_id": "room",
              "publication_id": "pub", "publication_version": 1, "revoked_at": datetime.now(UTC)}
    monkeypatch.setattr(commands, "scope", lambda _: record)
    monkeypatch.setattr(student.command_runtime, "status", lambda *a: {"commandId": "reset", "status": "completed",
        "sessionView": {"sessionId": "new", "phase": "idle"}})
    response = client.post("/api/session/old/commands/reset/status", headers=headers, json={})
    assert response.status_code == 200
    assert response.json()["sessionView"]["sessionId"] == "new"


def test_failed_history_is_not_first_time_learning(system, monkeypatch):
    client, headers, *_ = system
    monkeypatch.setattr(persistence, "latest_session_key", lambda *a: None)
    missing = client.post("/api/session/resume", headers=headers,
                          json={"course_id": str(COURSE), "lesson_id": "lesson"})
    assert missing.status_code == 404 and missing.json()["code"] == "HISTORY_NOT_FOUND"
    def unavailable(*_): raise RuntimeError("synthetic database outage")
    monkeypatch.setattr(persistence, "latest_session_key", unavailable)
    assert client.post("/api/session/resume", headers=headers,
        json={"course_id": str(COURSE), "lesson_id": "lesson"}).status_code == 503


def test_readiness_projection_does_not_write(system, monkeypatch):
    sample = {"id": "s", "context": {"courseId": str(COURSE)}, "phase": "video", "lessonId": "lesson",
              "videoRevision": "rev", "messages": [], "courses": [], "dialogue": None, "preparation": "pending"}
    monkeypatch.setattr(service.published_knowledge, "read", lambda *a: {"status": "ready", "points": [
        {"id": "p", "title": "概念", "content": "解释"}], "coverage": {}})
    monkeypatch.setattr(service.lesson_content, "bind", lambda *a: {"contentRef": {}, "lessonContent": {}})
    monkeypatch.setattr(service, "commit", lambda *a: pytest.fail("GET projection must not commit"))
    service.sync_published_preparation(sample, persist=False)
    assert sample["preparation"] == "ready" and sample["dialogue"]


def test_shared_logout_works_for_teachers_and_revokes_subsequent_requests(system):
    client, headers, state, *_ = system
    state["role"] = "teacher"
    assert client.get("/api/v1/login/session").status_code == 200
    assert client.get("/api/session/identity").status_code == 403
    assert client.post("/api/v1/logout", headers=headers).status_code == 200
    assert client.get("/api/v1/login/session").status_code == 401


def test_wrong_cookie_and_disabled_account_are_rejected(system):
    client, _, state, *_ = system
    client.cookies.set("agentedu_session", "not-a-valid-session")
    assert client.get("/api/session/identity").status_code == 401
    client.cookies.set("agentedu_session", "synthetic-cookie")
    state["account_active"] = False
    assert client.get("/api/session/identity").status_code == 403


def test_login_database_failure_is_explicit_and_never_reaches_student(system, monkeypatch):
    client, _, _, _, requests, _ = system
    def broken_db(*_): raise RuntimeError("synthetic unavailable database")
    monkeypatch.setattr(auth, "Session", broken_db)
    response = client.get("/api/session/identity")
    assert response.status_code == 503
    assert "synthetic unavailable" not in response.text and requests == []


def test_explicit_loopback_demo_is_separate_from_platform_mode(system, monkeypatch):
    monkeypatch.delenv("PLATFORM_TO_STUDENT_KEY", raising=False)
    monkeypatch.delenv("PLATFORM_AUTH_URL", raising=False)
    monkeypatch.setenv("STUDENT_DEMO_MODE", "true")
    monkeypatch.setenv("STUDENT_NEW_DEMO_PLAYER_URL", "http://127.0.0.1/demo-player")
    local = TestClient(student.app, base_url="http://127.0.0.1")
    assert local.get("/api/session/identity").json()["demoEnabled"] is True
    assert local.post("/api/session/start", json={}).status_code == 200
    remote = TestClient(student.app, base_url="https://class.test")
    assert remote.post("/api/session/start", json={}).status_code == 503


def test_concurrent_internal_requests_keep_identity_separate(system, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    def context(actor, *_args, **_kwargs):
        return {"userId": actor.user_id, "courseId": actor.course_id, "publication": {"id": "pub", "version": 1},
                "lessons": [], "lessonCatalog": []}
    monkeypatch.setattr(platform_access, "platform_context", context)
    # Avoid lifespan workers in this boundary-only test; each TestClient request has its own portal.
    def request(user):
        client = TestClient(student.app)
        response = client.post("/api/session/start", json={"course_id": str(COURSE)}, headers={
            "X-Platform-Learning-Key": "synthetic-channel-key", "X-Platform-Protocol": "platform-cookie-v1",
            "X-Platform-User-Id": str(user), "X-Platform-Course-Id": str(COURSE)})
        assert response.status_code == 200, response.text
        return response.json()["userId"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(request, [USER, OTHER])) == [str(USER), str(OTHER)]
    assert current_identity.get() is None


def test_async_forward_keeps_platform_callbacks_available_with_one_worker(system, monkeypatch):
    client, headers, *_ = system
    async def exercise():
        import anyio
        limiter = anyio.to_thread.current_default_thread_limiter()
        original = limiter.total_tokens
        limiter.total_tokens = 1
        transport = httpx.ASGITransport(app=client.app)
        async def student_callback(request):
            # A student context callback needs the same platform worker pool as browser auth.
            async with httpx.AsyncClient(transport=transport, base_url="https://class.test",
                    cookies={"agentedu_session": "synthetic-cookie"}) as callback:
                response = await callback.get("/api/v1/login/session")
                assert response.status_code == 200
            assert request.headers["x-platform-user-id"] == str(USER)
            return httpx.Response(200, json={"phase": "idle", "userId": str(USER)})
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(student_callback), base_url="http://student") as upstream:
                monkeypatch.setattr(gateway, "_client", upstream)
                async with httpx.AsyncClient(transport=transport, base_url="https://class.test",
                        cookies={"agentedu_session": "synthetic-cookie"}) as browser:
                    responses = await asyncio.wait_for(asyncio.gather(*[
                        browser.post("/api/session/start", headers=headers | {"X-Platform-User-Id": str(OTHER)},
                                     json={"course_id": str(COURSE)}) for _ in range(8)]), timeout=5)
                    assert all(response.status_code == 200 for response in responses)
        finally:
            limiter.total_tokens = original
    asyncio.run(exercise())
