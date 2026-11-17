import json
from copy import deepcopy
from uuid import uuid4

from fastapi.testclient import TestClient
from backend import main
from backend.teaching import service, card_teaching
from backend.evidence import records
from backend.infrastructure import persistence


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
    assert opened["messages"][-1]["cardId"] == group["id"]
    from backend.session.command_runtime import validate
    validate(opened, "submit_answer", {"text": "提交题卡作答", "cardId": group["id"],
             "taskId": opened["currentTaskId"], "answers": {"q1": 0}})
    public = service.describe_session(opened)["questionGroups"][0]
    assert public["phase"] == "discussion"
    assert all("answer" not in q and "explanation" not in q for q in public["questions"])
    changed = service.card_turn(opened, group["id"], {"q1": 0})
    partial = records.transition(opened, dict(opened, **changed))
    assert partial["messages"] == opened["messages"]
    assert partial["dialogue"]["points"][0]["status"] != "mastered"
    restored = json.loads(json.dumps(partial))
    assert len(service.describe_session(restored)["questionGroups"][0]["results"]) == 1
    final = records.transition(restored, dict(restored, **service.card_turn(restored, group["id"], {"q2": 0})))
    assert final["dialogue"]["points"][0]["status"] == "mastered"
    assert final["dialogue"]["stage"] == "wrapup"
    assert final["dialogue"]["review_point_id"] == "p"
    assert len(final["dialogue"]["question_groups"]) == 1
    assert final["messages"] == opened["messages"]
    assert service.describe_session(json.loads(json.dumps(final)))["questionGroups"][0]["results"]["q2"]["explanation"] == "解析2"
    validate(final, "submit_answer", {"text": "为什么是这个答案？", "taskId": final["currentTaskId"]})
    monkeypatch.setattr(card_teaching.model, "complete", lambda *args: "因为题目中的条件如此。")
    helped = service.classroom_turn(final, "为什么是这个答案？")
    assert helped["messages"][-1]["text"] == "因为题目中的条件如此。"
    assert helped["dialogue"]["review_point_id"] == "p"


def test_formal_command_submits_card_without_student_chat_bubble(pg, monkeypatch):
    monkeypatch.setenv("PLATFORM_TO_STUDENT_KEY", "card-test-key")
    raw = {"questions": [{"prompt": "Push 的作用？", "options": ["插入", "删除"],
                          "answer": 0, "explanation": "Push 将元素放入栈中。",
                          "target_ids": ["requiredElements:1"]}]}
    monkeypatch.setattr(card_teaching.model, "complete", lambda *args: json.dumps(raw))
    sid = "card-" + uuid4().hex
    point = {"id": "push", "title": "Push", "type": "memory",
             "details": {"statement": "Push 是插入操作", "requiredElements": ["Push 是插入操作"]},
             "content": "Push 是插入操作", "description": "Push 是插入操作"}
    persistence.save({"id": sid, "phase": "video", "lessonId": "lesson", "classroomId": "room",
        "context": {"userId": "student", "courseId": "course", "publication": {"id": "pub", "version": 1}},
        "videoRevision": "revision", "messages": [], "courses": [], "preparation": "ready",
        "dialogue": service.new_dialogue([point])}, 0)
    client = TestClient(main.app, headers={"X-Platform-Learning-Key": "card-test-key",
        "X-Platform-Protocol": "platform-cookie-v1", "X-Platform-User-Id": "student",
        "X-Platform-Course-Id": "course"})

    def command(kind, payload):
        view = client.get(f"/api/session/{sid}").json()
        response = client.post(f"/api/session/{sid}/commands", json={"commandId": uuid4().hex,
            "type": kind, "payload": payload, "expectedStateVersion": view["stateVersion"],
            "contentGeneration": view["contentGeneration"]})
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["status"] == "completed", receipt
        return receipt["sessionView"]

    opened = command("start_discussion", {})
    group = opened["questionGroups"][0]
    assert opened["messages"][-1]["cardId"] == group["id"]
    answered = command("submit_answer", {"text": "提交题卡作答", "taskId": opened["currentTaskPublic"]["taskId"],
        "cardId": group["id"], "answers": {"q1": 0}})
    assert answered["messages"] == opened["messages"]
    assert answered["questionGroups"][0]["results"]["q1"]["explanation"] == "Push 将元素放入栈中。"
