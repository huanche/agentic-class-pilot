"""Per-class feedback derived from actual AI assessments, never invented scores."""
from __future__ import annotations

from datetime import datetime, timezone

from .progression import normalize


def lesson_feedback(session: dict) -> dict:
    dialogue = normalize(session["dialogue"])
    ended_early = dialogue.get("completion_reason") == "student_ended_early"
    unfinished_discussion_ids = set(
        (dialogue.get("discussion_point_ids") or [])[dialogue.get("discussion_index", 0):]
    ) if ended_early and dialogue["stage"] == "discuss" else set()
    entries = []
    for point in dialogue["points"]:
        history = point["assessment_history"]
        concept_history = [item for item in history if item.get("stage") not in {"discuss", "postclass_discuss"}]
        last_concept = concept_history[-1] if concept_history else None
        last_discussion = next((item for item in reversed(history)
                                if item.get("stage") in {"discuss", "postclass_discuss"}), None)
        # Earlier versions overwrote mastery with the discussion result. Recover
        # the actual recall/reinforcement result from the saved assessment history.
        concept_status = (last_concept.get("result") if last_concept and
                          last_concept.get("result") in
                          {"mastered", "partial", "misconception", "unanswered"}
                          else point["status"])
        discussion_result = point.get("discussion_result") or (last_discussion or {}).get("result")
        discussion_evidence = point.get("discussion_evidence") or (last_discussion or {}).get("evidence")
        discussion_needs_review = bool(discussion_result and discussion_result != "mastered")
        discussion_incomplete = (point["id"] in unfinished_discussion_ids or point.get("discussion_required", False)) and discussion_result != "mastered"
        excluded = point["excluded_from_discussion"] and not (
            concept_status == "mastered" and last_discussion)
        concept_evidence = (last_concept or {}).get("evidence") or point.get("evidence") or ""
        if excluded:
            category, label = "needs_review", "仍需巩固"
            suggestion = "建议重看相关视频片段，先理清概念和关键关系，再用自己的话复述。"
        elif (point.get("reinforcement_required") and not point["reinforce_done"]
              and point.get("mastered_in") != "postclass"):
            category, label = "incomplete", "强化确认未完成"
            suggestion = "首轮后期已讲清概念，还需要完成一次加强确认。"
        elif concept_status == "mastered":
            category = "mastered"
            label = ("课后补完" if point.get("mastered_in") == "postclass" else
                     "概念已掌握 · 讨论未完成" if discussion_incomplete else
                     "概念已掌握 · 讨论待巩固" if discussion_needs_review else
                     "加强后掌握" if point["mastered_in"] == "reinforce" else "掌握较好")
            suggestion = ("本课提前结束，当前深入讨论题尚未答对。"
                          if discussion_incomplete else
                          "概念复述已掌握；深入讨论题仍需巩固应用。"
                          if discussion_needs_review else "")
        elif not point["recall_attempts"] and concept_status == "unseen":
            category, label = "not_assessed", "尚未评估"
            suggestion = "本次尚未检查这个知识点，不能据此判断是否掌握。"
        else:
            category, label = "incomplete", "评估未完成"
            suggestion = "已开始复述，但课堂结束时尚未完成检查，建议继续梳理。"
        entries.append({
            "id": point["id"], "title": point["title"], "category": category,
            "label": label, "status": concept_status,
            "recallRounds": point["recall_attempts"],
            "reinforceRounds": point["reinforce_attempts"],
            "postclassRounds": point.get("postclass_rounds", 0),
            "evidence": concept_evidence,
            "assessments": history, "suggestion": suggestion,
            "excludedFromDiscussion": bool(excluded),
            "discussionResult": discussion_result,
            "discussionEvidence": discussion_evidence or "",
            "discussionNeedsReview": discussion_needs_review,
            "discussionIncomplete": discussion_incomplete,
            "masteredIn": point["mastered_in"],
        })
    counts = {key: sum(p["category"] == key for p in entries)
              for key in ("mastered", "needs_review", "incomplete", "not_assessed")}
    counts["postclass_completed"] = sum(p["masteredIn"] == "postclass" for p in entries)
    counts["discussion_needs_review"] = sum(
        p["discussionNeedsReview"] and not p["discussionIncomplete"] for p in entries)
    counts["discussion_incomplete"] = sum(p["discussionIncomplete"] for p in entries)
    context = session.get("context") or {}
    return {
        "schemaVersion": 3, "sessionId": session["id"], "studentId": context.get("userId"),
        "courseId": context.get("courseId"), "lessonId": session.get("lessonId"),
        "classroomId": session.get("classroomId"),
        "completedAt": (session.get("feedback") or {}).get("completedAt") or datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "postclassStage": session.get("postclassStage"),
        "recallRoundLimit": dialogue["recall_round_limit"],
        "reinforceRoundLimit": dialogue["reinforce_round_limit"],
        "points": entries, "counts": counts,
        "endedEarly": ended_early, "endedAtStage": dialogue.get("ended_at_stage"),
        "preparationCoverage": session.get("preparationCoverage"),
        "summary": (f"本次共涉及 {len(entries)} 个知识点：已掌握 {counts['mastered']} 个"
                    f"（其中课后补完 {counts['postclass_completed']} 个），"
                    f"概念仍需巩固 {counts['needs_review']} 个，讨论题待巩固 {counts['discussion_needs_review']} 个，"
                    f"讨论未完成 {counts['discussion_incomplete']} 个，"
                    f"评估未完成 {counts['incomplete']} 个，"
                    f"尚未评估 {counts['not_assessed']} 个。" +
                    ("本课由学生提前结束。" if ended_early else "")),
    }
