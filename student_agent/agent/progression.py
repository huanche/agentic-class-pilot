"""Deterministic, sequential learning progression; no model or database calls."""
from __future__ import annotations

import copy
import os

FLOW_VERSION = 3


def _limit(name: str, fallback: str, default: int) -> int:
    try:
        return max(1, min(20, int(os.environ.get(name, os.environ.get(fallback, str(default))))))
    except ValueError:
        return default


def recall_round_limit() -> int:
    return _limit("STUDENT_AGENT_RECALL_ROUNDS", "STUDENT_AGENT_RECALL_ROUNDS", 8)


def reinforce_round_limit() -> int:
    return _limit("STUDENT_AGENT_REINFORCE_ROUNDS", "STUDENT_AGENT_MAX_ROUNDS", 4)


def normalize(state: dict) -> dict:
    result = copy.deepcopy(state)
    result.setdefault("discussion_turns", 0)
    if result.get("flow_version") == FLOW_VERSION:
        for point in result["points"]:
            history = point.get("assessment_history") or []
            last_discussion = next((item for item in reversed(history)
                                    if item.get("stage") == "discuss"), None)
            last_concept = next((item for item in reversed(history)
                                 if item.get("stage") in {"recall", "reinforce", "postclass"}), None)
            if (last_discussion and last_concept
                    and last_concept.get("result") == "mastered"
                    and point.get("status") == last_discussion.get("result")
                    and point.get("excluded_from_discussion")):
                # Older flows replaced the mastered concept verdict with a
                # failed discussion answer. Restore the two separate results.
                point["status"] = "mastered"
                point["evidence"] = last_concept.get("evidence") or point.get("evidence")
                point["excluded_from_discussion"] = False
                point["discussion_result"] = last_discussion.get("result")
                point["discussion_evidence"] = last_discussion.get("evidence")
            # Repair late mastery in an active recall/reinforcement session saved by
            # the earlier flow, which marked reinforcement complete immediately.
            if (result.get("stage") in {"recall", "reinforce"}
                    and point.get("mastered_in") == "recall"
                    and point.get("recall_attempts", 0) > 5
                    and not point.get("reinforce_attempts", 0)):
                point["reinforce_done"] = False
                point["reinforcement_required"] = True
            point.setdefault("reinforcement_required", bool(
                point.get("recall_done") and not point.get("reinforce_done")))
    if result.get("stage") == "discuss":
        # Older sessions had a global discussion counter, but no per-point queue.
        # Give every eligible point its own question when they resume.
        result.setdefault("discussion_point_ids", [p["id"] for p in eligible_points(result["points"])])
        result.setdefault("discussion_index", 0)
        if result["discussion_index"] >= len(result["discussion_point_ids"]):
            result.update(stage="wrapup", completion_reason="all_points_discussed")
    if result.get("flow_version") == FLOW_VERSION:
        return result
    result.update(flow_version=FLOW_VERSION,
                  recall_round_limit=recall_round_limit(),
                  reinforce_round_limit=reinforce_round_limit(),
                  transition="continue")
    for point in result["points"]:
        mastered = point.get("status") == "mastered"
        attempts = max(0, int(point.get("attempts", 0)))
        point.update(
            recall_attempts=min(attempts, result["recall_round_limit"]),
            reinforce_attempts=0,
            recall_done=mastered or result["stage"] != "recall" or attempts >= result["recall_round_limit"],
            reinforce_done=mastered,
            reinforcement_required=not mastered and result["stage"] != "recall",
            mastered_in="previous" if mastered else None,
            excluded_from_discussion=False,
            assessment_history=[],
        )
    if result["stage"] != "wrapup":
        result["stage"] = next_stage(result["points"])
    return result


def next_stage(points: list[dict]) -> str:
    if any(not p["recall_done"] for p in points):
        return "recall"
    if any(p.get("reinforcement_required") and not p["reinforce_done"] for p in points):
        return "reinforce"
    return "discuss" if eligible_points(points) else "wrapup"


def eligible_points(points: list[dict]) -> list[dict]:
    return [p for p in points if p.get("status") == "mastered"
            and not (p.get("reinforcement_required") and not p.get("reinforce_done"))
            and not p.get("excluded_from_discussion", False)]


def current_point(state: dict) -> dict | None:
    stage = state["stage"]
    if stage == "recall":
        return next((p for p in state["points"] if not p["recall_done"]), None)
    if stage == "reinforce":
        return next((p for p in state["points"]
                     if p.get("reinforcement_required") and not p["reinforce_done"]), None)
    if stage == "discuss":
        ids = state.get("discussion_point_ids") or []
        index = state.get("discussion_index", 0)
        return next((p for p in state["points"] if p["id"] == ids[index]), None) if index < len(ids) else None
    return None


def advance(state: dict) -> dict:
    result = normalize(state)
    stage = result["stage"]
    points = result["points"]
    active = current_point(result)
    evaluations = {a["id"]: a for a in result["evaluation"].get("assessments", [])}
    result["transition"] = "continue"
    result["last_point_id"] = active["id"] if active else None
    result["strategy"] = "ask"
    if stage == "wrapup":
        return result
    targets = [active] if active else []
    for point in targets:
        assessment = evaluations.get(point["id"])
        if stage == "discuss" and not assessment:
            continue
        if not active and not assessment:
            continue
        outcome = assessment["result"] if assessment else "unclear"
        evidence = str((assessment or {}).get("evidence") or result.get("student_text") or "")[:1000]
        if stage in {"recall", "reinforce"}:
            counter = "recall_attempts" if stage == "recall" else "reinforce_attempts"
            point[counter] += 1
            point["attempts"] = point["recall_attempts"] + point["reinforce_attempts"]
        point["assessment_history"].append({
            "stage": stage, "round": point[counter] if stage in {"recall", "reinforce"} else
            sum(item.get("stage") == "discuss" for item in point["assessment_history"]) + 1,
            "result": outcome, "evidence": evidence,
            "studentText": result.get("student_text", ""),
        })
        if stage == "discuss":
            # Discussion checks application of an already learned concept. Keep
            # its result separate from the recall/reinforcement mastery verdict.
            point["discussion_result"] = outcome
            point["discussion_evidence"] = evidence
        else:
            point["evidence"] = evidence
        if stage != "discuss" and outcome in {"mastered", "partial", "misconception", "unanswered"}:
            point["status"] = outcome
        elif stage == "reinforce" and point["status"] == "mastered":
            # An unanswered confirmation must not retain the old mastery verdict.
            point["status"] = "unclear"
        elif point["status"] == "unseen":
            point["status"] = "unclear"
        if stage in {"recall", "reinforce"}:
            if outcome == "mastered":
                point["mastered_in"] = stage
                point["recall_done"] = True
                if stage == "recall":
                    point["reinforcement_required"] = point["recall_attempts"] > 5
                    point["reinforce_done"] = not point["reinforcement_required"]
                else:
                    point["reinforce_done"] = True
                result["transition"] = "mastered_next"
            elif point[counter] >= result["recall_round_limit" if stage == "recall" else "reinforce_round_limit"]:
                point["recall_done" if stage == "recall" else "reinforce_done"] = True
                if stage == "recall":
                    point["reinforcement_required"] = True
                point["excluded_from_discussion"] = stage == "reinforce"
                result["transition"] = "defer" if stage == "recall" else "record_gap"
            else:
                result["strategy"] = "hint"
        point["extended_reinforcement"] = (
            point["recall_attempts"] > 5 and point["status"] != "mastered"
        )
        if outcome == "misconception" and result["transition"] == "continue":
            result["strategy"] = "correct"
    if stage == "discuss":
        # Only a mastered answer completes this question. Other answers keep
        # the same focus and let the tutor help with the original question.
        assessment = evaluations.get(active["id"]) if active else None
        if assessment:
            result["discussion_turns"] += 1
        if assessment and assessment["result"] == "mastered":
            result["discussion_index"] += 1
            if result["discussion_index"] < len(result["discussion_point_ids"]):
                result["transition"] = "next_discussion_point"
        elif result["evaluation"].get("intent") == "question":
            result["strategy"] = "answer_question"
        elif assessment:
            result["strategy"] = "correct" if assessment["result"] == "misconception" else "hint"
        else:
            result["strategy"] = "clarify"
        if result["discussion_index"] >= len(result["discussion_point_ids"]):
            result.update(stage="wrapup", completion_reason="all_points_discussed")
    else:
        result["stage"] = next_stage(points)
        if result["stage"] == "discuss":
            result["discussion_point_ids"] = [p["id"] for p in eligible_points(points)]
            result["discussion_index"] = 0
    if result["stage"] == "wrapup":
        result.setdefault("completion_reason", "no_eligible_points")
    if result["stage"] != stage:
        result["transition"] = "enter_" + result["stage"]
    if result["transition"] == "continue" and result["evaluation"].get("intent") == "question":
        result["strategy"] = "answer_question"
    return result


def progress(state: dict) -> dict:
    current = normalize(state)
    points = current["points"]
    active = current_point(current)
    return {
        "total": len(points),
        "recallCompleted": sum(bool(p["recall_done"]) for p in points),
        "currentPoint": active["title"] if active else None,
        "reinforcementStarted": any(p["reinforce_attempts"] > 0 for p in points)
                                or current["stage"] == "reinforce",
        "discussionTurns": current.get("discussion_index", 0),
        "discussionLimit": len(current.get("discussion_point_ids") or eligible_points(points)),
        "completionReason": current.get("completion_reason"),
    }
