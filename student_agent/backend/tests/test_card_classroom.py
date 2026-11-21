import json
import pytest
from copy import deepcopy
from uuid import uuid4

from fastapi.testclient import TestClient
from backend import main
from backend.teaching import service, card_teaching
from backend.evidence import records
from backend.infrastructure import persistence


@pytest.fixture(autouse=True)
def stable_option_order(monkeypatch):
    monkeypatch.setattr(card_teaching.question_cards.random, "shuffle", lambda values: None)


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
    monkeypatch.setattr(card_teaching.model, "complete", lambda *args: json.dumps({"reply":"因为题目中的条件如此。","assisted_question_ids":[]}))
    helped = service.classroom_turn(final, "为什么是这个答案？")
    assert helped["messages"][-1]["text"] == "因为题目中的条件如此。"
    assert helped["dialogue"]["review_point_id"] == "p"


@pytest.mark.parametrize(("after_class", "request_text"), [
    (False, "下一个知识点"),
    (False, "老师，我懂了，去下个知识点吧"),
    (True, "能不能换个知识点？"),
])
def test_chat_navigation_reuses_button_with_pending_card(monkeypatch, after_class, request_text):
    points = [{"id": key, "title": key, "type": "memory",
               "details": {"statement": key, "requiredElements": [key]}}
              for key in ("first", "second")]
    base = {"id": "chat-navigation", "phase": "video", "lessonId": "lesson",
            "videoRevision": "r", "messages": [], "dialogue": service.new_dialogue(points)}
    raw = {"questions": [{"prompt": "当前题目？", "options": ["对", "错"], "answer": 0,
                         "explanation": "解析", "target_ids": ["requiredElements:1"]}]}
    monkeypatch.setattr(card_teaching.model, "complete", lambda *args: json.dumps(raw))
    opened = dict(base, **service.start_discussion(base))
    if after_class:
        opened = dict(opened, **service.finish(opened))
        opened = dict(opened, **service.start_postclass(opened))
    opened = records.normalize(opened)
    turn = service.postclass_turn if after_class else service.classroom_turn

    original = deepcopy(opened)
    button = service.navigate_point_turn(opened)
    changed = turn(opened, request_text)
    moved = records.transition(opened, dict(opened, **changed))
    assert opened == original
    assert moved["dialogue"]["current_task"]["pointId"] == "second"
    assert moved["dialogue"]["points"] == button["dialogue"]["points"]
    public_groups = service.describe_session(moved)["questionGroups"]
    assert [(g["point_id"], g["active"]) for g in public_groups] == [("first", False), ("second", True)]
    assert moved["messages"][-2]["text"] == request_text
    assert moved["messages"][-2]["role"] == "student"
    assert moved["messages"][-1]["cardId"] == public_groups[1]["id"]
    assert moved["dialogue"]["points"][0]["assessment_history"] == []
    assert moved["dialogue"]["points"][0]["status"] != "mastered"

    monkeypatch.setattr(card_teaching.model, "complete", lambda *args: pytest.fail("No next point to generate"))
    stayed = turn(moved, "请进入下一个知识点")
    assert stayed["messages"][-1]["text"] == "本课没有下一个知识点了。"
    assert stayed["dialogue"]["current_task"] == moved["dialogue"]["current_task"]
    assert stayed["dialogue"]["points"] == moved["dialogue"]["points"]


@pytest.mark.parametrize("text", ["继续", "别去下一个知识点", "你说的「下一点」是什么意思？"])
def test_chat_navigation_requires_an_explicit_request(monkeypatch, text):
    points = [{"id": key, "title": key, "type": "memory",
               "details": {"statement": key, "requiredElements": [key]}}
              for key in ("first", "second")]
    base = {"phase": "video", "messages": [], "dialogue": service.new_dialogue(points)}
    raw = {"questions": [{"prompt": "当前题目？", "options": ["对", "错"], "answer": 0,
                         "explanation": "解析", "target_ids": ["requiredElements:1"]}]}
    monkeypatch.setattr(card_teaching.model, "complete", lambda *args: json.dumps(raw))
    opened = dict(base, **service.start_discussion(base))
    monkeypatch.setattr(card_teaching.model, "complete", lambda *args: json.dumps(
        {"reply": "接着当前题卡。", "assisted_question_ids": []}))
    stayed = service.classroom_turn(opened, text)
    assert stayed["dialogue"]["current_task"] == opened["dialogue"]["current_task"]
    assert stayed["messages"][-1]["text"] == "接着当前题卡。"


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


@pytest.mark.parametrize("complete_group", [False, True])
def test_card_help_receives_submitted_choices_after_restore(monkeypatch, complete_group):
    point = {"id": "p", "title": "定义", "type": "memory", "details": {
        "statement": "两个事实", "requiredElements": ["事实一", "事实二"]}}
    base = {"phase": "video", "messages": [], "dialogue": service.new_dialogue([point])}
    raw = {"questions": [{"prompt": f"问题{i}", "options": ["对", "错"], "answer": 0,
                         "explanation": f"解析{i}", "target_ids": [f"requiredElements:{i}"]} for i in (1, 2)]}
    monkeypatch.setattr(card_teaching.model, "complete", lambda *args: json.dumps(raw))
    opened = dict(base, **service.start_discussion(base))
    group = opened["dialogue"]["question_groups"][0]
    answers = {"q1": 1, "q2": 0} if complete_group else {"q1": 1}
    partial = dict(opened, **service.card_turn(opened, group["id"], answers))
    restored = json.loads(json.dumps(partial))
    captured = []
    def complete(system, user):
        captured.append(json.loads(user))
        return json.dumps({"reply": "你选择了 B：错。", "assisted_question_ids": []})
    monkeypatch.setattr(card_teaching.model, "complete", complete)
    service.classroom_turn(restored, "我的作答是什么？")
    assert captured[0]["questionGroups"][0]["results"]["q1"]["choice"] == 1
    assert captured[0]["currentQuestionGroup"]["id"] == group["id"]
    assert ("q2" in captured[0]["questionGroups"][0]["results"]) == complete_group


def test_postclass_resumes_same_partial_card_and_accepts_remaining_answer(monkeypatch):
    point = {"id": "p", "title": "facts", "type": "memory", "details": {
        "statement": "two facts", "requiredElements": ["first", "second"]}}
    base = {"phase": "video", "messages": [], "dialogue": service.new_dialogue([point])}
    raw = {"questions": [{"prompt": f"question{i}", "options": ["yes", "no"], "answer": 0,
                         "explanation": "reason", "target_ids": [f"requiredElements:{i}"]} for i in (1, 2)]}
    monkeypatch.setattr(card_teaching.model, "complete", lambda *args: json.dumps(raw))
    opened = dict(base, **service.start_discussion(base))
    group_id = opened["dialogue"]["question_groups"][0]["id"]
    partial = dict(opened, **service.card_turn(opened, group_id, {"q1": 0}))
    ended = dict(partial, **service.finish(partial))
    resumed = dict(ended, **service.start_postclass(ended))
    assert resumed["messages"][-1]["cardId"] == group_id
    assert len(resumed["dialogue"]["question_groups"]) == 1
    assert resumed["dialogue"]["question_groups"][0]["results"]["q1"]["correct"]
    restored = json.loads(json.dumps(resumed))
    completed = service.card_turn(restored, group_id, {"q2": 0})
    assert completed["dialogue"]["points"][0]["status"] == "mastered"
    # Only the latest group at the focus is actionable; older groups are history.
    newer = deepcopy(resumed["dialogue"]["question_groups"][0])
    newer["id"] = "newer-group"
    resumed["dialogue"]["question_groups"].append(newer)
    assert [g["id"] for g in service.describe_session(resumed)["questionGroups"] if g["active"]] == ["newer-group"]

@pytest.mark.parametrize("hints, expected", [([], ["demonstrated", "demonstrated"]),
    (["q1"], ["unconfirmed", "demonstrated"]), (["q1", "q2"], ["unconfirmed", "unconfirmed"])])
def test_help_only_affects_hinted_questions(monkeypatch, hints, expected):
    point = {"id": "p", "title": "定义", "type": "memory", "details": {
        "statement": "两个事实", "requiredElements": ["事实一", "事实二"]}}
    base = {"phase": "video", "messages": [], "dialogue": service.new_dialogue([point])}
    raw = {"questions": [{"prompt": f"问题{i}", "options": ["对", "错"], "answer": 0,
                         "explanation": f"解析{i}", "target_ids": [f"requiredElements:{i}"]} for i in (1, 2)]}
    monkeypatch.setattr(card_teaching.model, "complete", lambda *args: json.dumps(raw))
    opened = dict(base, **service.start_discussion(base))
    monkeypatch.setattr(card_teaching.model, "complete", lambda *args: json.dumps(
        {"reply": "课堂答复", "assisted_question_ids": hints}))
    helped = dict(opened, **service.classroom_turn(opened, "请帮忙"))
    group = helped["dialogue"]["question_groups"][0]
    result = service.card_turn(helped, group["id"], {"q1": 0, "q2": 0})
    focus = result["dialogue"]["points"][0]
    assert [r["status"] for r in focus["requirements"]] == expected
    assert focus["assessment_history"][-1]["result"] == ("assisted_correct" if hints else "correct")


@pytest.mark.parametrize("first_choice", [0, 1])
def test_shared_requirement_cites_same_answers_after_split_submission(monkeypatch, first_choice):
    point = {"id": "p", "title": "定义", "type": "memory", "details": {
        "statement": "一个事实", "requiredElements": ["事实一"]}}
    base = {"phase": "video", "messages": [], "dialogue": service.new_dialogue([point])}
    raw = {"questions": [{"prompt": f"问题{i}", "options": ["对", "错"], "answer": 0,
                         "explanation": f"解析{i}", "target_ids": ["requiredElements:1"]} for i in (1, 2)]}
    monkeypatch.setattr(card_teaching.model, "complete", lambda *args: json.dumps(raw))
    opened = dict(base, **service.start_discussion(base))
    group_id = opened["dialogue"]["question_groups"][0]["id"]
    together = service.card_turn(opened, group_id, {"q1": first_choice, "q2": 0})
    first = dict(opened, **service.card_turn(opened, group_id, {"q1": first_choice}))
    split = service.card_turn(json.loads(json.dumps(first)), group_id, {"q2": 0})
    combined_point = together["dialogue"]["points"][0]
    split_point = split["dialogue"]["points"][0]
    combined_req = combined_point["requirements"][0]
    split_req = split_point["requirements"][0]
    assert split_req["status"] == combined_req["status"] == ("needs_help" if first_choice else "demonstrated")
    assert [source["quote"] for source in split_req["sources"]] == [
        source["quote"] for source in combined_req["sources"]]
    assert [source["turn"] for source in split_req["sources"]] == ([1] if first_choice else [1, 2])
    if first_choice:
        assert combined_point["assessment_history"][-1]["result"] == "partial"
        assert split_point["assessment_history"][0]["result"] == "incorrect"
        assert "问题1" in split_req["gap"]
