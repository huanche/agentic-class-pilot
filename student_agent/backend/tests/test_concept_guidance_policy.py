import json
import pytest
from backend.teaching import typed_state


def _state():
    return typed_state.initial([{"id": "p", "title": "关系", "type": "concept",
        "details": {"understandingPoints": ["解释原因"]}}])


def test_one_hint_then_explanation_for_same_unresolved_requirement():
    state = _state()
    state["student_text"] = "我说不清"
    state = typed_state.advance(state, "unclear", None, observation={})
    plan = typed_state.teaching_plan(state)
    assert plan["action"] == "concept_hint"
    assert plan["solicitation"] == "one_task"
    state["points"][0]["question_history"].append({
        "planned_action": plan["action"], "target_ids": plan["target_ids"]})
    state["student_text"] = "还是说不清"
    state = typed_state.advance(state, "unclear", None, observation={})
    plan = typed_state.teaching_plan(state)
    assert plan["action"] == "concept_explain"
    assert plan["solicitation"] == "none"
    assert state["points"][0]["requirements"][0]["status"] == "unconfirmed"


@pytest.mark.parametrize("observation", [
    {"help_quote": "还是不懂"},
    {"teacher_feedback": "还是不懂"},
    {"help_quote": "还是不懂", "teacher_feedback": "还是不懂"},
])
def test_difficulty_after_restored_hint_overrides_old_clarification(observation):
    state = _state()
    point = state["points"][0]
    point["question_history"].append({"planned_action": "concept_hint",
        "target_ids": [r["id"] for r in point["requirements"]]})
    state = json.loads(json.dumps(state))
    state["student_text"] = "还是不懂"
    state = typed_state.advance(state, "question", None, observation=observation)
    plan = typed_state.teaching_plan(state)
    assert plan["action"] == "concept_explain"
    assert plan["solicitation"] == "none"


def test_pause_after_hint_still_respects_student_control():
    state = _state()
    point = state["points"][0]
    point["question_history"].append({"planned_action": "concept_hint",
        "target_ids": [r["id"] for r in point["requirements"]]})
    state["student_text"] = "暂停"
    state = typed_state.advance(state, "unclear", None,
        observation={"control": "pause", "control_quote": "暂停"})
    assert typed_state.teaching_plan(state)["action"] == "respond"
