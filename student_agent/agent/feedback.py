"""Per-class feedback derived from actual AI assessments, never invented scores."""
from __future__ import annotations

from datetime import datetime, timezone

from .progression import normalize


def lesson_feedback(session: dict) -> dict:
    dialogue = normalize(session["dialogue"])
    entries = []
    for point in dialogue["points"]:
        history = point["assessment_history"]
        if point["status"] == "mastered":
            category = "mastered"
            label = ("课后补完" if point.get("mastered_in") == "postclass" else
                     "加强后掌握" if point["mastered_in"] == "reinforce" else "掌握较好")
            suggestion = ""
        elif point["excluded_from_discussion"]:
            category, label = "needs_review", "仍需巩固"
            suggestion = "建议重看相关视频片段，先理清概念和关键关系，再用自己的话复述。"
        elif not point["recall_attempts"] and point["status"] == "unseen":
            category, label = "not_assessed", "尚未评估"
            suggestion = "本次尚未检查这个知识点，不能据此判断是否掌握。"
        else:
            category, label = "incomplete", "评估未完成"
            suggestion = "已开始复述，但课堂结束时尚未完成检查，建议继续梳理。"
        entries.append({
            "id": point["id"], "title": point["title"], "category": category,
            "label": label, "status": point["status"],
            "recallRounds": point["recall_attempts"],
            "reinforceRounds": point["reinforce_attempts"],
            "postclassRounds": point.get("postclass_rounds", 0),
            "evidence": point.get("evidence") or "",
            "assessments": history, "suggestion": suggestion,
            "excludedFromDiscussion": point["excluded_from_discussion"],
            "masteredIn": point["mastered_in"],
        })
    counts = {key: sum(p["category"] == key for p in entries)
              for key in ("mastered", "needs_review", "incomplete", "not_assessed")}
    counts["postclass_completed"] = sum(p["masteredIn"] == "postclass" for p in entries)
    context = session.get("context") or {}
    return {
        "schemaVersion": 1, "sessionId": session["id"], "studentId": context.get("userId"),
        "courseId": context.get("courseId"), "lessonId": session.get("lessonId"),
        "classroomId": session.get("classroomId"),
        "completedAt": (session.get("feedback") or {}).get("completedAt") or datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "postclassStage": session.get("postclassStage"),
        "recallRoundLimit": dialogue["recall_round_limit"],
        "reinforceRoundLimit": dialogue["reinforce_round_limit"],
        "points": entries, "counts": counts,
        "summary": (f"本次共涉及 {len(entries)} 个知识点：已掌握 {counts['mastered']} 个"
                    f"（其中课后补完 {counts['postclass_completed']} 个），"
                    f"仍需巩固 {counts['needs_review']} 个，评估未完成 {counts['incomplete']} 个，"
                    f"尚未评估 {counts['not_assessed']} 个。"),
    }
