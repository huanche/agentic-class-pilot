import pytest
from backend.teaching.question_cards import generate, grade, public_group, validate_group


def test_partial_grade_preserves_unanswered_and_hides_key():
    point = {"id": "p", "type": "memory", "requirements": [{"id": "r"}]}
    item = {"prompt": "题目", "options": ["是", "否"], "answer": 0,
            "explanation": "依据", "target_ids": ["r"]}
    group = validate_group({"questions": [item, item]}, point)
    assert "answer" not in public_group(group)["questions"][0]
    updated = grade(group, {"q1": 1})
    assert updated["results"]["q1"]["correct"] is False
    assert "q2" not in updated["results"]
    assert group["results"] == {}
    with pytest.raises(ValueError):
        grade(updated, {"q1": 0})


def test_rejects_ambiguous_options_and_unknown_requirements():
    point = {"id": "p", "type": "memory", "requirements": [{"id": "r"}]}
    item = {"prompt": "题", "options": ["是", "是"], "answer": 0,
            "explanation": "依据", "target_ids": ["r"]}
    with pytest.raises(ValueError):
        validate_group({"questions": [item]}, point)
    item.update(options=["是", "否"], target_ids=["other"])
    with pytest.raises(ValueError):
        validate_group({"questions": [item]}, point)


def test_generated_questions_cannot_target_already_mastered_requirements():
    point = {"id": "p", "type": "memory", "title": "题", "details": {}, "requirements": [
        {"id": "done", "text": "已掌握", "status": "demonstrated"},
        {"id": "open", "text": "待确认", "status": "unconfirmed"}]}
    raw = '{"questions":[{"prompt":"题","options":["是","否"],"answer":0,"explanation":"依据","target_ids":["done"]}]}'
    with pytest.raises(ValueError):
        generate(point, lambda _system, _user: raw)
