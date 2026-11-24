"""Continuous dialogue through the session interface and the real model adapter."""
import json
from uuid import uuid4

import httpx
from openai import DefaultHttpxClient
import pytest

from backend.evidence import records
from backend.teaching import service


POINTS = [
    {"id": "A", "title": "栈", "type": "concept", "details": {"explanation": "栈的删除顺序。", "understandingPoints": ["后进先出"]}},
    {"id": "B", "title": "队列", "type": "concept", "details": {"explanation": "队列的删除顺序。", "understandingPoints": ["先进先出", "从队首删除"]}},
]


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("STUDENT_AGENT_API_KEY", "offline-key")
    monkeypatch.setenv("STUDENT_AGENT_BASE_URL", "https://dialogue.test/v1")
    packets, inputs = [], []

    def send(self, request, **kwargs):
        body = json.loads(request.content)
        inputs.append(json.loads(body["messages"][-1]["content"]))
        payload = packets.pop(0)
        return httpx.Response(200, request=request, json={"id": "offline", "object": "chat.completion",
            "created": 0, "model": "offline", "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)}}]})

    monkeypatch.setattr(DefaultHttpxClient, "send", send)
    return packets, inputs


def lesson():
    dialogue = service.new_dialogue(POINTS)
    dialogue["dialogue_version"] = 1
    return records.normalize({"id": uuid4().hex, "lessonId": "lesson", "phase": "video",
                              "dialogue": dialogue, "messages": [], "courses": []})


def apply(session, command, *args):
    return records.transition(session, dict(session, **command(session, *args)), command_id=uuid4().hex)


def test_cross_point_confirmation_precedes_natural_transition(provider):
    packets, inputs = provider
    packets.append({"reply": "用自己的话说说栈的取出顺序。"})
    session = apply(lesson(), service.start_discussion)
    answer = "栈后进先出，队列先进先出。栈为什么适合撤销？"
    # First student message, after the opening.
    packets.extend([
        {"reply": "因为撤销要先处理最后一次操作，正好符合栈的顺序。",
         "confirmations": [{"point_id": "A", "requirement_id": "understandingPoints:1",
                            "sources": [{"message": 2, "quote": "栈后进先出"}]},
                           {"point_id": "B", "requirement_id": "understandingPoints:1",
                            "sources": [{"message": 2, "quote": "队列先进先出"}]}]},
        {"reply": "你已经说清了队列的顺序。现在想想从哪一端删除？"},
    ])
    session = apply(session, service.classroom_turn, answer)
    student, response, transition = session["messages"][-3:]
    assert student["text"] == answer
    assert response["text"].startswith("因为撤销")
    assert transition["text"].startswith("你已经说清")
    assert service.describe_session(session)["learningProgress"]["currentPoint"] == "队列"
    a, b = session["dialogue"]["points"]
    assert a["status"] == "mastered"
    assert [item["status"] for item in b["requirements"]] == ["demonstrated", "unconfirmed"]
    for point in (a, b):
        assert point["requirements"][0]["evidenceRefs"][0]["messageId"] == student["messageId"]
    assert inputs[-1]["focus"]["id"] == "B"

@pytest.fixture
def command_session(pg, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import main
    from backend.infrastructure import persistence

    monkeypatch.setenv("PLATFORM_TO_STUDENT_KEY", "continuous-test-key")

    def create(points=POINTS):
        sid = uuid4().hex
        persistence.save({"id": sid, "lessonId": "lesson", "classroomId": "room", "videoRevision": "rev",
            "phase": "video", "dialogue": service.new_dialogue(points, continuous=True),
            "messages": [], "courses": [], "preparation": "ready",
            "context": {"userId": "student", "courseId": "course", "publication": {"id": "pub", "version": 1}}}, 0)
        path = f"/api/session/{sid}"
        headers = {"X-Platform-Learning-Key": "continuous-test-key",
                   "X-Platform-Protocol": "platform-cookie-v1", "X-Platform-User-Id": "student",
                   "X-Platform-Course-Id": "course"}

        def read():
            # Each request can reopen the persisted lesson independently of the previous client.
            with TestClient(main.app, headers=headers) as client:
                response = client.get(path)
            assert response.status_code == 200, response.text
            return response.json()

        def command(kind, text=None, **payload):
            view = read()
            if text is not None:
                payload["text"] = text
            if kind in {"next_point", "previous_point"} or "cardId" in payload:
                payload["taskId"] = (view["currentTaskPublic"] or {}).get("taskId")
            with TestClient(main.app, headers=headers) as client:
                response = client.post(path + "/commands", json={"commandId": uuid4().hex, "type": kind,
                    "payload": payload, "expectedStateVersion": view["stateVersion"],
                    "contentGeneration": view["contentGeneration"]})
            assert response.status_code == 200, response.text
            receipt = response.json()
            assert receipt["status"] == "completed", receipt
            return receipt["sessionView"]

        return read, command

    return create


def test_stalled_student_can_skip_then_resume_specific_issue_without_changing_classroom_snapshot(provider, command_session):
    packets, inputs = provider
    c = {"id": "C", "title": "双端队列", "type": "concept",
         "details": {"explanation": "可以在两端操作。", "understandingPoints": ["可在两端插入"]}}
    read, send = command_session([*POINTS, c])
    packets.append({"reply": "栈的元素按什么顺序弹出？"})
    send("start_discussion")
    answer = "栈后进先出，队列先进先出。栈为什么适合撤销？"
    packets.extend([
        {"reply": "撤销先处理最近的一次操作，和栈的取出顺序一致。",
         "confirmations": [{"point_id": point_id, "requirement_id": "understandingPoints:1",
                            "sources": [{"message": 2, "quote": quote}]}
                           for point_id, quote in [("A", "栈后进先出"), ("B", "队列先进先出")]]},
        {"reply": "已知道队列的顺序。现在看删除位置，从哪一端出队？"},
    ])
    view = send("submit_answer", answer)
    student, response, transition = view["messages"][-3:]
    assert response["taskId"] == student["taskId"]
    assert transition["taskId"] == view["currentTaskPublic"]["taskId"]
    for idx in range(6):
        packets.append({"reply": "要用排队例子换个方法继续，还是点右箭头先学下一点？也可以先结束。",
                        "open_issue": "把收到服务的人与队首删除对应起来"})
        view = send("submit_answer", "我还是分不清从哪一头删。")
        assert view["currentTaskPublic"]["topicId"] == "B"
        assert view["canGoNextPoint"]
        assert inputs[-1]["review_recent_dialogue"] == (idx >= 3)
    packets.append({"reply": "先看双端队列可以在哪些位置插入。"})
    assert send("next_point")["currentTaskPublic"]["topicId"] == "C"
    ended = send("finish")
    snapshot = ended["classroomFeedback"]
    assert snapshot["counts"]["mastered"] == 1
    assert snapshot["points"][1]["skipped"] is True
    assert snapshot["points"][1]["requirements"][0]["evidenceRefs"][0]["messageId"] == student["messageId"]
    assert read()["classroomFeedback"] == snapshot
    packets.append({"reply": "刚才卡在队首删除。想象第一个排队的人办完离开，他原来站在哪里？"})
    resumed = send("continue_after_class")
    assert resumed["currentTaskPublic"]["topicId"] == "B"
    assert inputs[-1]["focus"]["open_issue"]["text"] == "把收到服务的人与队首删除对应起来"
    assert any(message["text"] == "我还是分不清从哪一头删。" for message in inputs[-1]["history"])
    packets.extend([
        {"reply": "对，先出队的人离开队首。", "confirmations": [{"point_id": "B",
         "requirement_id": "understandingPoints:2", "sources": [{"message": len(resumed["messages"]) + 1,
                                                                   "quote": "从队首删除"}]}]},
        {"reply": "继续看双端队列，它在哪些位置可以插入？"},
    ])
    updated = send("postclass_answer", "从队首删除。")
    assert updated["feedback"]["counts"]["mastered"] == 2
    assert updated["classroomFeedback"] == snapshot
    assert updated["currentTaskPublic"]["topicId"] == "C"


def test_all_mastered_still_allows_questions_and_review(provider, command_session):
    packets, _ = provider
    _, send = command_session(POINTS[:1])
    packets.append({"reply": "栈的元素按什么顺序弹出？"})
    send("start_discussion")
    packets.extend([
        {"reply": "顺序说对了。", "confirmations": [{"point_id": "A", "requirement_id": "understandingPoints:1",
                                                     "sources": [{"message": 2, "quote": "后进先出"}]}]},
        {"reply": "这个要求已经达成，你还可以提问或回看。"},
    ])
    complete = send("submit_answer", "后进先出。")
    assert complete["afterClassComplete"] and complete["canGoPreviousPoint"]
    packets.append({"reply": "撤销栈就是一个应用。"})
    assert send("submit_answer", "有什么应用？")["messages"][-1]["text"] == "撤销栈就是一个应用。"
    packets.append({"reply": "我们回看栈。"})
    send("previous_point")
    packets.append({"reply": "这次顺序说反了，栈是后进先出。"})
    assert send("submit_answer", "先进先出。")["afterClassComplete"]
    assert send("finish")["classroomFeedback"]["endedEarly"] is False
    packets.append({"reply": "你已经完成本课要求。还想聊聊栈的哪些用法？"})
    assert send("continue_after_class")["postclassStage"] == "open"
    packets.append({"reply": "函数调用栈也遵循后进先出。"})
    assert send("postclass_answer", "函数调用也用栈吗？")["postclassStage"] == "open"

def test_early_exit_before_conversation_starts_at_first_unlearned_point(provider, command_session):
    packets, inputs = provider
    _, send = command_session()
    ended = send("finish")
    assert ended["classroomFeedback"]["counts"]["not_assessed"] == 2
    assert ended["messages"] == []
    packets.append({"reply": "我们从栈开始，想象一摞盘子。"})
    resumed = send("continue_after_class")
    assert resumed["currentTaskPublic"]["topicId"] == "A"
    assert inputs[-1]["history"] == []


def test_agent_can_choose_card_and_card_result_is_traceable(provider, command_session):
    packets, _ = provider
    point = {"id": "memory", "title": "Push", "type": "memory",
             "details": {"statement": "Push 是插入操作。", "requiredElements": ["Push 是插入操作。"]}}
    _, send = command_session([point])
    packets.extend([
        {"reply": "试试这张题卡。", "show_card": True},
        {"questions": [{"prompt": "Push 的作用？", "options": ["插入", "删除"], "answer": 0,
                        "explanation": "Push 将元素放入栈中。", "target_ids": ["requiredElements:1"]}]},
    ])
    opened = send("start_discussion")
    card = opened["questionGroups"][0]
    assert opened["messages"][-1]["cardId"] == card["id"]
    choice = card["questions"][0]["options"].index("插入")
    packets.extend([{"reply": "答对了，Push 将元素放入栈中。",
                     "card_confirmations": ["requiredElements:1"]}, {"reply": "本课的要求已达成。"}])
    updated = send("submit_answer", "提交题卡作答", cardId=card["id"], answers={"q1": choice})
    assert all(message["role"] == "assistant" for message in updated["messages"])
    finished = send("finish")
    assert finished["classroomFeedback"]["points"][0]["requirements"][0]["evidenceRefs"] == [
        {"cardId": card["id"], "questionId": "q1"}]

def test_assistant_text_cannot_become_evidence_and_original_student_message_is_retained(provider):
    packets, inputs = provider
    packets.append({"reply": "举个例子，栈后进先出。请讲讲你的理解。"})
    session = apply(lesson(), service.start_discussion)
    packets.append({"reply": "你说了正确的顺序，我再解释一下。"})
    session = apply(session, service.classroom_turn, "最后放进去的先拿出来。")
    original = session["messages"][-2]
    packets.extend([
        {"reply": "已掌握。", "confirmations": [{"point_id": "A", "requirement_id": "understandingPoints:1",
                                                 "sources": [{"message": 1, "quote": "栈后进先出"}]}]},
        {"reply": "你前面已经正确说出了取出顺序。", "confirmations": [
            {"point_id": "A", "requirement_id": "understandingPoints:1",
             "sources": [{"message": 2, "quote": "最后放进去的先拿出来"}]}]},
        {"reply": "接下来看看队列的顺序。"},
    ])
    session = apply(session, service.classroom_turn, "听懂了。")
    requirement = session["dialogue"]["points"][0]["requirements"][0]
    assert requirement["studentText"] == original["text"]
    assert requirement["evidenceRefs"][0]["messageId"] == original["messageId"]
    assert "repair" in inputs[-2]
    assert session["learningRecords"]["observations"][-1]["assessmentResult"] == "unknown"

def test_failed_transition_does_not_publish_partial_reply_or_mastery(provider):
    from backend.contracts import SessionError

    packets, _ = provider
    packets.append({"reply": "栈的元素按什么顺序弹出？"})
    session = apply(lesson(), service.start_discussion)
    original = json.loads(json.dumps(session))
    assessment = {"reply": "正确。", "confirmations": [{"point_id": "A", "requirement_id": "understandingPoints:1",
                                                        "sources": [{"message": 2, "quote": "后进先出"}]}]}
    packets.extend([assessment, {}, {}])
    with pytest.raises(SessionError) as failure:
        service.classroom_turn(session, "后进先出。")
    assert failure.value.code == "MODEL_UNAVAILABLE"
    assert session == original
    packets.extend([assessment, {"reply": "接下来看看队列的顺序。"}])
    updated = apply(session, service.classroom_turn, "后进先出。")
    assert updated["dialogue"]["points"][0]["status"] == "mastered"
    assert sum(message["role"] == "student" for message in updated["messages"]) == 1
