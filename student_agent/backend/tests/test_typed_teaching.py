"""Real teaching create_agent execution with scripted provider messages; no network."""
from copy import deepcopy
import json

import pytest
from langchain_core.messages import AIMessage

from backend.content.knowledge import compile_points
from backend.content.knowledge_schema import submit_knowledge_points
from backend.evidence import records
from backend.infrastructure import model
from backend.teaching import service, typed_state, typed_teaching
from backend.contracts import SessionError
from test_typed_knowledge import MEMORY, CONCEPT, DESIGN, ScriptedModel
from test_reliable_commands import active


def session(*types):
    points = compile_points(submit_knowledge_points(points=list(types or (MEMORY, CONCEPT, DESIGN))))
    dialogue = service.new_dialogue(points)
    # These archived fixtures exercise the earlier, pinned assessment protocol.
    dialogue.pop("mastery_version", None)
    return {"id": "typed", "phase": "video", "lessonId": "lesson", "videoRevision": "rev",
            "courses": [], "messages": [], "preparation": "ready", "stateVersion": 1,
            "dialogue": dialogue}


def reply(question="当前问题？", assistance="none"):
    return AIMessage(content=json.dumps({"text": "具体反馈。" + question,
        "question": question, "assistance": assistance}, ensure_ascii=False))


def assessment(result="partial", *, tool_id="assess"):
    return AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": tool_id,
        "args": {"intent": "answer", "assessment": {"result": result, "evidence": "学生自己的表达",
                 "known_parts": ["已会部分"], "gaps": [] if result == "mastered" else ["具体缺口"],
                 "next_step": "从有缺口的一步继续"}}}])


def scripted(monkeypatch, *responses):
    client = ScriptedModel(responses=list(responses))
    monkeypatch.setattr(model, "teaching_model", lambda: client)
    return client


@pytest.mark.parametrize("after_class", [False, True])
def test_natural_reply_receives_all_current_point_exchanges_across_rounds(monkeypatch, after_class):
    state = service.new_dialogue(compile_points(submit_knowledge_points(points=[MEMORY])))
    scripted(monkeypatch, AIMessage(content="先说说循环的结构？"))
    state = typed_teaching.run(state, opening=True)
    expected = []
    # More than two exchanges catches accidental truncation. Six classroom
    # answers cross from recall to reinforcement using the existing 5/8 rules.
    for index in range(6):
        question = state["points"][0]["latest_question"]
        answer = f"第{index + 1}次还是不知道"
        expected.extend([{"role": "assistant", "text": question}, {"role": "student", "text": answer}])
        state["student_text"] = answer
        packet = AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "assessment",
            "args": {"intent": "answer", "assessment": {"answer_result": "unanswered", "evidence": answer,
                "updates": [], "next_step": "讲清一步，再让学生完成下一步"}}}])
        client = scripted(monkeypatch, packet, AIMessage(content=f"第{index + 1}种帮助，请继续下一步。"))
        state = typed_teaching.run(state, after_class=after_class)
        context = json.loads(client.seen[-1][0].content.splitlines()[-1])
        assert context["pointConversation"] == expected
        assert context["studentText"] == answer
        assert context["focus"]["known_parts"] == []
        assert all(r["status"] == "unconfirmed" for r in context["focus"]["requirements"])
        assert "assessment_history" not in context["focus"]
        assert "help_history" not in context["focus"]
    if not after_class:
        assert state["stage"] == "reinforce"
        assert state["points"][0]["recall_attempts"] == 5
        assert state["points"][0]["reinforce_attempts"] == 1


def test_natural_reply_does_not_receive_previous_points_conversation(monkeypatch):
    state = service.new_dialogue(compile_points(submit_knowledge_points(points=[MEMORY, CONCEPT])))
    scripted(monkeypatch, AIMessage(content="上一点的独有题目？"))
    state = typed_teaching.run(state, opening=True)
    state["student_text"] = "上一点的独有回答"
    updates = [{"requirement_id": r["id"], "status": "demonstrated", "evidence": "学生已说明", "gap": ""}
               for r in state["points"][0]["requirements"]]
    packet = AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "assessment",
        "args": {"intent": "answer", "assessment": {"answer_result": "correct", "evidence": "学生已说明",
            "updates": updates, "next_step": "继续下一点"}}}])
    client = scripted(monkeypatch, packet, AIMessage(content="请解释当前概念。"))
    result = typed_teaching.run(state)
    context = json.loads(client.seen[-1][0].content.splitlines()[-1])
    assert context["focus"]["id"] == result["points"][1]["id"]
    assert context["pointConversation"] == []
    assert result["points"][0]["status"] == "mastered"


def test_postclass_reply_keeps_prior_unanswered_opening_without_new_state_fields(monkeypatch):
    state = service.new_dialogue(compile_points(submit_knowledge_points(points=[MEMORY])))
    scripted(monkeypatch, AIMessage(content="课堂的原问题？"))
    state = typed_teaching.run(state, opening=True)
    fields = set(state)
    point_fields = set(state["points"][0])
    scripted(monkeypatch, AIMessage(content="课后接着原问题，先说明第一步？"))
    state = typed_teaching.run(state, opening=True, after_class=True)
    state["student_text"] = "第一步我还不会"
    packet = AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "assessment",
        "args": {"intent": "answer", "assessment": {"answer_result": "unanswered", "evidence": "明确说不会",
            "updates": [], "next_step": "示范第一步"}}}])
    client = scripted(monkeypatch, packet, AIMessage(content="我先示范这一步，请接着完成下一步。"))
    state = typed_teaching.run(state, after_class=True)
    context = json.loads(client.seen[-1][0].content.splitlines()[-1])
    assert context["pointConversation"] == [
        {"role": "assistant", "text": "课堂的原问题？"},
        {"role": "assistant", "text": "课后接着原问题，先说明第一步？"},
        {"role": "student", "text": "第一步我还不会"}]
    assert set(state) == fields
    assert set(state["points"][0]) == point_fields | {"postclass_rounds"}


def apply(base, changed, command="test"):
    return records.transition(base, dict(base, **changed), command_id=command)


def opened(monkeypatch, *types):
    scripted(monkeypatch, reply("原始具体题目？"))
    base = session(*types)
    return apply(base, service.start_discussion(base), "open")


def test_agent_tool_updates_real_state_and_changes_type_before_final_reply(monkeypatch):
    base = opened(monkeypatch, MEMORY, DESIGN)
    old = deepcopy(base)
    client = scripted(monkeypatch, assessment("mastered"), reply("构造一个累加程序？"))
    after = apply(base, service.classroom_turn(base, "我自己解释清楚了"), "answer")
    assert base == old
    assert len(client.seen) == 2
    assert client.settings[0]["tool_choice"]["function"]["name"] == "submit_current_assessment"
    assert client.settings[1]["tool_choice"] == "none"
    assert "当前类型策略：按 capability" in client.seen[1][0].content
    first, second = after["dialogue"]["points"]
    assert first["status"] == "mastered" and first["recall_attempts"] == 1
    assert second["recall_attempts"] == 0 and second["task_question"] == "构造一个累加程序？"
    obs = after["learningRecords"]["observations"][-1]
    assert obs["topicId"] == first["id"] and obs["studentExcerpt"] == "我自己解释清楚了"


def test_five_then_eight_rounds_and_only_unmastered_points_are_reinforced():
    state = session(MEMORY, CONCEPT)["dialogue"]
    state["student_text"] = "回答"
    a = assessment().tool_calls[0]["args"]["assessment"]
    for _ in range(5):
        state = typed_state.advance(state, "answer", a)
    assert state["stage"] == "recall" and typed_state.current(state)["type"] == "concept"
    state = typed_state.advance(state, "answer", {**a, "result": "mastered"})
    assert state["stage"] == "reinforce" and typed_state.current(state)["type"] == "memory"
    for _ in range(8):
        state = typed_state.advance(state, "answer", a)
    assert state["stage"] == "wrapup" and state["completion_reason"] == "rounds_exhausted"
    assert state["points"][0]["status"] == "partial"
    assert state["points"][1]["reinforce_attempts"] == 0


def test_last_round_mastery_wins_without_extra_confirmation():
    state = session(MEMORY)["dialogue"]
    state["student_text"] = "回答"
    a = assessment().tool_calls[0]["args"]["assessment"]
    for _ in range(4):
        state = typed_state.advance(state, "answer", a)
    state = typed_state.advance(state, "answer", {**a, "result": "mastered"})
    assert state["stage"] == "wrapup" and state["completion_reason"] == "all_mastered"
    assert not state["points"][0]["reinforcement_required"]


def test_help_gap_and_original_task_survive_reinforcement(monkeypatch):
    base = opened(monkeypatch, DESIGN)
    for i in range(5):
        scripted(monkeypatch, assessment(), reply("针对缺口的追问？", "hint"))
        base = apply(base, service.classroom_turn(base, "我的方案还不完整"), f"answer-{i}")
    point = base["dialogue"]["points"][0]
    assert base["dialogue"]["stage"] == "reinforce"
    assert point["task_question"] == "原始具体题目？"
    assert point["known_parts"] == ["已会部分"] and point["gaps"] == ["具体缺口"]
    assert len(point["help_history"]) == 5
    assert all(h["text"] == "具体反馈。针对缺口的追问？" for h in point["help_history"])
    client = scripted(monkeypatch, assessment("mastered"), reply("", "none"))
    after = apply(base, service.classroom_turn(base, "提示后我自己修正并解释"), "master")
    assert after["dialogue"]["stage"] == "wrapup"
    assert "具体缺口" in client.seen[0][0].content


@pytest.mark.parametrize("responses", [
    (assessment(), RuntimeError("provider failed")),
    (reply(),),
])
def test_failed_reply_or_missing_tool_does_not_mutate_progress(monkeypatch, responses):
    base = opened(monkeypatch, MEMORY)
    before = deepcopy(base)
    scripted(monkeypatch, *responses)
    with pytest.raises(SessionError):
        service.classroom_turn(base, "回答")
    assert base == before


def test_postclass_exit_resume_and_completion_do_not_create_open_questions(monkeypatch):
    base = opened(monkeypatch, MEMORY)
    base = apply(base, service.finish(base), "finish")
    scripted(monkeypatch, reply("继续原题的缺口？"))
    base = apply(base, service.start_postclass(base), "post-open")
    assert base["postclassStage"] == "remediation"
    base = apply(base, service.finish(base), "exit")
    assert base["postclassStage"] == "paused"
    with pytest.raises(SessionError):
        service.postclass_turn(base, "已经退出")
    scripted(monkeypatch, reply("继续原题的缺口？"))
    base = apply(base, service.start_postclass(base), "resume")
    scripted(monkeypatch, assessment("mastered"), reply(""))
    base = apply(base, service.postclass_turn(base, "现在自己说明白了"), "complete")
    assert base["postclassStage"] == "completed"
    assert base["feedback"]["counts"]["mastered"] == 1
    before_messages = deepcopy(base["messages"])
    monkeypatch.setattr(model, "teaching_model", lambda: pytest.fail("Completed lesson must not call model"))
    base = apply(base, service.start_postclass(base), "already-complete")
    assert base["messages"] == before_messages
    assert base["classroomFeedback"]["counts"]["mastered"] == 0


def test_feedback_distinguishes_known_gaps_unconfirmed_and_unseen():
    base = session(MEMORY, CONCEPT, DESIGN)
    state = base["dialogue"]
    state["student_text"] = "提问"
    state = typed_state.advance(state, "question", None)
    base["dialogue"] = state
    feedback = typed_state.feedback(base)
    assert feedback["points"][0]["label"] == "本次尚未确认"
    assert feedback["points"][1]["label"] == "尚未学习／评估"
    assert "分" not in feedback["summary"]
    assert "recallRounds" not in feedback["points"][0]


def test_old_v2_snapshot_keeps_legacy_flow_and_v1_does_not_upgrade():
    state = session(MEMORY)["dialogue"]
    state["flow_version"] = 3
    assert not service.is_typed({"dialogue": state})
    assert not typed_state.active(service.new_dialogue([{"id": "v1", "title": "旧点", "content": "旧内容"}]))


def test_repeated_tool_call_in_one_run_only_updates_progress_once(monkeypatch):
    base = opened(monkeypatch, MEMORY)
    client = scripted(monkeypatch, assessment(), assessment(tool_id="repeat"), reply("继续解释？"))
    changed = service.classroom_turn(base, "回答")
    point = changed["dialogue"]["points"][0]
    assert len(client.seen) == 3
    assert point["recall_attempts"] == len(point["assessment_history"]) == 1


def test_question_counts_as_one_input_without_inventing_mastery(monkeypatch):
    base = opened(monkeypatch, MEMORY)
    call = AIMessage(content="", tool_calls=[{"id": "help", "name": "submit_current_assessment",
                                              "args": {"intent": "question", "assessment": None}}])
    scripted(monkeypatch, call, reply("请再试着说明？", "explanation"))
    changed = service.classroom_turn(base, "可以解释一下吗？")
    point = changed["dialogue"]["points"][0]
    assert point["status"] == "unclear" and point["recall_attempts"] == 1
    assert point["known_parts"] == []


def test_real_database_restores_task_gaps_and_idempotent_agent_result(pg, active, monkeypatch):
    from backend.infrastructure import persistence, commands
    from backend import main
    from conftest import business_client
    from test_reliable_commands import command
    from backend.session import service as learning_session
    base = session(DESIGN)
    base.update(id="typed-db", context=deepcopy(active[2]), courses=deepcopy(active[1]["courses"]),
                classroomId="room", videoRevision="revision", stateVersion=0)
    persistence.save(base, 0)
    client = business_client(main)
    def post(body):
        return client.post("/api/session/typed-db/commands", json={**body, "launch_token": "ticket"})
    scripted(monkeypatch, reply("数据库保存的原题？"))
    response = post(command(base, "start_discussion"))
    assert response.status_code == 200, response.text
    saved = persistence.restore("typed-db")
    scripted(monkeypatch, assessment(), reply("继续原题？", "hint"))
    body = command(saved)
    response = post(body)
    assert response.status_code == 200, response.text
    model_client = model.teaching_model()
    assert len(model_client.seen) == 2
    learning_session.sessions.clear()
    restored = persistence.restore("typed-db")
    point = restored["dialogue"]["points"][0]
    assert point["task_question"] == "数据库保存的原题？"
    assert point["gaps"] == ["具体缺口"] and point["recall_attempts"] == 1
    assert point["help_history"][0]["kind"] == "hint"
    repeated = post(body)
    assert repeated.status_code == 200 and len(model_client.seen) == 2
    assert len(commands.read("typed-db", body["commandId"])["result"]["dialogue"]["points"][0]["assessment_history"]) == 1


def test_real_database_failed_final_reply_rolls_back_progress_and_can_retry(pg, active, monkeypatch):
    from backend.infrastructure import persistence, commands
    from backend import main
    from conftest import business_client
    from test_reliable_commands import command
    base = session(MEMORY)
    base.update(id="typed-db", context=deepcopy(active[2]), courses=deepcopy(active[1]["courses"]),
                classroomId="room", videoRevision="revision", stateVersion=0)
    persistence.save(base, 0)
    client = business_client(main)
    def post(body):
        return client.post("/api/session/typed-db/commands", json={**body, "launch_token": "ticket"})
    scripted(monkeypatch, reply("原题？"))
    assert post(command(base, "start_discussion")).status_code == 200
    body = command(persistence.restore("typed-db"))
    scripted(monkeypatch, assessment("mastered"), RuntimeError("final provider failure"))
    assert post(body).status_code == 503
    restored = persistence.restore("typed-db")
    assert restored["dialogue"]["points"][0]["recall_attempts"] == 0
    assert restored["dialogue"]["points"][0]["status"] == "unseen"
    assert commands.read("typed-db", body["commandId"])["status"] == "failed"
    scripted(monkeypatch, assessment("mastered"), reply(""))
    response = post(body)
    assert response.status_code == 200, response.text
    assert persistence.restore("typed-db")["dialogue"]["points"][0]["recall_attempts"] == 1


def test_database_exit_cancels_inflight_postclass_reply_without_late_progress(pg, active, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from backend.infrastructure import persistence, commands
    from backend import main
    from conftest import business_client
    from test_reliable_commands import command
    base = session(MEMORY)
    base.update(id="typed-db", context=deepcopy(active[2]), courses=deepcopy(active[1]["courses"]),
                classroomId="room", videoRevision="revision", stateVersion=0)
    persistence.save(base, 0)
    client = business_client(main)
    def post(body):
        return client.post("/api/session/typed-db/commands", json={**body, "launch_token": "ticket"})
    scripted(monkeypatch, reply("原题？"))
    assert post(command(base, "start_discussion")).status_code == 200
    assert post(command(persistence.restore("typed-db"), "finish")).status_code == 200
    scripted(monkeypatch, reply("继续原题？"))
    assert post(command(persistence.restore("typed-db"), "continue_after_class")).status_code == 200
    before = persistence.restore("typed-db")
    entered, release = Event(), Event()
    original = ScriptedModel._generate
    def gated(self, messages, **kwargs):
        if kwargs.get("tool_choice") == "none":
            entered.set()
            assert release.wait(10)
        return original(self, messages, **kwargs)
    scripted(monkeypatch, assessment("mastered"), reply(""))
    monkeypatch.setattr(ScriptedModel, "_generate", gated)
    body = command(before, "postclass_answer")
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(post, body)
        try:
            assert entered.wait(5)
            exit_response = post(command(persistence.restore("typed-db"), "finish"))
            assert exit_response.status_code == 200, exit_response.text
        finally:
            release.set()
        future.result(timeout=10)
    after = persistence.restore("typed-db")
    assert after["postclassStage"] == "paused"
    assert after["messages"] == before["messages"]
    assert after["dialogue"]["points"] == before["dialogue"]["points"]
    assert commands.read("typed-db", body["commandId"])["status"] == "cancelled"


def test_real_chat_adapter_uses_updated_type_without_replaying_old_tool_arguments(monkeypatch):
    import httpx
    from langchain_openai import ChatOpenAI
    state = session(MEMORY, DESIGN)["dialogue"]
    state["student_text"] = "我能自己说清基本语法"
    state["points"][0]["task_question"] = "说出 for 的结构？"
    requests = []
    def transport(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            call = assessment("mastered").tool_calls[0]
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": call["id"],
                "type": "function", "function": {"name": call["name"], "arguments": json.dumps(call["args"])}}]}
        else:
            message = {"role": "assistant", "content": reply("请构造累加程序？").content}
        return httpx.Response(200, json={"id": "offline-teaching", "object": "chat.completion", "created": 0,
            "model": "offline", "choices": [{"index": 0, "message": message,
                "finish_reason": "tool_calls" if len(requests) == 1 else "stop"}]})
    with httpx.Client(transport=httpx.MockTransport(transport)) as http:
        client = ChatOpenAI(model="offline", api_key="offline-test-key", base_url="https://offline.test/v1",
                            max_retries=0, http_client=http)
        monkeypatch.setattr(model, "teaching_model", lambda: client)
        result = typed_teaching.run(state)
    assert len(requests) == 2 and requests[0]["parallel_tool_calls"] is False
    assert requests[0]["tool_choice"]["function"]["name"] == "submit_current_assessment"
    assert requests[1]["tool_choice"] == "none"
    assert not any(m["role"] == "tool" or m.get("tool_calls") for m in requests[1]["messages"])
    assert "当前类型策略：按 capability" in requests[1]["messages"][0]["content"]
    assert result["points"][0]["status"] == "mastered" and result["points"][1]["recall_attempts"] == 0
