"""Convert platform learning-context payloads into stable internal models.

Only this module understands the platform JSON shape (schemaVersion 1); the
teaching state machine consumes the resulting CourseLearningContext.
"""
from typing import Any, Dict, List, Optional

from . import evaluation as evaluation_adapter
from .models import (ClassroomRef, ClassroomScene, CourseLearningContext,
                     KnowledgeEntry, KnowledgePackage, Lesson, LessonCatalogItem, PublicationRef,
                     SceneAction, Segment)

SUPPORTED_SCHEMA_VERSION = 1


class ContextContractError(ValueError):
    """Payload violates the learning-context contract."""


def from_platform_payload(payload: Dict[str, Any], lesson_id: Optional[str] = None) -> CourseLearningContext:
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

    selected_id = payload.get("selectedLessonId")
    if lesson_id and selected_id != lesson_id:
        raise ContextContractError("平台返回的课时与所选课时不一致，请重新进入课程")
    raw_catalog = payload.get("lessonCatalog") or []
    catalog = [LessonCatalogItem(
        id=str(item["id"]), title=str(item.get("title") or ""), order=int(item.get("order") or 1),
        week=item.get("week"), lesson_number=item.get("lessonNumber"),
        teaching_hours=item.get("teachingHours"), segment_count=int(item.get("segmentCount") or 0),
    ) for item in raw_catalog if isinstance(item, dict) and item.get("id")]
    package = payload["knowledgePackage"]
    entries = []
    if selected_id:
        for entry in package.get("entries") or []:
            scope = entry.get("scope") or {}
            if (scope.get("lessonId") == selected_id or
                    (scope.get("type") == "course" and not scope.get("lessonId")
                     and entry.get("resourceType") != "knowledge-points")):
                entries.append(entry)
    context = CourseLearningContext(
        schema_version=version,
        user_id=str(payload["userId"]),
        course_id=str(payload["courseId"]),
        course_title=str(payload.get("courseTitle") or ""),
        publication=PublicationRef(id=str(publication["id"]), version=int(publication["version"])),
        knowledge_package=_package({**package, "entries": entries}),
        selected_lesson_id=selected_id,
        lesson_catalog=catalog,
    )
    if selected_id:
        selected = [item for item in payload.get("lessons") or [] if item.get("id") == selected_id]
        context.lessons = _published_lessons(selected)
        if len(context.lessons) != 1:
            raise ContextContractError("所选课时没有有效的已发布课堂")
        context.classroom = context.lessons[0].classroom
        context.evaluation = evaluation_adapter.from_platform_context(payload)
    else:
        context.evaluation = evaluation_adapter.from_platform_context({})
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


def _published_lessons(raw_lessons: Any) -> List[Lesson]:
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
            week=raw.get("week"),
            lesson_number=raw.get("lessonNumber"),
            teaching_hours=raw.get("teachingHours"),
            segments=segments,
            classroom=classroom,
        ))
    lessons.sort(key=lambda item: item.order)
    return lessons



def load_plan_for_session(state) -> Optional[dict]:
    """Convert the session's learning context into a lesson-plan dict.

    Returns None when the session carries no platform learning context; the
    orchestrator treats that as a failed platform launch and refuses to start.

    The generated plan reuses the orchestrator's plan schema so the state
    machine (stages, segments, advance policy) keeps working unchanged.
    """
    context = state.get("learning_context") if isinstance(state, dict) else None
    if not context:
        return None
    if isinstance(context, dict):
        context = CourseLearningContext(**context)
    # 平台课时没有本地课时文件，kp_title 查不到标题会把 KP-xxx 编号念出来；
    # 建计划时把平台下发的知识点标题注册进编排器。
    try:
        import agent as orchestrator_agent
        orchestrator_agent.register_kp_titles(
            {kp.id: kp.title for kp in context.evaluation.knowledge_points
             if kp.id and kp.title})
    except Exception as error:  # noqa: BLE001 —— 注册失败只影响称谓，不挡上课
        print(f"[course_adapter] 知识点标题注册失败: {error}")
    selected = next((lesson for lesson in context.lessons
                     if lesson.id == state.get("lesson_id")), None)
    if selected is None or context.selected_lesson_id != state.get("lesson_id"):
        raise ContextContractError("请先选择有效课时，禁止回退到其他课时")
    segments = selected.segments
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
        "lesson_id": selected.id,
        "course_id": context.course_id,
        # 开场白/报告等学生可见文案读的是 lesson_title；以前只有 title，
        # 取不到就回退成 lesson-N7fcx... 这类原始 ID 念给学生听。
        "lesson_title": selected.title,
        "title": selected.title,
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
        "knowledge_sources": [entry.model_dump() for entry in context.knowledge_package.entries],
    }
    return plan


def repair_empty_knowledge_catalog(state: Dict[str, Any]) -> bool:
    """重入时补齐旧桥接遗漏的空目录，不替换已有目录或跨发布版改课。

    只改知识点评价与段落关联；课件内容、时间、星级和对话保留。
    旧空目录生成的无归属检测题清掉，下次发言再按真实知识点出题。
    """
    plan = state.get("lesson_plan") or {}
    if plan.get("source") != "platform-published" or plan.get("knowledge_points"):
        return False
    context = state.get("learning_context") or {}
    if not context:
        return False
    if isinstance(context, dict):
        context = CourseLearningContext(**context)
    if (context.course_id != plan.get("course_id")
            or context.publication.id != plan.get("publication_id")
            or context.publication.version != plan.get("publication_version")
            or not context.evaluation.knowledge_points
            or not any(lesson.id == plan.get("lesson_id") for lesson in context.lessons)):
        return False
    fresh = load_plan_for_session({"learning_context": context, "lesson_id": plan["lesson_id"]})
    if not fresh:
        return False
    segments = {segment["id"]: segment for segment in fresh["segments"]}
    state["lesson_plan"] = {
        **plan,
        "knowledge_points": fresh["knowledge_points"],
        "evaluation": fresh["evaluation"],
        "knowledge_sources": fresh["knowledge_sources"],
        "segments": [{**segment, "knowledge_point_ids":
                      segments.get(segment["id"], {}).get("knowledge_point_ids", [])}
                     for segment in plan.get("segments", [])],
    }
    question = state.get("tutoring_question")
    if question and not question.get("kp_id"):
        state["tutoring_question"] = None
        state["tutoring_last_judgement"] = None
    return True
