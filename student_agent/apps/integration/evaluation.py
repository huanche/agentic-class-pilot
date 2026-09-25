"""Course-level evaluation contracts.

Published packages may carry a rubric (knowledge points, expected concepts,
misconceptions). When they do not, a generic semantic contract is used and
explicitly marked `is_default` — the hardcoded operating-system keyword
groups are never applied to other courses.
"""
from typing import Any, Dict, List
import re

from .models import EvaluationContract, KnowledgePoint

#: When the platform context carries knowledge points, derive at most this
#: many expected concepts per point from the published entry content.
_MAX_CONCEPTS_PER_POINT = 6


def from_internal_context(context) -> EvaluationContract:
    """Build the contract from the internal CourseLearningContext model.

    Preference: published rubric → knowledge-package entries (titled
    concepts) → generic semantic fallback (marked default).
    """
    package = context.knowledge_package
    points: List[KnowledgePoint] = []
    for entry in package.entries:
        title = entry.title.strip()
        if not title:
            continue
        points.append(KnowledgePoint(
            id=entry.id,
            title=title,
            expected_concepts=_concepts_from_content(entry.content),
        ))
    if points:
        return EvaluationContract(knowledge_points=points, is_default=False,
                                  source="published-entries")
    return EvaluationContract(
        knowledge_points=[KnowledgePoint(
            id=f"{context.course_id}:core",
            title=context.course_title or "本课主题",
        )],
        source="default-semantic",
    )


def from_platform_context(context: Dict[str, Any]) -> EvaluationContract:
    """Build the evaluation contract from a platform learning context.

    Order of preference:
    1. explicit rubric fields on the knowledge package (if the teacher adds them);
    2. knowledge points derived from published entries (titled concepts);
    3. generic semantic fallback, marked as default.
    """
    package = context.get("knowledgePackage") or {}
    entries = package.get("entries") or []

    rubric = package.get("rubric") or context.get("evaluation")
    if isinstance(rubric, dict) and rubric.get("knowledgePoints"):
        points = [_point_from_rubric(item) for item in rubric["knowledgePoints"]]
        if points:
            return EvaluationContract(
                knowledge_points=points,
                completion_rule=rubric.get("completionRule", "student-mentions-core-concept"),
                is_default=False,
                source="published-rubric",
            )

    points: List[KnowledgePoint] = []
    for entry in entries:
        title = str(entry.get("title") or "").strip()
        if not title:
            continue
        concepts = _concepts_from_content(str(entry.get("content") or ""))
        points.append(KnowledgePoint(
            id=str(entry.get("id") or title),
            title=title,
            expected_concepts=concepts,
        ))
    if points:
        return EvaluationContract(
            knowledge_points=points,
            is_default=False,
            source="published-entries",
        )

    return EvaluationContract(
        knowledge_points=[KnowledgePoint(
            id=f"{context.get('courseId', 'course')}:core",
            title=str(context.get("courseTitle") or "本课主题"),
        )],
        source="default-semantic",
    )


def _point_from_rubric(item: Dict[str, Any]) -> KnowledgePoint:
    return KnowledgePoint(
        id=str(item.get("id") or item.get("title") or ""),
        title=str(item.get("title") or item.get("id") or ""),
        expected_concepts=[str(c) for c in (item.get("expectedConcepts") or [])][:_MAX_CONCEPTS_PER_POINT],
        misconceptions=[str(m) for m in (item.get("misconceptions") or [])],
    )


def _concepts_from_content(content: str) -> List[str]:
    """Use substantive statements, never treat document headings as answer evidence.

    Semantic concept extraction is performed by the question generator with
    the full published text. These statements are only fallback assessment hints.
    """
    concepts: List[str] = []
    for line in content.splitlines():
        if line.lstrip().startswith(("#", ">", "|")):
            continue
        text = line.strip().lstrip("*-— ").strip()
        if (not 25 <= len(text) <= 240 or not re.search(r"[。；：]", text)
                or any(word in text for word in ("使用说明", "课程名称", "填空题", "基础巩固层"))):
            continue
        if text not in concepts:
            concepts.append(text)
        if len(concepts) >= _MAX_CONCEPTS_PER_POINT:
            break
    return concepts
