"""Convert platform learning-context payloads into stable internal models.

Only this module understands the platform JSON shape (schemaVersion 1); the
teaching state machine consumes the resulting CourseLearningContext.
"""
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from . import evaluation as evaluation_adapter
from .models import (ClassroomRef, ClassroomScene, CourseLearningContext,
                     KnowledgeEntry, KnowledgePackage, Lesson, PublicationRef,
                     SceneAction, Segment)

SUPPORTED_SCHEMA_VERSION = 1


class ContextContractError(ValueError):
    """Payload violates the learning-context contract."""


def from_platform_payload(payload: Dict[str, Any]) -> CourseLearningContext:
    version = int(payload.get("schemaVersion") or 0)
    if version != SUPPORTED_SCHEMA_VERSION:
        raise ContextContractError(
            f"不支持的学习上下文版本 schemaVersion={version}（支持 {SUPPORTED_SCHEMA_VERSION}）")
    for field in ("userId", "courseId", "publication", "knowledgePackage"):
        if field not in payload:
            raise ContextContractError(f"学习上下文缺少必需字段：{field}")
    publication = payload["publication"]
    for field in ("id", "version"):
        if field not in publication:
            raise ContextContractError(f"publication 缺少必需字段：{field}")

    context = CourseLearningContext(
        schema_version=version,
        user_id=str(payload["userId"]),
        course_id=str(payload["courseId"]),
        course_title=str(payload.get("courseTitle") or ""),
        publication=PublicationRef(id=str(publication["id"]), version=int(publication["version"])),
        knowledge_package=_package(payload["knowledgePackage"]),
        classroom=_classroom(payload.get("classroom")),
    )
    context.lessons = _published_lessons(payload.get("lessons"), context) or _lessons(context)
    context.evaluation = evaluation_adapter.from_internal_context(context)
    return context


def _package(raw: Dict[str, Any]) -> KnowledgePackage:
    entries = []
    for item in (raw.get("entries") or []):
        if not isinstance(item, dict) or "id" not in item:
            raise ContextContractError("knowledgePackage.entries 含无效条目（缺 id）")
        citations = item.get("citations") or []
        entries.append(KnowledgeEntry(
            id=str(item["id"]),
            title=str(item.get("title") or ""),
            content=str(item.get("content") or ""),
            source_name=str(citations[0].get("sourceName")) if citations and citations[0].get("sourceName") else None,
        ))
    return KnowledgePackage(
        title=str(raw.get("title") or ""),
        summary=str(raw.get("summary") or ""),
        entries=entries,
    )


def _classroom(raw: Optional[Dict[str, Any]]) -> Optional[ClassroomRef]:
    if not raw or not raw.get("id"):
        return None
    scenes: List[ClassroomScene] = []
    for scene in (raw.get("scenes") or []):
        actions = [SceneAction(
            id=str(action.get("id") or ""),
            type=str(action.get("type") or "speech"),
            text=action.get("text"),
        ) for action in (scene.get("actions") or []) if isinstance(action, dict)]
        scenes.append(ClassroomScene(
            id=str(scene.get("id") or ""),
            order=int(scene.get("order") or 1),
            title=str(scene.get("title") or ""),
            actions=actions,
        ))
    scenes.sort(key=lambda item: item.order)
    return ClassroomRef(id=str(raw["id"]), player_url=str(raw.get("playerUrl") or ""), scenes=scenes)


def _lessons(context: CourseLearningContext) -> List[Lesson]:
    """One lesson per learning session.

    With a classroom: each scene becomes a segment (completion = scene
    completed in the player). Without: each knowledge entry becomes a text
    segment (completion = discussed), so text-only courses still start.
    """
    segments: List[Segment] = []
    if context.classroom and context.classroom.scenes:
        for index, scene in enumerate(context.classroom.scenes, start=1):
            speech = " ".join(a.text for a in scene.actions if a.type == "speech" and a.text)
            segments.append(Segment(
                id=f"seg-scene-{index}",
                title=scene.title or f"第 {index} 页",
                order=index,
                source_scene_id=scene.id,
                content=speech.strip(),
                completion_rule="scene-completed",
            ))
    else:
        for index, entry in enumerate(context.knowledge_package.entries, start=1):
            segments.append(Segment(
                id=f"seg-entry-{index}",
                title=entry.title or f"第 {index} 节",
                order=index,
                content=entry.content,
                completion_rule="discussed",
            ))
    lesson_title = context.knowledge_package.title or context.course_title or "课程学习"
    return [Lesson(id=f"lesson-{context.publication.id}", title=lesson_title,
                   order=1, segments=segments, classroom=context.classroom)]


def _published_lessons(raw_lessons: Any, context: CourseLearningContext) -> List[Lesson]:
    """Convert the platform's published classroom catalog.

    Each published classroom is a selectable lesson.  Keeping this mapping in
    the adapter isolates the student state machine from platform payloads.
    """
    if not isinstance(raw_lessons, list):
        return []
    lessons: List[Lesson] = []
    for index, raw in enumerate(raw_lessons, start=1):
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        classroom = _classroom(raw.get("classroom"))
        if not classroom:
            continue
        segments = []
        for scene_index, scene in enumerate(classroom.scenes, start=1):
            speech = " ".join(a.text for a in scene.actions if a.type == "speech" and a.text)
            segments.append(Segment(
                id=f"seg-{raw['id']}-{scene_index}",
                title=scene.title or f"第 {scene_index} 页",
                order=scene_index,
                source_scene_id=scene.id,
                content=speech.strip(),
                completion_rule="scene-completed",
            ))
        lessons.append(Lesson(
            id=str(raw["id"]),
            title=str(raw.get("title") or classroom.id),
            order=int(raw.get("order") or index),
            segments=segments,
            classroom=classroom,
        ))
    lessons.sort(key=lambda item: item.order)
    return lessons



def load_plan_for_session(state) -> Optional[dict]:
    """Convert the session's learning context into a lesson-plan dict.

    Returns None when the session carries no learning context (demo mode:
    the orchestrator then loads its local lesson-plan.json).

    The generated plan reuses the orchestrator's plan schema so the state
    machine (stages, segments, advance policy) keeps working unchanged.
    """
    context = state.get("learning_context") if isinstance(state, dict) else None
    if not context:  # None or empty dict (demo mode)
        return None
    if isinstance(context, dict):
        context = CourseLearningContext(**context)
    selected = next((lesson for lesson in context.lessons
                     if lesson.id == state.get("lesson_id")), None)
    selected = selected or (context.lessons[0] if context.lessons else None)
    segments = selected.segments if selected else []
    total_minutes = max(20, 5 * len(segments))
    knowledge_points = [
        {"id": kp.id, "title": kp.title,
         "expected": kp.expected_concepts, "misconceptions": kp.misconceptions}
        for kp in context.evaluation.knowledge_points
    ]

    def segment_knowledge_ids(segment) -> List[str]:
        haystack = f"{segment.title}\n{segment.content}".lower()
        matched = []
        for point in knowledge_points:
            terms = [point["title"], *point["expected"]]
            if any(str(term).strip().lower() in haystack for term in terms if str(term).strip()):
                matched.append(point["id"])
        if not matched and len(segments) == 1:
            return [point["id"] for point in knowledge_points]
        return matched

    plan = {
        "version": 2,
        "source": "platform-published",
        "publication_id": context.publication.id,
        "publication_version": context.publication.version,
        "lesson_id": selected.id if selected else context.course_id,
        "course_id": context.course_id,
        "title": selected.title if selected else context.course_title,
        "total_minutes": total_minutes,
        "stages": [
            {"id": "guided_learning", "name": "讲解", "enabled": True, "delivery": "video",
             "minutes": max(10, total_minutes // 2), "advance_when": "evidence"},
            {"id": "recap_discussion", "name": "复述讨论", "enabled": True,
             "minutes": max(5, total_minutes // 4), "advance_when": "either"},
            {"id": "deep_inquiry", "name": "深入探究", "enabled": True,
             "minutes": max(5, total_minutes // 4), "advance_when": "either"},
        ],
        "segments": [
            {"id": seg.id, "title": seg.title, "order": seg.order,
             "knowledge_point_ids": segment_knowledge_ids(seg), "content": seg.content,
             "source": {"scene_id": seg.source_scene_id, "position": f"scene {seg.source_scene_id or seg.order}"}}
            for seg in segments
        ],
        "advance_policy": {
            "on_budget_exhausted": "advance",
            "on_evidence_reached": "advance",
            "min_stage_minutes": 0,
            "max_stage_overrun_minutes": 10,
        },
        "evaluation": context.evaluation.model_dump(),
        "knowledge_points": knowledge_points,
    }
    return plan
