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
