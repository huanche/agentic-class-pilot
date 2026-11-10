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
