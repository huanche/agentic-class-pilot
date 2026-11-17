from copy import deepcopy
import json

from backend.teaching import learner_feedback, service, card_teaching, question_cards


def test_reports_preserve_text_and_context_without_changing_grades():
    dialogue = service.new_dialogue([{"id": "p", "title": "定义", "type": "memory",
        "details": {"statement": "定义", "requiredElements": ["事实"]}}])
    dialogue["question_groups"] = [{"id": "g", "point_id": "p", "questions": [], "results": {}}]
    dialogue["student_text"] = "这题太简单，而且答案有错误"
    original = deepcopy(dialogue)
    learner_feedback.record(dialogue)
    reports = dialogue.pop("learner_reports")
    assert dialogue == original
    report = json.loads(json.dumps(reports))[0]
    assert report["categories"] == ["too_easy", "reported_error"]
    assert report["text"] == original["student_text"]
    assert report["point_id"] == "p" and report["group_id"] == "g"
    assert report["status"] == "unreviewed"
    dialogue["learner_reports"] = reports
    public = service.describe_session({"dialogue": dialogue, "phase": "discussion"})
    assert "learner_reports" not in public


def test_student_error_is_not_a_question_error_report():
    dialogue = {"student_text": "我答错了，现在明白了"}
    learner_feedback.record(dialogue)
    assert "learner_reports" not in dialogue


def test_card_chat_persists_report_with_session_without_exposing_it(monkeypatch):
    dialogue = service.new_dialogue([{"id": "p", "title": "定义", "type": "memory",
        "details": {"statement": "定义", "requiredElements": ["事实"]}}])
    group = question_cards.validate_group({"questions": [{"prompt": "事实？",
        "options": ["是", "否"], "answer": 0, "explanation": "原因",
        "target_ids": ["requiredElements:1"]}]}, dialogue["points"][0])
    dialogue["question_groups"] = [group]
    session = {"dialogue": dialogue, "phase": "discussion", "messages": []}
    before = deepcopy(session)
    monkeypatch.setattr(card_teaching.model, "complete", lambda *args: "已收到你的反馈。")
    changed = service.classroom_turn(session, "这题太简单")
    assert session == before
    restored = json.loads(json.dumps(dict(session, **changed)))
    assert restored["dialogue"]["learner_reports"][0]["group_id"] == group["id"]
    assert restored["dialogue"]["points"] == before["dialogue"]["points"]
    assert restored["dialogue"]["question_groups"][0]["results"] == {}
    assert "learner_reports" not in service.describe_session(restored)
