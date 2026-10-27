"""Durable, publication-triggered knowledge preparation shared by all students."""
from __future__ import annotations

import hashlib
import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone

from .context import classroom_materials
from .database import _db
from .knowledge import CURRICULUM_VERSION, learning_points
from .prompts import KNOWLEDGE_EXTRACTION_PROMPT

log = logging.getLogger(__name__)
EXTRACTOR_HASH = hashlib.sha256(
    f"{CURRICULUM_VERSION}:{KNOWLEDGE_EXTRACTION_PROMPT}".encode()
).hexdigest()
_stop = threading.Event()


def read(course_id: str, lesson_id: str, video_revision: str) -> dict | None:
    with _db() as connection:
        row = connection.execute(
            "SELECT status, extractor_hash, points, coverage, last_error FROM "
            "student.published_lesson_knowledge WHERE course_id=%s AND lesson_id=%s "
            "AND video_revision=%s", (course_id, lesson_id, video_revision),
        ).fetchone()
    if not row:
        return None
    status, extractor_hash, points, coverage, error = row
    return {"status": status if extractor_hash == EXTRACTOR_HASH else "pending",
            "points": points if extractor_hash == EXTRACTOR_HASH else None,
            "coverage": coverage if extractor_hash == EXTRACTOR_HASH else None,
            "error": error if extractor_hash == EXTRACTOR_HASH else None}


def retry(course_id: str, lesson_id: str, video_revision: str) -> bool:
    with _db() as connection:
        row = connection.execute(
            "UPDATE student.published_lesson_knowledge SET status='pending', "
            "next_retry_at=now(), lease_until=NULL, claim_token=NULL, "
            "last_error=NULL, updated_at=now() "
            "WHERE course_id=%s AND lesson_id=%s AND video_revision=%s "
            "AND status='failed' RETURNING 1", (course_id, lesson_id, video_revision),
        ).fetchone()
    return bool(row)


def process_next() -> bool:
    """Claim one job across workers, then commit the model result separately."""
    with _db() as connection:
        connection.execute(
            "UPDATE student.published_lesson_knowledge SET status='pending', "
            "points=NULL, coverage=NULL, next_retry_at=now(), updated_at=now() "
            "WHERE status='ready' AND extractor_hash<>%s", (EXTRACTOR_HASH,),
        )
        job = connection.execute(
            "SELECT course_id, lesson_id, video_revision, scenes, attempts FROM "
            "student.published_lesson_knowledge WHERE "
            "((status IN ('pending','failed') AND next_retry_at<=now()) "
            "OR (status='running' AND lease_until<now())) "
            "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"
        ).fetchone()
        if not job:
            return False
        key = tuple(job[:3])
        claim_token = secrets.token_hex(16)
        connection.execute(
            "UPDATE student.published_lesson_knowledge SET status='running', "
            "lease_until=now()+interval '10 minutes', attempts=attempts+1, "
            "extractor_hash=%s, claim_token=%s, updated_at=now() "
            "WHERE course_id=%s AND lesson_id=%s AND video_revision=%s",
            (EXTRACTOR_HASH, claim_token, *key),
        )
    try:
        result = learning_points(classroom_materials(job[3]))
        coverage = {"partial": result.partial, "acceptedCount": len(result.points),
                    "rejectedCount": result.rejected_count,
                    "candidateCount": result.candidate_count,
                    "repairAttempted": result.repair_attempted}
        from psycopg.types.json import Jsonb
        with _db() as connection:
            connection.execute(
                "UPDATE student.published_lesson_knowledge SET status='ready', "
                "points=%s, coverage=%s, lease_until=NULL, last_error=NULL, "
                "claim_token=NULL, updated_at=now() WHERE course_id=%s AND lesson_id=%s "
                "AND video_revision=%s AND status='running' AND claim_token=%s",
                (Jsonb(result.points), Jsonb(coverage), *key, claim_token),
            )
    except Exception as error:
        log.exception("Published lesson knowledge extraction failed: lesson=%s", key[1])
        delay = min(300, 10 * 2 ** min(job[4], 5))
        with _db() as connection:
            connection.execute(
                "UPDATE student.published_lesson_knowledge SET status='failed', "
                "next_retry_at=%s, lease_until=NULL, claim_token=NULL, "
                "last_error=%s, updated_at=now() "
                "WHERE course_id=%s AND lesson_id=%s AND video_revision=%s "
                "AND status='running' AND claim_token=%s",
                (datetime.now(timezone.utc) + timedelta(seconds=delay),
                 type(error).__name__, *key, claim_token),
            )
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
