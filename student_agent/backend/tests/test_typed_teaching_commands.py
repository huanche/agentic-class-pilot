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
        message = ({"role": "assistant", "content": response} if isinstance(response, str) else
                   response if "tool_calls" in response else {"role": "assistant", "content": json.dumps(response, ensure_ascii=False)})
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
        "dialogue": service.new_dialogue(scenario.get("points") or [{"id": "stack", "title": "栈的操作", "type": "memory",
            "details": {"statement": "Push 是插入，Pop 是删除。", "requiredElements": ["Push 插入", "Pop 删除"]},
            "content": "Push 是插入，Pop 是删除。\nPush 插入\nPop 删除",
            "description": "Push 是插入，Pop 是删除。\nPush 插入\nPop 删除"}, *scenario.get("extra_points", [])])}
    if not scenario.get("requirement_progress"):
        # Existing conversations keep the earlier point-level assessment protocol.
        seed["dialogue"].pop("mastery_version", None)
    if not scenario.get("natural_reply"):
        seed["dialogue"].pop("reply_version", None)
    persistence.save(seed, 0)  # Arrange the lesson; assertions use only HTTP below.
    client = TestClient(main.app, headers={"X-Platform-Learning-Key": "tdd-forward-key",
        "X-Platform-Protocol": "platform-cookie-v1", "X-Platform-User-Id": "student", "X-Platform-Course-Id": "course"})

    def read():
        response = client.get(f"/api/session/{sid}")
        assert response.status_code == 200, response.text
        return response.json()

    def send(kind, text=None, expected_status=200):
        view = read()
        response = client.post(f"/api/session/{sid}/commands", json={"commandId": uuid4().hex,
            "type": kind, "payload": {"text": text} if text is not None else {}, "expectedStateVersion": view["stateVersion"],
            "contentGeneration": view["contentGeneration"]})
        assert response.status_code == expected_status, response.text
        if expected_status != 200:
            return response.json()
        return response.json()["sessionView"]

    def read_records():
        response = client.post(f"/api/session/{sid}/learning-records", json={})
        assert response.status_code == 200, response.text
        return response.json()

    read.records = read_records

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


@pytest.mark.parametrize("conversation", [{
    "requirement_progress": True,
    "responses": [
        {"text": "请说明 Push 的含义。", "question": "请说明 Push 的含义。", "target_ids": ["requiredElements:1"], "assistance": "none"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "push-answer", "type": "function", "function": {
            "name": "submit_current_assessment", "arguments": json.dumps({"intent": "answer", "assessment": {
                "answer_result": "correct", "evidence": "学生说明 Push 是插入",
                "updates": [{"requirement_id": "requiredElements:1", "status": "demonstrated", "evidence": "学生说 Push 是插入", "gap": ""}],
                "next_step": "请学生说明 Pop"}})}}]},
        {"text": "Push 说对了，请说明 Pop 的含义。", "question": "", "target_ids": ["requiredElements:2"], "assistance": "none"}
    ]
}], indirect=True)
def test_correct_answer_only_confirms_what_student_actually_demonstrated(conversation):
    read, send = conversation
    send("start_discussion")
    answered = send("submit_answer", "Push 是插入")
    assert answered["currentTaskPublic"]["topicId"] == "stack"
    send("finish")
    point = read()["feedback"]["points"][0]
    assert point["category"] == "needs_review"
    assert point["label"] == "本次尚未确认"
    assert [(r["text"], r["status"]) for r in point["requirements"]] == [
        ("Push 插入", "demonstrated"), ("Pop 删除", "unconfirmed")]


def scoped_packet(*updates, answer_result="correct", next_step="继续尚未确认的要求"):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": "scoped-answer", "type": "function",
        "function": {"name": "submit_current_assessment", "arguments": json.dumps({"intent": "answer", "assessment": {
            "answer_result": answer_result, "evidence": "按学生本轮实际表现判断", "updates": list(updates), "next_step": next_step}})}}]}


PUSH_SHOWN = {"requirement_id": "requiredElements:1", "status": "demonstrated", "evidence": "学生说 Push 是插入", "gap": ""}
POP_SHOWN = {"requirement_id": "requiredElements:2", "status": "demonstrated", "evidence": "学生自己说明 Pop 是删除", "gap": ""}
PUSH_QUESTION = {"text": "请说明 Push 的含义。", "question": "请说明 Push 的含义。", "target_ids": ["requiredElements:1"], "assistance": "none"}
POP_FOLLOWUP = {"text": "Push 已说明，现在请说明 Pop。", "question": "", "target_ids": ["requiredElements:2"], "assistance": "hint"}
COMPLETED_REPLY = {"text": "你已经说明 Push 插入、Pop 删除。", "question": "", "target_ids": [], "assistance": "none"}


@pytest.mark.parametrize("conversation", [{"requirement_progress": True,
    "responses": [PUSH_QUESTION, scoped_packet(PUSH_SHOWN), POP_FOLLOWUP,
                  POP_FOLLOWUP, POP_FOLLOWUP, scoped_packet(POP_SHOWN), COMPLETED_REPLY]}], indirect=True)
def test_student_keeps_evidence_after_pause_and_completes_remaining_requirement_with_help(conversation):
    read, send = conversation
    opened = send("start_discussion")
    send("submit_answer", "Push 是插入")
    send("finish")
    send("continue_after_class")
    send("finish")
    restored = send("continue_after_class")
    assert restored["currentTaskPublic"]["question"] == opened["currentTaskPublic"]["question"]
    done = send("postclass_answer", "提示后我明白了，Pop 是删除当前栈顶")
    assert done["postclassStage"] == "completed"
    point = read()["feedback"]["points"][0]
    assert point["category"] == "mastered"
    assert point["gaps"] == []
    assert [(r["status"], r["studentText"]) for r in point["requirements"]] == [
        ("demonstrated", "Push 是插入"), ("demonstrated", "提示后我明白了，Pop 是删除当前栈顶")]


@pytest.mark.parametrize("conversation", [{"requirement_progress": True,
    "responses": [PUSH_QUESTION, scoped_packet(PUSH_SHOWN, POP_SHOWN), COMPLETED_REPLY]}], indirect=True)
def test_one_answer_can_demonstrate_multiple_requirements_without_extra_confirmation(conversation):
    read, send = conversation
    send("start_discussion")
    answered = send("submit_answer", "Push 是插入，Pop 是删除")
    assert answered["agentStage"] == "wrapup"
    send("finish")
    assert read()["feedback"]["points"][0]["category"] == "mastered"


def bounded_scenario(complete_last):
    stuck = {"requirement_id": "requiredElements:2", "status": "needs_help",
             "evidence": "学生把 Pop 当成插入", "gap": "Pop 的删除含义仍混淆"}
    responses = [PUSH_QUESTION, scoped_packet(PUSH_SHOWN), POP_FOLLOWUP,
                 scoped_packet(stuck, answer_result="misconception"), POP_FOLLOWUP]
    for _ in range(10):
        responses.extend([scoped_packet(answer_result="unanswered"), POP_FOLLOWUP])
    closing = COMPLETED_REPLY if complete_last else {**COMPLETED_REPLY, "text": "本轮先到这里，Push已说明，Pop仍需帮助。"}
    responses.extend([scoped_packet(POP_SHOWN) if complete_last else scoped_packet(answer_result="unanswered"), closing])
    return {"requirement_progress": True, "responses": responses}


@pytest.mark.parametrize("conversation,complete_last", [(bounded_scenario(False), False), (bounded_scenario(True), True)], indirect=["conversation"])
def test_limits_preserve_confirmed_and_missing_requirements_and_last_answer_can_complete(conversation, complete_last):
    read, send = conversation
    send("start_discussion")
    views = [send("submit_answer", "Push 是插入")]
    views.append(send("submit_answer", "Pop 我以为也是插入"))
    for _ in range(10):
        views.append(send("submit_answer", "我还不知道 Pop 的含义"))
    last = send("submit_answer", "现在我可以自己说明 Pop 是删除")
    assert views[3]["agentStage"] == "recall"
    assert views[4]["agentStage"] == "reinforce"
    assert views[-1]["agentStage"] == "reinforce"
    assert last["agentStage"] == "wrapup"
    send("finish")
    point = read()["feedback"]["points"][0]
    assert point["requirements"][0]["status"] == "demonstrated"
    assert point["requirements"][0]["studentText"] == "Push 是插入"
    assert last["learningProgress"]["completionReason"] == ("all_mastered" if complete_last else "rounds_exhausted")
    if complete_last:
        assert point["category"] == "mastered"
        assert point["requirements"][1]["status"] == "demonstrated"
    else:
        assert last["learningProgress"]["completionReason"] == "rounds_exhausted"
        assert point["category"] == "needs_review"
        assert point["requirements"][1]["status"] == "needs_help"
        assert point["gaps"] == ["Pop 的删除含义仍混淆"]


@pytest.mark.parametrize("conversation", [{"requirement_progress": True,
    "points": [{"id": "undo", "title": "用栈撤销", "type": "design",
        "details": {"capability": "构造撤销方案", "constraints": ["只取栈顶"], "successCriteria": ["结果正确"]},
        "content": "构造撤销方案\n只取栈顶\n结果正确", "description": "构造撤销方案\n只取栈顶\n结果正确"}],
    "responses": [
        {"text": "请构造撤销方案，并写出结果。", "question": "请构造撤销方案，并写出结果。", "target_ids": ["capability:1", "constraints:1", "successCriteria:1"], "assistance": "none"},
        scoped_packet({"requirement_id": "successCriteria:1", "status": "demonstrated", "evidence": "结果正确", "gap": ""}),
        {"text": "结果对了，请说明实际构造步骤和如何只操作栈顶。", "question": "", "target_ids": ["capability:1", "constraints:1"], "assistance": "hint"},
        scoped_packet({"requirement_id": "capability:1", "status": "demonstrated", "evidence": "学生完成了实际步骤", "gap": ""},
                      {"requirement_id": "constraints:1", "status": "demonstrated", "evidence": "每一步只取栈顶", "gap": ""}),
        {**COMPLETED_REPLY, "text": "你已完成撤销构造，过程只取栈顶，结果正确。"}
    ]}], indirect=True)
def test_design_needs_actual_construction_and_constraints_not_only_a_correct_result(conversation):
    read, send = conversation
    send("start_discussion")
    partial = send("submit_answer", "最后结果为 a")
    assert partial["agentStage"] == "recall"
    assert partial["currentTaskPublic"]["topicId"] == "undo"
    done = send("submit_answer", "依次压入a、b，撤销时只弹出栈顶b，剩下a")
    assert done["agentStage"] == "wrapup"
    send("finish")
    point = read()["feedback"]["points"][0]
    assert [r["id"] for r in point["requirements"]] == ["capability:1", "constraints:1", "successCriteria:1"]
    assert all(r["status"] == "demonstrated" for r in point["requirements"])


@pytest.mark.parametrize("conversation", [{"requirement_progress": True,
    "points": [{"id": "sequence", "title": "理解栈顶与顺序", "type": "concept",
        "details": {"explanation": "每次弹出当前栈顶，所以顺序受操作影响。", "understandingPoints": ["弹出当前栈顶", "操作影响顺序"]},
        "content": "每次弹出当前栈顶，所以顺序受操作影响。\n弹出当前栈顶\n操作影响顺序",
        "description": "每次弹出当前栈顶，所以顺序受操作影响。\n弹出当前栈顶\n操作影响顺序"}],
    "responses": [
        {"text": "请解释每次从哪里弹出？", "question": "请解释每次从哪里弹出？", "target_ids": ["understandingPoints:1"], "assistance": "none"},
        scoped_packet({"requirement_id": "understandingPoints:1", "status": "demonstrated", "evidence": "学生说明当前栈顶", "gap": ""}),
        {"text": "每次取栈顶已说明，请解释为什么操作会改变输出顺序。", "question": "", "target_ids": ["understandingPoints:2"], "assistance": "hint"}
    ]}], indirect=True)
def test_concept_correct_subquestion_does_not_complete_unexplained_relationship(conversation):
    read, send = conversation
    send("start_discussion")
    answered = send("submit_answer", "每次 Pop 都取当前栈顶")
    assert answered["currentTaskPublic"]["topicId"] == "sequence"
    send("finish")
    point = read()["feedback"]["points"][0]
    assert point["category"] == "needs_review"
    assert point["requirements"][1]["status"] == "unconfirmed"
    assert point["requirements"][1]["studentText"] == ""


@pytest.mark.parametrize("conversation", [{"requirement_progress": True,
    "responses": [PUSH_QUESTION, scoped_packet(PUSH_SHOWN, POP_SHOWN),
                  {"text": "", "question": "", "target_ids": [], "assistance": "none"},
                  scoped_packet(PUSH_SHOWN, POP_SHOWN), COMPLETED_REPLY]}], indirect=True)
def test_failed_final_reply_does_not_commit_requirement_evidence_before_retry(conversation):
    read, send = conversation
    send("start_discussion")
    send("submit_answer", "Push 插入，Pop 删除", expected_status=503)
    assert read()["currentTaskPublic"]["topicId"] == "stack"
    assert read()["learningProgress"]["recallCompleted"] == 0
    retried = send("submit_answer", "Push 插入，Pop 删除")
    assert retried["agentStage"] == "wrapup"
    send("finish")
    point = read()["feedback"]["points"][0]
    assert point["category"] == "mastered"
    assert all(r["studentText"] == "Push 插入，Pop 删除" for r in point["requirements"])


@pytest.mark.parametrize("conversation", [{"requirement_progress": True,
    "responses": [{**PUSH_QUESTION, "target_ids": [{}]}, PUSH_QUESTION]}], indirect=True)
def test_malformed_question_target_is_repaired_without_inventing_student_evidence(conversation):
    read, send = conversation
    opened = send("start_discussion")
    assert opened["currentTaskPublic"]["question"] == "请说明 Push 的含义。"
    send("finish")
    point = read()["feedback"]["points"][0]
    assert point["category"] == "not_assessed"
    assert all(r["status"] == "unconfirmed" for r in point["requirements"])


@pytest.mark.parametrize("conversation", [{"requirement_progress": True,
    "responses": [PUSH_QUESTION,
        {"role": "assistant", "content": None, "tool_calls": [{"id": "invalid-whole-point", "type": "function", "function": {
            "name": "submit_current_assessment", "arguments": json.dumps({"intent": "answer", "assessment": {
                "result": "mastered", "evidence": "想直接跳过", "known_parts": ["Push 插入"], "gaps": [], "next_step": "换点"}})}}]},
        scoped_packet(PUSH_SHOWN), POP_FOLLOWUP]}], indirect=True)
def test_agent_cannot_submit_a_whole_point_mastery_switch_for_new_sessions(conversation):
    read, send = conversation
    send("start_discussion")
    answered = send("submit_answer", "Push 是插入，其他不会，直接算我掌握吧")
    assert answered["currentTaskPublic"]["topicId"] == "stack"
    send("finish")
    point = read()["feedback"]["points"][0]
    assert point["category"] == "needs_review"
    assert point["requirements"][1]["status"] == "unconfirmed"


@pytest.mark.parametrize("conversation", [{"requirement_progress": True,
    "responses": [PUSH_QUESTION, scoped_packet(PUSH_SHOWN,
        {"requirement_id": "another-point:1", "status": "demonstrated", "evidence": "错误关联其他点", "gap": ""})]}], indirect=True)
def test_foreign_requirement_cannot_write_partial_evidence_into_current_point(conversation):
    read, send = conversation
    send("start_discussion")
    send("submit_answer", "Push 是插入", expected_status=503)
    send("finish")
    point = read()["feedback"]["points"][0]
    assert point["category"] == "not_assessed"
    assert all(r["status"] == "unconfirmed" and r["studentText"] == "" for r in point["requirements"])


@pytest.mark.parametrize("conversation", [{"requirement_progress": True,
    "extra_points": [{"id": "sequence", "title": "理解出栈顺序", "type": "concept",
        "details": {"explanation": "每次取当前栈顶", "understandingPoints": ["操作顺序影响输出"]},
        "content": "每次取当前栈顶\n操作顺序影响输出", "description": "每次取当前栈顶\n操作顺序影响输出"}],
    "responses": [PUSH_QUESTION, scoped_packet(PUSH_SHOWN, POP_SHOWN),
        {"text": "Push、Pop已说明。为什么操作顺序影响输出？", "question": "为什么操作顺序影响输出？", "target_ids": ["understandingPoints:1"], "assistance": "none"},
        scoped_packet({"requirement_id": "understandingPoints:1", "status": "demonstrated", "evidence": "学生解释每次只取当前栈顶", "gap": ""}),
        {**COMPLETED_REPLY, "text": "两个知识点已说明。"}]}], indirect=True)
def test_completed_point_advances_in_order_and_new_point_uses_its_own_requirements(conversation):
    read, send = conversation
    send("start_discussion")
    next_point = send("submit_answer", "Push插入，Pop删除")
    assert next_point["currentTaskPublic"]["topicId"] == "sequence"
    assert next_point["currentTaskPublic"]["question"] == "为什么操作顺序影响输出？"
    done = send("submit_answer", "每次只能取当前栈顶，操作先后改变栈顶，因此改变输出顺序")
    assert done["agentStage"] == "wrapup"
    send("finish")
    assert read()["feedback"]["counts"] == {"mastered": 2, "needs_review": 0, "not_assessed": 0}


@pytest.mark.parametrize("conversation", [{"requirement_progress": True, "natural_reply": True,
    "responses": ["请说明 Push 的含义。", scoped_packet(PUSH_SHOWN, POP_SHOWN), "你已说明 Push 插入、Pop 删除，本课结束。"]}], indirect=True)
def test_natural_chinese_summary_is_displayed_without_json_parsing(conversation):
    read, send = conversation
    opened = send("start_discussion")
    assert opened["currentTaskPublic"]["question"] == "请说明 Push 的含义。"
    done = send("submit_answer", "Push插入，Pop删除")
    assert done["agentStage"] == "wrapup"
    assert done["messages"][-1]["text"] == "你已说明 Push 插入、Pop 删除，本课结束。"
    send("finish")
    assert read()["feedback"]["counts"]["mastered"] == 1


def inspect_program_plan(body):
    context = json.loads(body["messages"][0]["content"].splitlines()[-1])
    if context["focus"] and context["focus"]["requirements"][0]["status"] == "demonstrated":
        assert context["teaching_plan"]["target_ids"] == ["requiredElements:2"]


@pytest.mark.parametrize("conversation", [{"requirement_progress": True, "natural_reply": True,
    "inspect_request": inspect_program_plan,
    "responses": ["请说明 Push。", scoped_packet(PUSH_SHOWN, next_step="继续问已会的Push"),
                  "Push已说明，请说明Pop。"]}], indirect=True)
def test_program_chooses_pending_target_and_records_actual_unclassified_reply(conversation):
    read, send = conversation
    send("start_discussion")
    reply = send("submit_answer", "Push 是插入")
    assert reply["messages"][-1]["text"] == "Push已说明，请说明Pop。"
    record = read.records()["assistance"][-1]
    assert record["classificationBasis"] == "unclassified_tutor_text"
    assert record["guidedPolicy"] is None
    assert record["plannedAction"] == "ask"


@pytest.mark.parametrize("conversation", [{"requirement_progress": True, "natural_reply": True,
    "responses": ["请说明Push。", scoped_packet(PUSH_SHOWN), "请说明Pop。", "我们继续说明Pop。",
                  scoped_packet(POP_SHOWN), "你已自己说明了两个操作。"]}], indirect=True)
def test_plain_reply_keeps_original_task_and_evidence_after_postclass_resume(conversation):
    read, send = conversation
    opened = send("start_discussion")
    send("submit_answer", "Push插入")
    send("finish")
    resumed = send("continue_after_class")
    assert resumed["currentTaskPublic"]["question"] == opened["currentTaskPublic"]["question"]
    done = send("postclass_answer", "Pop删除当前栈顶")
    assert done["postclassStage"] == "completed"
    assert [r["studentText"] for r in read()["feedback"]["points"][0]["requirements"]] == ["Push插入", "Pop删除当前栈顶"]


@pytest.mark.parametrize("conversation", [{"requirement_progress": True, "natural_reply": True,
    "responses": ["请说明Push。", scoped_packet(PUSH_SHOWN, POP_SHOWN), "   ",
                  scoped_packet(PUSH_SHOWN, POP_SHOWN), "你已说明这两个操作。"]}], indirect=True)
def test_empty_plain_reply_rolls_back_evidence_until_successful_retry(conversation):
    read, send = conversation
    send("start_discussion")
    send("submit_answer", "Push插入Pop删除", expected_status=503)
    assert read()["learningProgress"]["recallCompleted"] == 0
    assert send("submit_answer", "Push插入Pop删除")["agentStage"] == "wrapup"


@pytest.mark.parametrize("conversation", [{"requirement_progress": True, "natural_reply": True,
    "responses": ["请说明Push。",
        {"role": "assistant", "content": None, "tool_calls": [{"id": "unclear", "type": "function", "function": {
            "name": "submit_current_assessment", "arguments": json.dumps({"intent": "unclear", "assessment": None})}}]},
        "你是没有理解题意，还是不知道Push做什么？"]}], indirect=True)
def test_program_selects_clarification_for_unclear_answer_without_mastery(conversation):
    read, send = conversation
    send("start_discussion")
    send("submit_answer", "懂了")
    assert read.records()["assistance"][-1]["plannedAction"] == "clarify"
    send("finish")
    assert all(r["status"] == "unconfirmed" for r in read()["feedback"]["points"][0]["requirements"])
