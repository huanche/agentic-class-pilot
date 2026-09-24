"""Learning-data persistence boundary.

Production: writes to the shared education database's student schema (DDL
owned by the platform migration final04; this module only performs DML with
idempotent keys). Demo mode: JSON files under runtime/ (explicit opt-in via
STUDENT_DEMO_MODE=true). The business state machine never touches SQL or the
filesystem directly.
"""
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from . import config

RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtime" / "integration"


class PersistenceError(RuntimeError):
    """Learning data could not be persisted."""


def _db() -> Any:
    import psycopg  # imported lazily: only needed in production mode
    url = config.student_database_url()
    if not url:
        raise PersistenceError("STUDENT_DATABASE_URL 未配置")
    return psycopg.connect(url.replace("+psycopg", ""), autocommit=False)


def _demo_path(kind: str, key: str) -> Path:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in key)
    return RUNTIME_DIR / f"{kind}-{safe}.json"


def record_event(session_key: str, user_id: str, course_id: str, publication_id: str,
                 event_type: str, payload: Optional[Dict[str, Any]] = None,
                 classroom_id: Optional[str] = None, event_id: Optional[str] = None) -> None:
    """Append one learning event (session start, message, playback, mastery…).

    Idempotency: keyed by (session_key, event_type, event_id) in production;
    demo mode is best-effort JSON append.
    """
    body = {
        "user_id": user_id, "course_id": course_id, "publication_id": publication_id,
        "classroom_id": classroom_id, "event_type": event_type, "event_id": event_id,
        "payload": payload or {}, "recorded_at": int(time.time() * 1000),
    }
    if config.demo_mode():
        path = _demo_path("events", session_key)
        existing = []
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
        if event_id and any(item.get("event_id") == event_id and item.get("event_type") == event_type
                            for item in existing):
            return
        existing.append(body)
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=1), encoding="utf-8")
        return
    with _db() as connection:
        connection.execute(
            "INSERT INTO student.learning_events "
            "(session_key, user_id, course_id, publication_id, classroom_id, event_type, event_id, payload) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (session_key, event_type, event_id) DO NOTHING",
            (session_key, user_id, course_id, publication_id, classroom_id,
             event_type, event_id, json.dumps(body["payload"], ensure_ascii=False)))
        connection.commit()


def upsert_session(session_key: str, user_id: str, course_id: str,
                   publication_id: str, publication_version: int,
                   classroom_id: str | None = None,
                   student_name: str | None = None) -> None:
    """会话行：首插后每次活跃刷新 last_active_at（幂等，session_key 主键）。"""
    if config.demo_mode():
        path = _demo_path("session", session_key)
        path.write_text(json.dumps({
            "session_key": session_key, "user_id": user_id, "course_id": course_id,
            "publication_id": publication_id, "publication_version": publication_version,
            "classroom_id": classroom_id,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        return
    with _db() as connection:
        connection.execute(
            "INSERT INTO student.student_sessions "
            "(session_key, user_id, course_id, publication_id, publication_version, classroom_id, student_name) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (session_key) DO UPDATE SET last_active_at = now()",
            (session_key, user_id, course_id, publication_id,
             publication_version, classroom_id, student_name))
        connection.commit()


def finish_session(session_key: str) -> None:
    """Mark a persisted session complete without changing its immutable binding."""
    if config.demo_mode():
        return
    with _db() as connection:
        connection.execute(
            "UPDATE student.student_sessions "
            "SET ended_at = COALESCE(ended_at, now()), last_active_at = now() "
            "WHERE session_key = %s",
            (session_key,))
        connection.commit()


def upsert_message(session_key: str, user_id: str, course_id: str,
                   publication_id: str, seq: int, role: str,
                   phase: str | None, content: str) -> None:
    """消息流水：按 (session_key, seq) 幂等。"""
    if config.demo_mode():
        path = _demo_path("messages", session_key)
        existing = []
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
        if any(item.get("seq") == seq for item in existing):
            return
        existing.append({"seq": seq, "role": role, "phase": phase, "content": content})
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=1), encoding="utf-8")
        return
    with _db() as connection:
        connection.execute(
            "INSERT INTO student.student_messages "
            "(session_key, user_id, course_id, publication_id, seq, role, phase, content) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (session_key, seq) DO NOTHING",
            (session_key, user_id, course_id, publication_id, seq, role, phase, content))
        connection.commit()


def upsert_playback_progress(session_key: str, user_id: str, course_id: str,
                             publication_id: str, classroom_id: str,
                             scene_id: str, segment_id: str | None = None) -> None:
    """播放进度：主键 (session_key, scene_id)，重复场景天然幂等。"""
    if config.demo_mode():
        _record_event_stub = None  # demo 下由 record_event 记录即可
        return
    with _db() as connection:
        connection.execute(
            "INSERT INTO student.playback_progress "
            "(session_key, user_id, course_id, publication_id, classroom_id, scene_id, segment_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (session_key, scene_id) DO NOTHING",
            (session_key, user_id, course_id, publication_id, classroom_id, scene_id, segment_id))
        connection.commit()


def upsert_mastery(session_key: str, user_id: str, course_id: str,
                   publication_id: str, knowledge_point_id: str,
                   stars: int, status: str,
                   evidence: str | None = None, source: str | None = None) -> None:
    """掌握度：按 (user, course, publication, kp) 唯一，星级只升不降。"""
    if config.demo_mode():
        path = _demo_path("mastery", f"{session_key}-{knowledge_point_id}")
        path.write_text(json.dumps({
            "session_key": session_key, "knowledge_point_id": knowledge_point_id,
            "stars": stars, "status": status, "evidence": evidence,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        return
    with _db() as connection:
        connection.execute(
            "INSERT INTO student.knowledge_mastery "
            "(session_key, user_id, course_id, publication_id, knowledge_point_id, stars, status, evidence, source) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (user_id, course_id, publication_id, knowledge_point_id) DO UPDATE SET "
            "stars = GREATEST(student.knowledge_mastery.stars, EXCLUDED.stars), "
            "status = EXCLUDED.status, evidence = EXCLUDED.evidence, "
            "source = EXCLUDED.source, updated_at = now()",
            (session_key, user_id, course_id, publication_id,
             knowledge_point_id, stars, status, evidence, source))
        connection.commit()


def upsert_report(session_key: str, user_id: str, course_id: str,
                  publication_id: str, payload: dict) -> None:
    """课后报告：session_key 主键，重复下课覆盖为最新。"""
    if config.demo_mode():
        path = _demo_path("report", session_key)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        return
    with _db() as connection:
        connection.execute(
            "INSERT INTO student.after_class_reports "
            "(session_key, user_id, course_id, publication_id, payload) "
            "VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (session_key) DO UPDATE SET payload = EXCLUDED.payload, created_at = now()",
            (session_key, user_id, course_id, publication_id,
             json.dumps(payload, ensure_ascii=False)))
        connection.commit()
