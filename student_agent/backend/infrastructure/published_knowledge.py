"""Durable, publication-triggered knowledge preparation shared by all students."""
from __future__ import annotations

from backend.infrastructure import content_store

import hashlib
import json
import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone

from backend.content.context import classroom_materials
from backend.infrastructure.database import _db
from backend.content.knowledge import EXTRACTION_VERSION, KnowledgePreparationError
from backend.content.knowledge_schema import submit_knowledge_points
from backend.content.knowledge import learning_points
from backend.content.prompts import KNOWLEDGE_EXTRACTION_PROMPT

log = logging.getLogger(__name__)
EXTRACTOR_HASH = hashlib.sha256(
    json.dumps([EXTRACTION_VERSION, KNOWLEDGE_EXTRACTION_PROMPT,
                submit_knowledge_points.model_json_schema()], sort_keys=True).encode()
).hexdigest()
_stop = threading.Event()


def _compiler(extractor):
    return "lesson-content-v1:" + extractor


def _compiled(course, lesson, revision, compiler, scenes, points, coverage):
    from backend.content import lesson_content
    return lesson_content.build(course, lesson, revision, _compiler(compiler), points,
                                classroom_materials(scenes), scenes=scenes, coverage=coverage)


def _archive(connection, row):
    from backend.content import lesson_content
    course, lesson, revision, scenes, points, coverage, compiler = row
    if points and compiler:
        # Retry diagnostics describe a job attempt, not the old immutable content.
        frozen_coverage = {k: v for k, v in (coverage or {}).items() if k != "extractionFailure"}
        body = _compiled(course, lesson, revision, compiler, scenes, points, frozen_coverage)
        content_store.store(body, connection=connection)


def _existing(connection, course, lesson, revision, scenes):
    from backend.content import lesson_content
    manifest = _compiled(course, lesson, revision, EXTRACTOR_HASH, scenes, [], {})["sourceManifestHash"]
    return content_store.find(course, lesson, revision, _compiler(EXTRACTOR_HASH), manifest, connection=connection)


def read(course_id: str, lesson_id: str, video_revision: str) -> dict | None:
    from backend.content import lesson_content
    with _db() as connection:
        row = connection.execute(
            "SELECT scenes,points,coverage,extractor_hash,status,last_error FROM "
            "student.published_lesson_knowledge WHERE course_id=%s AND lesson_id=%s AND video_revision=%s",
            (course_id, lesson_id, video_revision)).fetchone()
        if not row:
            return None
        scenes, points, coverage, compiler, status, error = row
        _archive(connection, (course_id, lesson_id, video_revision, scenes, points, coverage, compiler))
        body = _existing(connection, course_id, lesson_id, video_revision, scenes)
        if body:
            return {"status": "ready", "points": body["points"], "coverage": body["coverage"],
                    "error": None, "contentRef": lesson_content.reference(body), "contentModel": body}
        if status == "ready" and compiler != EXTRACTOR_HASH:
            connection.execute("UPDATE student.published_lesson_knowledge SET status='pending',"
                               "next_retry_at=now() WHERE course_id=%s AND lesson_id=%s AND video_revision=%s "
                               "AND status='ready' AND extractor_hash=%s",
                               (course_id, lesson_id, video_revision, compiler))
            status = "pending"
        return {"status": status, "points": None, "coverage": None, "error": error}


def retry(course_id: str, lesson_id: str, video_revision: str) -> bool:
    with _db() as connection:
        row = connection.execute(
            "UPDATE student.published_lesson_knowledge SET status='pending', next_retry_at=now(),"
            "lease_until=NULL,claim_token=NULL,last_error=NULL,updated_at=now() "
            "WHERE course_id=%s AND lesson_id=%s AND video_revision=%s AND status='failed' RETURNING 1",
            (course_id, lesson_id, video_revision)).fetchone()
    return bool(row)


def process_next() -> bool:
    from backend.content import lesson_content
    # Archive old ready results before scheduling a new compiler. Versions coexist.
    with _db() as connection:
        old = connection.execute(
            "SELECT course_id,lesson_id,video_revision,scenes,points,coverage,extractor_hash "
            "FROM student.published_lesson_knowledge j WHERE status='ready' AND extractor_hash<>%s "
            "AND NOT EXISTS (SELECT 1 FROM student.lesson_content_versions v WHERE v.course_id=j.course_id "
            "AND v.lesson_id=j.lesson_id AND v.video_revision=j.video_revision AND v.compiler_version=%s) "
            "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1", (EXTRACTOR_HASH, _compiler(EXTRACTOR_HASH))).fetchone()
        if old:
            _archive(connection, old)
            connection.execute("UPDATE student.published_lesson_knowledge SET status='pending',next_retry_at=now() "
                               "WHERE course_id=%s AND lesson_id=%s AND video_revision=%s", tuple(old[:3]))
        job = connection.execute(
            "SELECT course_id,lesson_id,video_revision,scenes,attempts,points,coverage,extractor_hash "
            "FROM student.published_lesson_knowledge WHERE (((status='pending' OR (status='failed' AND "
            "COALESCE(coverage->'extractionFailure'->>'manualRetryRequired','false')<>'true')) AND next_retry_at<=now()) "
            "OR (status='running' AND lease_until<now())) ORDER BY created_at "
            "FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
        if not job:
            return False
        key, scenes = tuple(job[:3]), job[3]
        _archive(connection, (*key, scenes, job[5], job[6], job[7]))
        ready = _existing(connection, *key, scenes)
        if ready:
            connection.execute("UPDATE student.published_lesson_knowledge SET status='ready',extractor_hash=%s,"
                               "points=%s,coverage=%s,claim_token=NULL,lease_until=NULL WHERE course_id=%s "
                               "AND lesson_id=%s AND video_revision=%s", (EXTRACTOR_HASH,
                                json.dumps(ready["points"], ensure_ascii=False),
                                json.dumps(ready["coverage"]), *key))
            return True
        compiler = EXTRACTOR_HASH
        claim_token = secrets.token_hex(16)
        connection.execute("UPDATE student.published_lesson_knowledge SET status='running',"
                           "lease_until=now()+interval '10 minutes',attempts=attempts+1,claim_token=%s,updated_at=now() "
                           "WHERE course_id=%s AND lesson_id=%s AND video_revision=%s", (claim_token, *key))
    try:
        result = learning_points(classroom_materials(scenes), *key[:2])
        coverage = {"partial": result.partial, "acceptedCount": len(result.points),
                    "rejectedCount": result.rejected_count, "candidateCount": result.candidate_count,
                    "repairAttempted": result.repair_attempted, "modelCalls": result.model_calls,
                    "duplicateCount": result.duplicate_count}
        body = _compiled(*key, compiler, scenes, result.points, coverage)
        from psycopg.types.json import Jsonb
        with _db() as connection:
            accepted = connection.execute(
                "UPDATE student.published_lesson_knowledge SET status='ready',extractor_hash=%s,points=%s,coverage=%s,"
                "lease_until=NULL,last_error=NULL,claim_token=NULL,updated_at=now() WHERE course_id=%s "
                "AND lesson_id=%s AND video_revision=%s AND status='running' AND claim_token=%s "
                "AND lease_until>clock_timestamp() RETURNING 1",
                (compiler, Jsonb(result.points), Jsonb(coverage), *key, claim_token)).fetchone()
            if accepted:
                content_store.store(body, connection=connection)
    except Exception as error:
        log.exception("Published lesson knowledge extraction failed: lesson=%s", key[1])
        delay = min(300, 10 * 2 ** min(job[4], 5))
        with _db() as connection:
            diagnostics = {"code": error.code, "modelCalls": error.model_calls, "manualRetryRequired": True,
                           "issues": [vars(issue) for issue in error.issues], "draft": error.draft} \
                if isinstance(error, KnowledgePreparationError) else {"code": type(error).__name__}
            connection.execute("UPDATE student.published_lesson_knowledge SET status='failed',next_retry_at=%s,"
                               "lease_until=NULL,claim_token=NULL,last_error=%s,"
                               "coverage=COALESCE(coverage,'{}'::jsonb)||CAST(%s AS jsonb),updated_at=now() WHERE course_id=%s "
                               "AND lesson_id=%s AND video_revision=%s AND status='running' AND claim_token=%s",
                               (datetime.now(timezone.utc) + timedelta(seconds=delay), type(error).__name__,
                                json.dumps({"extractionFailure": diagnostics}, ensure_ascii=False), *key, claim_token))
    return True


def worker() -> None:
    while not _stop.is_set():
        try:
            if process_next():
                continue
        except Exception:
            log.exception("Published lesson knowledge worker failed")
        _stop.wait(10)


def start_worker() -> None:
    _stop.clear()
    threading.Thread(target=worker, name="published-knowledge", daemon=True).start()


def stop_worker() -> None:
    _stop.set()
