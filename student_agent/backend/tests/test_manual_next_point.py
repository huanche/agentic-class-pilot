from backend.teaching import typed_state


def test_manual_next_preserves_unanswered_point_for_reinforcement():
    points = [{"id": "first", "title": "第一点", "type": "memory",
               "details": {"statement": "事实一", "requiredElements": ["事实一"]}},
              {"id": "second", "title": "第二点", "type": "concept",
               "details": {"understandingPoints": ["理解二"]}}]
    state = typed_state.initial(points)
    changed = typed_state.skip_to_next(state)
    assert typed_state.current(changed)["id"] == "second"
    assert state["points"][0]["recall_done"] is False
    assert changed["points"][0]["recall_done"] is True
    assert changed["points"][0]["status"] != "mastered"
    assert changed["points"][0]["reinforcement_required"] is True
    assert changed["points"][0]["attempts"] == 0
    assert typed_state.next_point(changed) is None


def test_previous_and_next_can_review_completed_point_without_changing_mastery():
    points = [{"id": key, "title": key, "type": "memory",
               "details": {"statement": key, "requiredElements": [key]}} for key in ("first", "second", "third")]
    state = typed_state.initial(points)
    state["points"][0]["status"] = "mastered"
    state["points"][0]["recall_done"] = True
    state["selected_point_id"] = "second"
    previous = typed_state.go_to_previous(state)
    assert typed_state.current(previous)["id"] == "first"
    assert typed_state.next_point(previous)["id"] == "second"
    forward = typed_state.skip_to_next(previous)
    assert typed_state.current(forward)["id"] == "second"
    assert forward["points"][0]["status"] == "mastered"
