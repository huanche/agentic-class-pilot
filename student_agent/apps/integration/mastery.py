"""统一知识点掌握星级：模型描述表现，程序按证据与题目条件评分。"""

STAR_STATUS = {
    0: "未检测", 1: "需要重新理解", 2: "理解了一部分",
    3: "提示后能说清", 4: "能独立说清", 5: "能灵活应用",
}


def normalize_mastery_state(state: dict) -> dict:
    """旧会话沿用原综合记录，不把两套分数相加；删除独立辅导星字段。"""
    state.pop("tutoring_stars", None)
    state.setdefault("mastery_history", [])
    state.setdefault("mastery_needs_review", [])
    state.setdefault("mastery_contradictions", {})
    state["mastery_schema"] = "knowledge-mastery/2"
    return state


def assessed_stars(question: dict, verdict: str, assessment: dict) -> int | None:
    """不执行模型给出的分数，只接受带依据的表现类别。缺证据不评分。"""
    performance = assessment.get("performance")
    note = assessment.get("note")
    if not isinstance(performance, str) or not isinstance(note, str) or not note.strip():
        return None
    if verdict == "wrong":
        return {"incorrect": 1, "partial": 2}.get(performance)
    if verdict != "correct" or performance not in ("understood", "transfer"):
        return None
    if question.get("hint_given"):
        return 3
    if (performance == "transfer" and question.get("kind") == "application"
            and question.get("was_fresh") is True
            and isinstance(assessment.get("reasoning"), str)
            and assessment["reasoning"].strip()):
        return 5
    return 4


def record_assessment(state: dict, question: dict, verdict: str,
                      assessment: dict, answer: str) -> dict:
    """按表现更新唯一星级，累积证据；高星后连续答错标为需再次确认。"""
    kid = question.get("kp_id")
    catalog = (state.get("lesson_plan") or {}).get("knowledge_points") or []
    if not kid or kid not in {p.get("id") or p.get("kp_id") for p in catalog}:
        return {}
    score = assessed_stars(question, verdict, assessment)
    if score is None:
        return {}
    stars = dict(state.get("kp_stars") or {})
    old = int(stars.get(kid, 0))
    stars[kid] = max(old, score)
    counts = dict(state.get("mastery_contradictions") or {})
    review = list(state.get("mastery_needs_review") or [])
    if verdict == "wrong" and old >= 3:
        counts[kid] = counts.get(kid, 0) + 1
        if counts[kid] >= 2 and kid not in review:
            review.append(kid)
    elif verdict == "correct":
        counts[kid] = 0
        if not question.get("hint_given") and score >= old:
            review = [k for k in review if k != kid]
    evidence = {
        "kp_id": kid, "old_stars": old, "new_stars": stars[kid],
        "old_status": STAR_STATUS.get(old, "未检测"),
        "new_status": STAR_STATUS[stars[kid]], "source": "mastery-v2",
        "stage": state.get("host_phase"), "occurred_at": state.get("now"),
        "evidence": assessment["note"].strip()[:300],
        "performance": assessment["performance"], "verdict": verdict,
        "question": question.get("question", ""), "answer": answer,
        "hint_given": bool(question.get("hint_given")),
        "kind": question.get("kind", "basic"), "assessed_stars": score,
        "was_fresh": bool(question.get("was_fresh")),
        "reasoning": assessment.get("reasoning", ""),
    }
    return {"kp_stars": stars, "mastery_updates": [evidence],
            "mastery_history": [*(state.get("mastery_history") or []), evidence],
            "mastery_needs_review": review, "mastery_contradictions": counts}
