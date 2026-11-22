"""Bind and restore lesson content at the learning-session seam."""
from __future__ import annotations

from backend.content.lesson_content import bind
from backend.infrastructure import content_store


def hydrate(session, *, connection=None):
    """Restore a pinned package without rebuilding it or changing transaction ownership."""
    if not session.get("contentRef"):
        return bind(session)
    body = session.get("lessonContent")
    if body is None:
        body = content_store.get_by_id(session["contentRef"]["contentId"], connection=connection)
    result = dict(session, lessonContent=body)
    return bind(result)
