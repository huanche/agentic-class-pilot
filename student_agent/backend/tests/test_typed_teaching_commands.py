"""Teaching behaviors through authenticated HTTP commands and session reads."""
import json
from importlib import import_module
from uuid import uuid4

from fastapi.testclient import TestClient
from openai import DefaultHttpxClient
import pytest

from backend import main
from backend.infrastructure import persistence
from backend.teaching import service


@pytest.fixture
def conversation(pg, monkeypatch, request):
    scenario = getattr(request, "param", None) or {}
    packets = iter(scenario.get("responses", []))
    monkeypatch.setenv("PLATFORM_TO_STUDENT_KEY", "tdd-forward-key")
    monkeypatch.setenv("STUDENT_AGENT_API_KEY", "offline-key")
    monkeypatch.setenv("STUDENT_AGENT_BASE_URL", "https://teaching-provider.test/v1")
    monkeypatch.setenv("STUDENT_AGENT_MODEL", "offline-model")
    original_send = DefaultHttpxClient.send

    def provider(self, request, **kwargs):
        if request.url.host != "teaching-provider.test":
            return original_send(self, request, **kwargs)
        if scenario.get("inspect_request"):
            scenario["inspect_request"](json.loads(request.content))
        response = next(packets) if "responses" in scenario else scenario or {
            "text": "接着原题，说明 Push 和 Pop 的作用？", "question": "说明 Push 和 Pop 的作用？", "assistance": "none"}
        message = response if "tool_calls" in response else {"role": "assistant", "content": json.dumps(response, ensure_ascii=False)}
        transport = import_module(type(request).__module__.split(".")[0])
        return transport.Response(200, request=request, json={"id": "offline", "object": "chat.completion", "created": 0,
            "model": "offline-model", "choices": [{"index": 0, "finish_reason": "tool_calls" if "tool_calls" in message else "stop",
                "message": message}]})

    # Replace only external provider HTTP; real teaching, commands and storage execute.
    monkeypatch.setattr(DefaultHttpxClient, "send", provider)
    sid = "tdd-" + uuid4().hex
    seed = {"id": sid, "phase": "video", "lessonId": "lesson", "classroomId": "room",
        "context": {"userId": "student", "courseId": "course", "publication": {"id": "pub", "version": 1}},
        "videoRevision": "revision", "messages": [], "courses": [], "preparation": "ready",
        "dialogue": service.new_dialogue([{"id": "stack", "title": "栈的操作", "type": "memory",
            "details": {"statement": "Push 是插入，Pop 是删除。", "requiredElements": ["Push 插入", "Pop 删除"]},
            "content": "Push 是插入，Pop 是删除。\nPush 插入\nPop 删除",
            "description": "Push 是插入，Pop 是删除。\nPush 插入\nPop 删除"}, *scenario.get("extra_points", [])])}
    persistence.save(seed, 0)  # Arrange the lesson; assertions use only HTTP below.
    client = TestClient(main.app, headers={"X-Platform-Learning-Key": "tdd-forward-key",
        "X-Platform-Protocol": "platform-cookie-v1", "X-Platform-User-Id": "student", "X-Platform-Course-Id": "course"})

    def read():
        response = client.get(f"/api/session/{sid}")
        assert response.status_code == 200, response.text
        return response.json()

    def send(kind, text=None):
        view = read()
        response = client.post(f"/api/session/{sid}/commands", json={"commandId": uuid4().hex,
            "type": kind, "payload": {"text": text} if text is not None else {}, "expectedStateVersion": view["stateVersion"],
            "contentGeneration": view["contentGeneration"]})
        assert response.status_code == 200, response.text
        return response.json()["sessionView"]

    return read, send


def test_student_resumes_the_same_unfinished_task_as_active_after_exiting(conversation):
    read, send = conversation
    send("start_discussion")
    send("finish")
    started = send("continue_after_class")
    send("finish")
    assert read()["postclassStage"] == "paused"
    resumed = send("continue_after_class")
    assert resumed["postclassStage"] == "remediation"
    assert resumed["currentTaskPublic"]["taskId"] == started["currentTaskPublic"]["taskId"]
    assert resumed["currentTaskPublic"]["question"] == "说明 Push 和 Pop 的作用？"
    assert resumed["currentTaskPublic"]["status"] == "active"


@pytest.mark.parametrize("conversation", [{
    "text": "我们先回忆：请你说说栈和队列的插入、删除位置有什么特点？",
    "question": "请说说栈和队列的插入、删除位置有什么特点？", "assistance": "none"
}], indirect=True)
def test_opening_preserves_the_question_seen_by_student_despite_equivalent_wording(conversation):
    read, send = conversation
    opened = send("start_discussion")
    assert opened["phase"] == "discussion"
    assert opened["currentTaskPublic"]["question"] == "我们先回忆：请你说说栈和队列的插入、删除位置有什么特点？"
    assert read()["currentTaskPublic"]["question"] == opened["messages"][-1]["text"]


PARTIAL_PACKET = {"role": "assistant", "content": None, "tool_calls": [{"id": "current-assessment",
    "type": "function", "function": {"name": "submit_current_assessment", "arguments": json.dumps({
        "intent": "answer", "assessment": {"result": "partial", "evidence": "学生只说对 Push",
        "known_parts": ["Push 插入"], "gaps": ["Pop 的含义"], "next_step": "区分删除操作"}})}}]}


@pytest.mark.parametrize("conversation", [{
    "extra_points": [{"id": "sequence", "title": "理解出栈顺序", "type": "concept",
        "details": {"explanation": "每次取当前栈顶", "understandingPoints": ["操作顺序影响输出"]},
        "content": "每次取当前栈顶\n操作顺序影响输出", "description": "每次取当前栈顶\n操作顺序影响输出"}],
    "responses": [
        {"text": "请说明栈的操作？", "question": "请说明栈的操作？", "assistance": "none"},
        *[packet for _ in range(4) for packet in [PARTIAL_PACKET,
            {"text": "继续说明 Pop。", "question": "", "assistance": "hint"}]],
        PARTIAL_PACKET,
        {"text": "Pop 还没分清，请继续回答栈顶的问题。", "question": "", "assistance": "hint"},
        {"text": "这部分稍后补强。为什么操作顺序会影响出栈顺序？",
         "question": "为什么操作顺序会影响出栈顺序？", "assistance": "none"}
    ]
}], indirect=True)
def test_student_reaches_next_point_when_missing_new_question_is_repaired(conversation):
    read, send = conversation
    send("start_discussion")
    for _ in range(5):
        view = send("submit_answer", "我知道 Push 是插入，Pop 还不确定")
    assert view["currentTaskPublic"]["topicId"] == "sequence"
    assert view["currentTaskPublic"]["question"] == "为什么操作顺序会影响出栈顺序？"
    assert view["messages"][-1]["text"] == "这部分稍后补强。为什么操作顺序会影响出栈顺序？"
    assert read()["currentTaskPublic"]["topicId"] == "sequence"


def inspect_handover_request(body):
    """The external model must not receive an instruction to continue the old task."""
    context = json.loads(body["messages"][0]["content"].splitlines()[-1])
    if context["focus"] and context["focus"]["id"] == "sequence":
        assert "next_step" not in context["previousPoint"]
        assert "task_question" not in context["previousPoint"]
        assert not context.get("recentMessages")
        # Old tool arguments also contain next_step, so they cannot be generation input.
        assert not any(message["role"] == "tool" or message.get("tool_calls") for message in body["messages"])


@pytest.mark.parametrize("conversation", [{
    "inspect_request": inspect_handover_request,
    "extra_points": [{"id": "sequence", "title": "理解出栈顺序", "type": "concept",
        "details": {"explanation": "每次取当前栈顶", "understandingPoints": ["操作顺序影响输出"]},
        "content": "每次取当前栈顶\n操作顺序影响输出", "description": "每次取当前栈顶\n操作顺序影响输出"}],
    "responses": [
        {"text": "请说明栈的操作？", "question": "请说明栈的操作？", "assistance": "none"},
        *[packet for _ in range(4) for packet in [PARTIAL_PACKET,
            {"text": "继续说明 Pop。", "question": "", "assistance": "hint"}]],
        PARTIAL_PACKET,
        {"text": "Pop 留待补强。为什么操作顺序会影响出栈顺序？",
         "question": "为什么操作顺序会影响出栈顺序？", "assistance": "none"}
    ]
}], indirect=True)
def test_handover_gives_model_only_old_point_feedback_and_the_new_task(conversation):
    read, send = conversation
    send("start_discussion")
    for _ in range(5):
        view = send("submit_answer", "我知道 Push 是插入，Pop 还不确定")
    assert view["currentTaskPublic"]["topicId"] == "sequence"
    assert view["messages"][-1]["text"] == "Pop 留待补强。为什么操作顺序会影响出栈顺序？"
    assert read()["currentTaskPublic"]["topicId"] == "sequence"


MASTERED_WITH_GAP = {"role": "assistant", "content": None, "tool_calls": [{"id": "assessment-with-gap",
    "type": "function", "function": {"name": "submit_current_assessment", "arguments": json.dumps({
        "intent": "answer", "assessment": {"result": "mastered", "evidence": "学生只说对 Push，Pop 仍未说明",
        "known_parts": ["Push 插入"], "gaps": ["Pop 的含义"], "next_step": "说明 Pop 删除哪个元素"}})}}]}


@pytest.mark.parametrize("conversation", [{"responses": [
    {"text": "请说明 Push 和 Pop？", "question": "请说明 Push 和 Pop？", "assistance": "none"},
    MASTERED_WITH_GAP,
    {"text": "Push 说对了，接着说明 Pop 删除哪个元素？", "question": "", "assistance": "hint"}
]}], indirect=True)
def test_remaining_gap_keeps_student_on_same_task_and_in_needs_review_feedback(conversation):
    read, send = conversation
    opened = send("start_discussion")
    answered = send("submit_answer", "我只知道 Push 是插入")
    assert answered["currentTaskPublic"] is not None
    assert answered["currentTaskPublic"]["taskId"] == opened["currentTaskPublic"]["taskId"]
    assert read()["currentTaskPublic"]["question"] == "请说明 Push 和 Pop？"
    feedback = send("finish")["feedback"]
    assert feedback["counts"]["mastered"] == 0
    assert feedback["points"][0]["status"] == "partial"
    assert feedback["points"][0]["gaps"] == ["Pop 的含义"]


def assessment_packet(result, gaps):
    packet = json.loads(json.dumps(MASTERED_WITH_GAP))
    function = packet["tool_calls"][0]["function"]
    arguments = json.loads(function["arguments"])
    arguments["assessment"].update(result=result, gaps=gaps)
    function["arguments"] = json.dumps(arguments)
    return packet


@pytest.mark.parametrize("conversation, expected_status", [
    ({"responses": [
        {"text": "请说明栈的操作？", "question": "请说明栈的操作？", "assistance": "none"},
        assessment_packet(result, []), {"text": "记录你的回答。", "question": "", "assistance": "none"}
    ]}, result) for result in ["partial", "mastered"]
], indirect=["conversation"])
def test_empty_gap_does_not_change_the_submitted_mastery_decision(conversation, expected_status):
    read, send = conversation
    send("start_discussion")
    send("submit_answer", "Push 插入，Pop 删除栈顶元素")
    send("finish")
    assert read()["feedback"]["points"][0]["status"] == expected_status


def inspect_preserved_assessment(body):
    context = json.loads(body["messages"][0]["content"].splitlines()[-1])
    history = (context.get("focus") or {}).get("assessment_history", [])
    if history:
        # A later HTTP command must recover both the applied decision and what
        # the provider originally submitted, not only an in-memory correction.
        assert history[-1]["result"] == "partial"
        assert history[-1]["submitted_assessment"]["result"] == "mastered"
        assert history[-1]["submitted_assessment"]["gaps"] == ["Pop 的含义"]


@pytest.mark.parametrize("conversation", [{
    "inspect_request": inspect_preserved_assessment,
    "responses": [
        {"text": "请说明 Push 和 Pop？", "question": "请说明 Push 和 Pop？", "assistance": "none"},
        *[packet for _ in range(13) for packet in [MASTERED_WITH_GAP,
            {"text": "Pop 还需要说清楚。", "question": "", "assistance": "hint"}]],
        {"text": "接着原题，说明 Pop。", "question": "", "assistance": "hint"},
        MASTERED_WITH_GAP,
        {"text": "继续说明 Pop 删除哪个元素？", "question": "", "assistance": "hint"},
        assessment_packet("mastered", []),
        {"text": "已说清 Push 和 Pop，本课已全部掌握。", "question": "", "assistance": "none"}
    ]
}], indirect=True)
def test_gap_survives_limits_and_postclass_then_completes_when_resolved(conversation):
    read, send = conversation
    opened = send("start_discussion")
    for _ in range(4):
        assert send("submit_answer", "只会 Push")["currentTaskPublic"]["type"] == "recall"
    reinforced = send("submit_answer", "只会 Push，Pop 不会")
    assert reinforced["currentTaskPublic"]["type"] == "reinforce"
    assert reinforced["currentTaskPublic"]["question"] == opened["currentTaskPublic"]["question"]
    for _ in range(7):
        assert send("submit_answer", "Pop 还是没有说清")["currentTaskPublic"] is not None
    exhausted = send("submit_answer", "Pop 仍不会")
    assert exhausted["currentTaskPublic"] is None
    feedback = send("finish")["feedback"]
    assert feedback["points"][0]["status"] == "partial"
    assert feedback["points"][0]["gaps"] == ["Pop 的含义"]
    resumed = send("continue_after_class")
    assert resumed["currentTaskPublic"]["question"] == "请说明 Push 和 Pop？"
    pending = send("postclass_answer", "我还没有解释 Pop")
    assert pending["postclassStage"] == "remediation"
    assert read()["currentTaskPublic"]["topicId"] == "stack"
    completed = send("postclass_answer", "Push 在栈顶插入，Pop 删除当前栈顶元素")
    assert completed["postclassStage"] == "completed"
    assert completed["feedback"]["counts"]["mastered"] == 1
    assert completed["feedback"]["points"][0]["gaps"] == []
