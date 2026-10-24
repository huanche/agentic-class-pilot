import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.postclass import apply_assessment, pending_points, postclass_stage


def test_postclass_completes_only_the_active_gap():
    points = [
        {"id": "a", "title": "A", "status": "partial", "excluded_from_discussion": True,
         "assessment_history": [], "recall_attempts": 8, "reinforce_attempts": 4},
        {"id": "b", "title": "B", "status": "mastered", "excluded_from_discussion": False,
         "assessment_history": [], "recall_attempts": 2, "reinforce_attempts": 0},
    ]
    assert [point["id"] for point in pending_points(points)] == ["a"]
    assert postclass_stage(points) == "remediation"
    updated = apply_assessment(points, "a", {"result": "mastered", "evidence": "学生独立解释"}, "我的复述")
    assert updated[0]["status"] == "mastered"
    assert updated[0]["mastered_in"] == "postclass"
    assert updated[0]["excluded_from_discussion"] is False
    assert updated[0]["postclass_rounds"] == 1
    assert postclass_stage(updated) == "open"
    assert points[0]["status"] == "partial"


def test_confirmation_and_discussion_must_both_finish():
    from agent.postclass import pending_kind, advance
    point = {"id": "a", "title": "A", "status": "mastered", "reinforcement_required": True,
             "reinforce_done": False, "discussion_required": True, "assessment_history": []}
    state = advance({"points": [point], "stage": "remediation", "student_text": "explanation",
                     "assessment": {"result": "mastered"}})
    assert state["transition"] == "next"
    assert pending_kind(state["points"][0]) == "discussion"
    failed = apply_assessment(state["points"], "a", {"result": "unanswered"}, "I do not know")
    assert failed[0]["status"] == "mastered"
    assert postclass_stage(failed) == "remediation"
    finished = apply_assessment(failed, "a", {"result": "mastered"}, "correct answer")
    assert postclass_stage(finished) == "open"
    assert finished[0]["assessment_history"][-1]["stage"] == "postclass_discuss"


def test_early_end_queues_unattempted_discussion_without_another_points_question():
    from agent.postclass import prepare_points, pending_kind
    points = [{"id": key, "status": "mastered"} for key in ("a", "b")]
    prepared = prepare_points({"points": points, "discussion_point_ids": ["a", "b"],
                               "discussion_index": 0}, [{"phase": "discuss", "text": "question A"}])
    assert [pending_kind(p) for p in prepared] == ["discussion", "discussion"]
    assert prepared[0]["discussion_context"]
    assert prepared[1]["discussion_context"] == []
    assert "discussion_required" not in points[0]
