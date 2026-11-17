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


@pytest.mark.parametrize("answer", range(4))
def test_generation_shuffles_options_with_answer_key(monkeypatch, answer):
    import json
    from backend.teaching import question_cards
    point = {"id": "p", "type": "memory", "requirements": [
        {"id": "r", "text": "事实", "status": "unconfirmed"}]}
    raw = {"questions": [{"prompt": "题", "options": ["一", "二", "三", "四"], "answer": answer,
                          "explanation": "正确是事实", "target_ids": ["r"]}]}
    import random
    monkeypatch.setattr(random, "shuffle", lambda values: values.reverse())
    group = generate(point, lambda *args: json.dumps(raw))
    expected = 3 - answer
    assert group["questions"][0]["answer"] == expected
    assert group["questions"][0]["options"][expected] == raw["questions"][0]["options"][answer]
    assert grade(group, {"q1": expected})["results"]["q1"]["correct"]
