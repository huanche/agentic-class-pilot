"""Versioned, source-backed lesson content. No student performance lives here."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def build(course_id, lesson_id, revision, compiler_version, points, materials, *, scenes=None, coverage=None):
    sources = [{"sourceId": item["id"], "kind": item.get("source", "unknown"),
                "locator": {"sceneId": item["id"].removeprefix("scene:")},
                "text": str(item.get("content") or ""), "title": item.get("title", ""),
                "textHash": digest(str(item.get("content") or ""))} for item in materials]
    topics, gaps = [], []
    for point in points:
        refs = []
        for quote in str(point.get("content") or point.get("description") or "").split("\n\n"):
            if not quote.strip():
                continue
            for source in sources:
                if source["sourceId"] in (point.get("sourceIds") or []) and quote in source["text"]:
                    refs.append({"sourceId": source["sourceId"], "quote": quote,
                                 "quoteHash": digest(quote)})
        if not refs:
            gaps.append({"code": "topic_source_unknown", "topicId": point["id"]})
        topics.append({"topicId": point["id"], "title": point.get("title", ""), "sourceRefs": refs})
    if not sources:
        gaps.append({"code": "source_material_unavailable"})
    gaps.extend({"code": "source_text_may_be_truncated", "sourceId": source["sourceId"]}
                for source in sources if len(source["text"]) >= 6000)
    if any(element.get("type") != "text" for scene in scenes or []
           for element in (((scene.get("content") if isinstance(scene.get("content"), dict) else {}).get("canvas") or {}).get("elements") or [])
           if isinstance(element, dict)):
        gaps.append({"code": "visual_content_not_interpreted"})
    clean_points = [{key: deepcopy(point[key]) for key in
                     ("id", "title", "content", "description", "source", "sourceIds") if key in point}
                    for point in points]
    manifest = [{key: source[key] for key in ("sourceId", "kind", "locator", "textHash")} for source in sources]
    body = {"schemaVersion": 1, "courseId": str(course_id), "lessonId": str(lesson_id),
            "sourceRevision": str(revision), "compilerVersion": str(compiler_version),
            "sourceManifestHash": digest(manifest), "sourceManifest": manifest, "sources": sources,
            "topics": topics, "points": clean_points, "coverage": coverage or {}, "coverageGaps": gaps,
            "validationStatus": "limited" if gaps else "source_checked",
            "inputCapabilities": {"classroomText": bool(sources), "originalPpt": False,
                                  "visualSemantics": False}}
    body["contentId"] = "content:" + digest(body)
    return body


def reference(body):
    return {key: body[key] for key in ("contentId", "compilerVersion", "sourceRevision", "sourceManifestHash")}


def validate(body):
    unhashed = {key: value for key, value in body.items() if key != "contentId"}
    if body.get("contentId") != "content:" + digest(unhashed):
        raise ValueError("Lesson content fingerprint is invalid")
    sources = {s["sourceId"]: s for s in body["sources"]}
    if len(sources) != len(body["sources"]):
        raise ValueError("Duplicate source identity")
    manifest = [{key: source[key] for key in ("sourceId", "kind", "locator", "textHash")} for source in body["sources"]]
    if (manifest != body["sourceManifest"] or digest(manifest) != body["sourceManifestHash"]
            or any(source["textHash"] != digest(source["text"]) for source in sources.values())):
        raise ValueError("Source manifest is inconsistent")
    if (len({t["topicId"] for t in body["topics"]}) != len(body["topics"])
            or [p["id"] for p in body["points"]] != [t["topicId"] for t in body["topics"]]):
        raise ValueError("Content topic identity is invalid")
    for topic in body["topics"]:
        for ref in topic["sourceRefs"]:
            if (ref["sourceId"] not in sources or not ref["quote"]
                    or ref["quote"] not in sources[ref["sourceId"]]["text"]
                    or ref["quoteHash"] != digest(ref["quote"])):
                raise ValueError("Lesson citation is not grounded")


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
        clean = [{key: deepcopy(p[key]) for key in ("id", "title", "content", "description", "source", "sourceIds")
                  if key in p} for p in points]
        body = build((session.get("context") or {}).get("courseId", "demo"), session["lessonId"],
                     session.get("videoRevision") or "legacy-unversioned", "legacy-frozen:" + digest(clean),
                     clean, session.get("preparationMaterials") or [], coverage=session.get("preparationCoverage"))
    if body is not None:
        validate(body)
        if (body["courseId"] != str((session.get("context") or {}).get("courseId", "demo"))
                or body["lessonId"] != str(session.get("lessonId"))
                or (body["sourceRevision"] != str(session.get("videoRevision") or "legacy-unversioned")
                    and not (body["sourceRevision"] == "legacy-unversioned"
                             and body["compilerVersion"].startswith("legacy-frozen:")))):
            raise ValueError("Content belongs to a different lesson revision")
        if session.get("contentRef") and reference(body) != session["contentRef"]:
            raise ValueError("Pinned content reference changed")
        point_content = [{key: deepcopy(p[key]) for key in ("id", "title", "content", "description", "source", "sourceIds")
                          if key in p} for p in points]
        if points and body["points"] != point_content:
            raise ValueError("Teaching points differ from pinned content")
        bound.update(contentRef=reference(body), lessonContent=deepcopy(body))
    return bound
