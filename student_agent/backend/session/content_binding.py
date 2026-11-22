"""Bind and restore lesson content at the learning-session seam."""
from __future__ import annotations

from copy import deepcopy

from backend.content import lesson_content
from backend.infrastructure import content_store


def bind(session, result=None):
    """Pure binding, including a frozen legacy capture with explicit unknown sources."""
    bound = dict(session)
    points = (session.get("dialogue") or {}).get("points") or []
    if result:
        body = result.get("contentModel")
        points = result.get("points") or points
    else:
        body = session.get("lessonContent")
    if body is None and session.get("contentRef"):
        # The persisted reference will be hydrated at the storage seam, never silently rebuilt.
        return bound
    if body is None and points and session.get("lessonId"):
        clean = [lesson_content.point_payload(p) for p in points]
        body = lesson_content.build(
            (session.get("context") or {}).get("courseId", "demo"), session["lessonId"],
            session.get("videoRevision") or "legacy-unversioned", "legacy-frozen:" + lesson_content.digest(clean),
            clean, session.get("preparationMaterials") or [], coverage=session.get("preparationCoverage"))
    if body is not None:
        lesson_content.validate(body)
        if (body["courseId"] != str((session.get("context") or {}).get("courseId", "demo"))
                or body["lessonId"] != str(session.get("lessonId"))
                or (body["sourceRevision"] != str(session.get("videoRevision") or "legacy-unversioned")
                    and not (body["sourceRevision"] == "legacy-unversioned"
                             and body["compilerVersion"].startswith("legacy-frozen:")))):
            raise ValueError("Content belongs to a different lesson revision")
        if session.get("contentRef") and lesson_content.reference(body) != session["contentRef"]:
            raise ValueError("Pinned content reference changed")
        point_content = [lesson_content.point_payload(p) for p in points]
        if points and body["points"] != point_content:
            raise ValueError("Teaching points differ from pinned content")
        bound.update(contentRef=lesson_content.reference(body), lessonContent=deepcopy(body))
    return bound


def hydrate(session, *, connection=None):
    """Restore a pinned package without rebuilding it or changing transaction ownership."""
    if not session.get("contentRef"):
        return bind(session)
    body = session.get("lessonContent")
    if body is None:
        body = content_store.get_by_id(session["contentRef"]["contentId"], connection=connection)
    result = dict(session, lessonContent=body)
    return bind(result)
