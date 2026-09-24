"""Course-grounded prompt helpers for platform-launched learning sessions.

This module is the only place where published platform course data is turned
into tutor prompts.  The orchestrator keeps its phase and timing decisions;
these helpers only provide factual context, questions and hints.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional


def is_platform_plan(plan: Dict[str, Any]) -> bool:
    return plan.get("source") == "platform-published"


def segment_by_id(plan: Dict[str, Any], segment_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not segment_id or not is_platform_plan(plan):
        return None
    return next((item for item in plan.get("segments", []) if item.get("id") == segment_id), None)


def knowledge_point(plan: Dict[str, Any], kp_id: str) -> Optional[Dict[str, Any]]:
    if not is_platform_plan(plan):
        return None
    return next((item for item in plan.get("knowledge_points", []) if item.get("id") == kp_id), None)


def knowledge_title(plan: Dict[str, Any], kp_id: str) -> Optional[str]:
    item = knowledge_point(plan, kp_id)
    return str(item.get("title") or kp_id) if item else None


def tutor_context(state: Dict[str, Any], *, max_chars: int = 12000) -> str:
    """Return a compact, published-only factual context for one LLM call."""
    plan = state.get("lesson_plan") or {}
    if not is_platform_plan(plan):
        return ""

    segments = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "content": item.get("content"),
        }
        for item in plan.get("segments", [])
    ]
    points = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "expected": item.get("expected") or [],
            "misconceptions": item.get("misconceptions") or [],
        }
        for item in plan.get("knowledge_points", [])
    ]
    payload = {
        "course": plan.get("title"),
        "publication": {
            "id": plan.get("publication_id"),
            "version": plan.get("publication_version"),
        },
        "currentSegment": segment_by_id(plan, state.get("active_segment_id")),
        "segments": segments,
        "knowledgePoints": points,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))[:max_chars]


def question_queue(
    phase: str,
    plan: Dict[str, Any],
    unresolved: Iterable[str],
) -> List[Dict[str, str]]:
    """Build deterministic questions from the published evaluation contract."""
    if not is_platform_plan(plan):
        return []
    by_id = {str(item.get("id")): item for item in plan.get("knowledge_points", [])}
    ordered_ids = list(dict.fromkeys([*unresolved, *by_id.keys()]))
    questions: List[Dict[str, str]] = []
    for kp_id in ordered_ids:
        item = by_id.get(str(kp_id))
        if not item:
            continue
        title = str(item.get("title") or kp_id)
        expected = [str(value) for value in item.get("expected") or [] if str(value).strip()]
        if phase == "recap_discussion":
            suffix = f"，并说明{'、'.join(expected[:3])}" if expected else ""
            question = f"请用自己的话说明“{title}”的核心内容{suffix}。"
        else:
            anchor = f"，结合{'、'.join(expected[:2])}" if expected else ""
            question = f"为什么“{title}”很重要？它在实际学习或应用中如何发挥作用{anchor}？"
        questions.append({
            "kp_id": str(kp_id),
            "question": question,
            "source": "platform-published evaluation contract",
        })
    return questions


def hint(plan: Dict[str, Any], kp_id: str) -> Optional[str]:
    item = knowledge_point(plan, kp_id)
    if not item:
        return None
    expected = [str(value) for value in item.get("expected") or [] if str(value).strip()]
    if expected:
        return f"可以从这些关键词展开：{'、'.join(expected[:3])}。"
    return f"先回到“{item.get('title') or kp_id}”的定义和课堂讲解，再举一个例子。"
