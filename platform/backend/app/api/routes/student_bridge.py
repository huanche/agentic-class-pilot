"""Student bridge: trusted entry into the independent student agent service.

Two surfaces:
- POST /api/v1/internal/student/authorize — the student agent validates each
  request (session cookie or launch token) against the platform.
- POST /api/v1/courses/{course_id}/student-workspace — an enrolled student of a
  published course receives a short-lived launch token plus the entry URL.
  Identity is carried inside the signed token; caller-supplied student ids are
  never trusted.
"""
import hashlib
import hmac
import json
import secrets
import base64
import time
import uuid
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import Enrollment
from app.services.browser_sessions import user_for_cookie
from app.services.course_access import get_accessible_course

router = APIRouter(tags=["student-bridge"])


def check_student_service_key(value: str | None) -> None:
    if not settings.STUDENT_SERVICE_KEY or not hmac.compare_digest(value or "", settings.STUDENT_SERVICE_KEY):
        raise HTTPException(403, "Invalid service credentials")


# --- launch tokens: HMAC-signed, self-contained, short-lived -----------------

def _launch_signature(payload_json: str) -> str:
    key = (settings.STUDENT_SERVICE_KEY or "").encode()
    return hmac.new(key, payload_json.encode(), hashlib.sha256).hexdigest()


def issue_launch_token(user_id: uuid.UUID, course_id: uuid.UUID, classroom_id: str,
                       publication: dict) -> str:
    payload = {
        "uid": str(user_id),
        "cid": str(course_id),
        "rid": classroom_id,
        "pub": publication,
        "exp": int(time.time()) + settings.STUDENT_LAUNCH_TOKEN_TTL_SECONDS,
        "nonce": secrets.token_urlsafe(12),
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    encoded = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    return f"{encoded}.{_launch_signature(payload_json)}"


def verify_launch_token(token: str) -> dict:
    """Validate signature and expiry; raise 401 on any mismatch."""
    encoded, _, signature = token.partition(".")
    if not signature:
        raise HTTPException(401, "Invalid launch token")
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        payload_json = base64.urlsafe_b64decode(padded).decode()
        payload = json.loads(payload_json)
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(401, "Invalid launch token") from error
    if not hmac.compare_digest(signature, _launch_signature(payload_json)):
        raise HTTPException(401, "Invalid launch token")
    if int(payload.get("exp", 0)) < time.time():
        raise HTTPException(401, "Launch token expired")
    return payload


# --- published-content resolution (read-only cross-schema queries) ------------

def _latest_publication(session: SessionDep, course_id: uuid.UUID) -> dict | None:
    row = session.execute(
        text("SELECT p.payload->>'version', p.payload->>'id' FROM teacher.mentra_knowledge_packages p "
             "JOIN teacher_course_link l ON l.external_course_id = p.course_id "
             "WHERE l.course_id=:id AND p.status='published' ORDER BY p.version DESC LIMIT 1"),
        {"id": course_id}).first()
    if not row:
        return None
    return {"publicationId": row[1], "version": int(row[0])}


def _published_classroom(session: SessionDep, course_id: uuid.UUID) -> str | None:
    row = session.execute(
        text("SELECT c.id FROM teacher.mentra_classrooms c "
             "JOIN teacher.mentra_course_artifacts a ON a.payload->>'classroomId' = c.id "
             "JOIN teacher_course_link l ON l.external_course_id = a.course_id "
             "WHERE l.course_id=:id AND a.payload->>'classPublicationId' IS NOT NULL "
             "ORDER BY (a.payload->>'classPublishedAt')::bigint DESC NULLS LAST LIMIT 1"),
        {"id": course_id}).first()
    return row[0] if row else None


def is_published_classroom(session: SessionDep, course_id: uuid.UUID,
                           classroom_id: str) -> bool:
    """Return whether a classroom is any published lesson of the course."""
    row = session.execute(
        text("SELECT 1 FROM teacher.mentra_course_artifacts a "
             "JOIN teacher_course_link l ON l.external_course_id = a.course_id "
             "WHERE l.course_id=:course AND a.payload->>'classroomId'=:classroom "
             "AND a.payload->>'classPublicationId' IS NOT NULL LIMIT 1"),
        {"course": course_id, "classroom": classroom_id}).first()
    return row is not None


class StudentAuthorization(BaseModel):
    cookie: str | None = None
    launch_token: str | None = None
    course_id: uuid.UUID | None = None
    classroom_id: str | None = None


def _resolve_launch_context(session: SessionDep, payload: dict) -> None:
    """Re-check enrollment + publication for a launch token at authorize time."""
    course_id = payload.get("cid")
    user_id = payload.get("uid")
    enrolled = session.execute(
        text("SELECT 1 FROM enrollment WHERE course_id=:c AND student_id=:u"),
        {"c": course_id, "u": user_id}).first()
    if not enrolled:
        raise HTTPException(403, "Launch token no longer matches an active enrollment")


@router.post("/internal/student/authorize")
def authorize_student_request(body: StudentAuthorization, session: SessionDep,
                              x_student_service_key: str | None = Header(default=None)):
    """Student-agent request validation: browser cookie or one-time launch context."""
    check_student_service_key(x_student_service_key)
    try:
        if body.launch_token:
            payload = verify_launch_token(body.launch_token)
            _resolve_launch_context(session, payload)
            return {"userId": payload["uid"], "courseId": payload["cid"],
                    "classroomId": payload.get("rid"), "publication": payload.get("pub"),
                    "source": "launch_token"}
        user = user_for_cookie(session, body.cookie)
        if user.role != "student" and not user.is_superuser:
            raise HTTPException(403, "Student role required")
        return {"userId": str(user.id), "source": "session"}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(503, "平台数据库暂不可用，请稍后重试") from error


@router.post("/courses/{course_id}/student-workspace")
def open_student_workspace(course_id: uuid.UUID, session: SessionDep, user: CurrentUser):
    """Trusted student entry: enrolled + published => short-lived launch URL."""
    if user.role == "teacher" and not user.is_superuser:
        raise HTTPException(403, "教师账号不能通过学生接口创建学习会话")
    get_accessible_course(session, user, course_id)
    if not user.is_superuser:
        enrolled = session.exec(
            select(Enrollment).where(
                Enrollment.course_id == course_id, Enrollment.student_id == user.id)
        ).first()
        if not enrolled:
            raise HTTPException(403, "尚未选课，无法进入学习")
    publication = _latest_publication(session, course_id)
    if not publication:
        raise HTTPException(409, "课程尚未发布，请等待教师发布后进入学习")
    # Classroom is optional: a published package alone supports text learning.
    # The player is an add-on; issue_launch_token tolerates classroom_id=None.
    classroom_id = _published_classroom(session, course_id)
    token = issue_launch_token(user.id, course_id, classroom_id or "none", publication)
    player_url = (f"{settings.TEACHER_PUBLIC_URL.rstrip('/')}/classroom-player/"
                  f"{quote(classroom_id)}") if classroom_id else None
    entry = f"{settings.STUDENT_PUBLIC_URL.rstrip('/')}/app?launch_token={quote(token)}"
    return {"url": entry, "playerUrl": player_url, "launchToken": token,
            "publication": publication, "classroomId": classroom_id}


# --- learning context (student agent data plane, schemaVersion 1) -------------

SCHEMA_VERSION = 1


class LearningContextRequest(BaseModel):
    launch_token: str


def _published_package_payload(session: SessionDep, course_id: uuid.UUID) -> dict | None:
    row = session.execute(
        text("SELECT p.payload FROM teacher.mentra_knowledge_packages p "
             "JOIN teacher_course_link l ON l.external_course_id = p.course_id "
             "WHERE l.course_id = :id AND p.status = 'published' "
             "ORDER BY p.version DESC LIMIT 1"),
        {"id": course_id}).first()
    return row[0] if row else None


def _classroom_view(session: SessionDep, classroom_id: str) -> dict:
    row = session.execute(
        text("SELECT stage, scenes FROM teacher.mentra_classrooms WHERE id = :id"),
        {"id": classroom_id}).first()
    if not row:
        raise HTTPException(404, "课堂不存在或尚未发布")
    scenes = []
    for scene in (row[1] or []):
        scenes.append({
            "id": scene.get("id"),
            "type": scene.get("type", "slide"),
            "order": int(scene.get("order") or 1),
            "title": scene.get("title", ""),
            # speech texts only: the student agent segments need narration;
            # canvas internals stay in the player's own data channel
            "actions": [
                {"id": action.get("id"), "type": action.get("type", "speech"),
                 "text": action.get("text")}
                for action in (scene.get("actions") or [])
                if isinstance(action, dict)
            ],
        })
    scenes.sort(key=lambda item: item["order"])
    return {
        "id": classroom_id,
        "title": (row[0] or {}).get("name", ""),
        "scenes": scenes,
        "playerUrl": f"{settings.TEACHER_PUBLIC_URL.rstrip('/')}/classroom-player/{classroom_id}",
    }


def _published_lessons(session: SessionDep, course_id: uuid.UUID,
                       user_id: uuid.UUID) -> list[dict]:
    """Return every published classroom for the course as a selectable lesson."""
    rows = session.execute(
        text("SELECT a.id, a.payload->>'title', a.payload->>'classroomId', "
             "a.payload->>'classPublishedAt' "
             "FROM teacher.mentra_course_artifacts a "
             "JOIN teacher_course_link l ON l.external_course_id = a.course_id "
             "WHERE l.course_id=:id "
             "AND a.payload->>'classPublicationId' IS NOT NULL "
             "AND a.payload->>'classroomId' IS NOT NULL "
             "ORDER BY (a.payload->>'classPublishedAt')::bigint ASC NULLS LAST, a.created_at ASC"),
        {"id": course_id}).all()
    lessons = []
    for order, row in enumerate(rows, start=1):
        classroom = _classroom_view(session, row[2])
        classroom["playbackToken"] = _issue_playback_grant(user_id, course_id, row[2])
        lessons.append({
            "id": f"lesson-{row[0]}",
            "title": row[1] or classroom["title"] or f"第 {order} 章",
            "order": order,
            "publishedAt": int(row[3]) if row[3] else None,
            "classroom": classroom,
        })
    return lessons


@router.post("/internal/student/learning-context")
def student_learning_context(body: LearningContextRequest, session: SessionDep,
                             x_student_service_key: str | None = Header(default=None)):
    """Versioned learning context for a verified launch token.

    Returns published content only. The classroom is optional: text-only
    courses still start the student agent; the player is an add-on.
    """
    check_student_service_key(x_student_service_key)
    try:
        payload = verify_launch_token(body.launch_token)
        _resolve_launch_context(session, payload)  # enrollment re-check
        user_id = uuid.UUID(payload["uid"])
        course_id = uuid.UUID(payload["cid"])

        course = session.execute(
            text("SELECT title FROM public.course WHERE id = :id"), {"id": course_id}
        ).first()
        if not course:
            raise HTTPException(404, "课程不存在")
        package_payload = _published_package_payload(session, course_id)
        if not package_payload:
            raise HTTPException(409, "课程尚未发布学习内容")

        classroom_id = _published_classroom(session, course_id)
        lessons = _published_lessons(session, course_id, user_id)
        context = {
            "schemaVersion": SCHEMA_VERSION,
            "userId": str(user_id),
            "courseId": str(course_id),
            "courseTitle": course[0],
            "publication": {"id": package_payload.get("id"), "version": int(package_payload.get("version") or 1)},
            "knowledgePackage": {
                "title": package_payload.get("title") or course[0],
                "summary": package_payload.get("summary") or "",
                "entries": package_payload.get("entries") or [],
            },
            "classroom": _classroom_view(session, classroom_id) if classroom_id else None,
            "lessons": lessons,
        }
        grant = _issue_playback_grant(user_id, course_id, classroom_id) if classroom_id else None
        if grant:
            context["classroom"]["playbackToken"] = grant
        return context
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(503, "平台数据库暂不可用，请稍后重试") from error


def _issue_playback_grant(user_id: uuid.UUID, course_id: uuid.UUID, classroom_id: str) -> str:
    """Short-lived playback authorization bound to user+course+classroom.

    The teacher-side authorize hook validates it (stage 5); students cannot
    open other classrooms by editing URLs.
    """
    import time as _time
    payload = {
        "kind": "playback", "uid": str(user_id), "cid": str(course_id), "rid": classroom_id,
        "exp": int(_time.time()) + 1800, "nonce": secrets.token_urlsafe(9),
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    encoded = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    return f"{encoded}.{_launch_signature(payload_json)}"


@router.get("/student/status")
async def student_status(current_user: CurrentUser):
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.get(f"{settings.STUDENT_URL}/api/session/health")
            ready = response.status_code == 200
    except httpx.HTTPError:
        ready = False
    return {"studentAgentReady": ready, "studentUrl": settings.STUDENT_PUBLIC_URL}
