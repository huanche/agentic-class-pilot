import json
from copy import deepcopy
from backend.teaching import service, card_teaching
from backend.evidence import records


def test_group_partial_submission_restore_and_completion(monkeypatch):
    point = {"id": "p", "title": "定义", "type": "memory", "details": {
        "statement": "两个事实", "requiredElements": ["事实一", "事实二"]}}
    base = {"id": "card-session", "phase": "video", "lessonId": "lesson", "videoRevision": "r",
            "courses": [], "messages": [], "preparation": "ready", "stateVersion": 1,
            "dialogue": service.new_dialogue([point])}
    raw = {"questions": [{"prompt": f"问题{i}", "options": ["对", "错"], "answer": 0,
                         "explanation": f"解析{i}", "target_ids": [f"requiredElements:{i}"]} for i in (1, 2)]}
    monkeypatch.setattr(card_teaching.model, "complete", lambda *args: json.dumps(raw))
    base = records.normalize(base)
    opened = records.transition(base, dict(base, **service.start_discussion(base)))
    group = opened["dialogue"]["question_groups"][0]
    from backend.session.command_runtime import validate
    validate(opened, "submit_answer", {"text": "提交题卡作答", "cardId": group["id"],
             "taskId": opened["currentTaskId"], "answers": {"q1": 0}})
    public = service.describe_session(opened)["questionGroups"][0]
    assert all("answer" not in q and "explanation" not in q for q in public["questions"])
    changed = service.card_turn(opened, group["id"], {"q1": 0})
    partial = records.transition(opened, dict(opened, **changed))
    assert partial["dialogue"]["points"][0]["status"] != "mastered"
    restored = json.loads(json.dumps(partial))
    assert len(service.describe_session(restored)["questionGroups"][0]["results"]) == 1
    final = records.transition(restored, dict(restored, **service.card_turn(restored, group["id"], {"q2": 0})))
    assert final["dialogue"]["points"][0]["status"] == "mastered"
    assert final["dialogue"]["stage"] == "wrapup"
