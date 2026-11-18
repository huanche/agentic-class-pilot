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
        _store_archive(connection, body)


def _store_archive(connection, body):
    # Keep the generic store strict, including the insert race. Both candidates
    # are validated before comparison; return the original fingerprint unchanged.
    from backend.content import lesson_content
    lesson_content.validate(body)
    try:
        return content_store.store(body, connection=connection)
    except content_store.ContentVersionConflict:
        saved = content_store.find(body["courseId"], body["lessonId"], body["sourceRevision"],
                                   body["compilerVersion"], body["sourceManifestHash"], connection=connection)
        def metadata_only(left, right):
            if set(left) != set(right):
                return False
            # Both full fingerprints were validated above. Only their derived
            # digest may differ when the exact coverage whitelist differs.
            for key in left:
                if key == "contentId":
                    continue
                if key == "coverage":
                    a, b = left[key], right[key]
                    if any(value is not None and not isinstance(value, str)
                           for value in (a.get("courseName"), b.get("courseName"))):
                        return False
                    for field in (set(a) | set(b)) - {"courseName"}:
                        if field not in a or field not in b or a[field] != b[field]:
                            return False
                elif left[key] != right[key]:
                    return False
            return True
        if saved is not None and metadata_only(saved, body):
            return saved
        raise


def _conflict_result():
    return {"status": "failed", "points": None, "coverage": None,
            "error": "published_content_conflict"}


def _fail_archive(connection, key):
    connection.execute("UPDATE student.published_lesson_knowledge SET status='failed',"
                       "last_error='published_content_conflict',claim_token=NULL,lease_until=NULL,"
                       "coverage=COALESCE(coverage,'{}'::jsonb)||%s::jsonb WHERE course_id=%s "
                       "AND lesson_id=%s AND video_revision=%s",
                       (json.dumps({"extractionFailure": {"code": "published_content_conflict",
                                                          "manualRetryRequired": True}}), *key))


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
        try:
            _archive(connection, (course_id, lesson_id, video_revision, scenes, points, coverage, compiler))
        except content_store.ContentVersionConflict:
            return _conflict_result()
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
            try:
                _archive(connection, old)
            except content_store.ContentVersionConflict:
                _fail_archive(connection, tuple(old[:3]))
                return True
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
        try:
            _archive(connection, (*key, scenes, job[5], job[6], job[7]))
        except content_store.ContentVersionConflict:
            _fail_archive(connection, key)
            return True
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
        course_name = (job[6] or {}).get("courseName") or ""
        result = learning_points(classroom_materials(scenes), *key[:2], course_name=course_name)
        coverage = {"courseName": course_name, "partial": result.partial, "acceptedCount": len(result.points),
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
                _store_archive(connection, body)
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
