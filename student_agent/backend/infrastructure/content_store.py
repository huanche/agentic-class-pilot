"""PostgreSQL Adapter for immutable content and pinned-version hydration."""
from __future__ import annotations
import json
from contextlib import nullcontext
from backend.content.lesson_content import validate, bind
from backend.infrastructure import database

def store(body, *, connection=None):
    validate(body)
    with (database._db() if connection is None else nullcontext(connection)) as connection:
        connection.execute(
            "INSERT INTO student.lesson_content_versions (content_id,course_id,lesson_id,video_revision,"
            "compiler_version,source_manifest_hash,payload) VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT DO NOTHING", (body["contentId"], body["courseId"], body["lessonId"], body["sourceRevision"],
            body["compilerVersion"], body["sourceManifestHash"], json.dumps(body, ensure_ascii=False)))
        saved = find(body["courseId"], body["lessonId"], body["sourceRevision"], body["compilerVersion"],
                     body["sourceManifestHash"], connection=connection)
        if saved["contentId"] != body["contentId"]:
            raise ValueError("A compiled content version cannot be replaced")
        return saved


def find(course_id, lesson_id, revision, compiler_version, manifest_hash, *, connection=None):
    with (database._db() if connection is None else nullcontext(connection)) as connection:
        row = connection.execute("SELECT payload FROM student.lesson_content_versions WHERE course_id=%s "
            "AND lesson_id=%s AND video_revision=%s AND compiler_version=%s AND source_manifest_hash=%s",
            (str(course_id), str(lesson_id), str(revision), str(compiler_version), manifest_hash)).fetchone()
        if row:
            validate(row[0])
        return row[0] if row else None


def hydrate(session, *, connection=None):
    if not session.get("contentRef"):
        return bind(session)
    body = session.get("lessonContent")
    if body is None:
        with (database._db() if connection is None else nullcontext(connection)) as connection:
            row = connection.execute("SELECT payload FROM student.lesson_content_versions WHERE content_id=%s",
                                     (session["contentRef"]["contentId"],)).fetchone()
        if not row:
            raise ValueError("Pinned lesson content is unavailable")
        body = row[0]
    result = dict(session, lessonContent=body)
    return bind(result)
