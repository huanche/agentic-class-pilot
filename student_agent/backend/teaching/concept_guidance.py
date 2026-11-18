"""One guided attempt per unresolved concept scope, then direct explanation."""


def select_action(point, pending, evaluation, student_text, *, changed, fallback):
    history = point["assessment_history"]
    observation = evaluation.get("observation") or {}
    if (point.get("type") != "concept" or not history or changed
            or observation.get("control", "none") != "none"):
        return fallback
    targets = {r["id"] for r in pending}
    hinted = any(item.get("planned_action") == "concept_hint"
                 and targets.intersection(item.get("target_ids", []))
                 for item in point.get("question_history", []))
    attempted = history[-1].get("answer_assessment") is not None
    difficulty = bool(observation.get("help_quote") or observation.get("teacher_feedback")
                      or evaluation.get("intent") == "question" or any(
                          phrase in student_text for phrase in
                          ("说不清", "不清楚", "不会", "不明白", "不懂", "不记得")))
    # A student's attempt or difficulty after a hint must not re-enter clarification.
    if hinted and (attempted or difficulty):
        return "concept_explain"
    if (observation.get("help_quote") or observation.get("teacher_feedback")
            or evaluation.get("intent") == "question"):
        return fallback
    if attempted or difficulty:
        result = history[-1]["result"]
        if result == "unanswered":
            return "concept_explain"
        if result in {"unclear", "partial", "misconception"}:
            return "concept_hint"
    return fallback
