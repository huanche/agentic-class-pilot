"""Real teaching create_agent execution with scripted provider messages; no network."""
from copy import deepcopy
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

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


def test_assessment_preserves_teacher_and_student_as_native_message_roles(monkeypatch):
    from teaching_behavior_cases import CASES, build_case
    state = build_case(next(c for c in CASES if c["id"] == "12"))
    items = state["points"][0]["requirements"]
    packet = AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "assessment",
        "args": {"intent": "answer", "assessment": {"answer_result": "correct", "evidence": "学生纠正老师并说明三项",
            "updates": [{"requirement_id": r["id"], "status": "demonstrated", "evidence": state["student_text"], "gap": ""} for r in items],
            "next_step": "继续"}}}])
    client = scripted(monkeypatch, packet, AIMessage(content="你纠正得对，下面看连续存放。"))
    result = typed_teaching.run(state)
    messages = client.seen[0]
    assert any(isinstance(m, AIMessage) and m.content == "a[5]是第5个元素，所以不越界。" for m in messages)
    assert isinstance(messages[-1], HumanMessage)
    assert messages[-1].content == state["student_text"]
    context = json.loads(messages[0].content.splitlines()[-1])
    assert context["learnerEvidence"] == [state["student_text"]]
    assert "a[5]是第5个元素，所以不越界。" not in context["learnerEvidence"]
    assert result["points"][0]["status"] == "mastered"


@pytest.mark.parametrize("after_class", [False, True])
def test_control_request_plan_reports_actual_progress(monkeypatch, after_class):
    from teaching_behavior_cases import CASES, build_case
    state = build_case(next(c for c in CASES if c["id"] == "13"))
    packet = AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "assessment",
        "args": {"intent": "unclear", "assessment": None,
                 "observation": {"control": "skip", "control_quote": "这题先跳过吧"}}}])
    client = scripted(monkeypatch, packet, AIMessage(content="目前按知识点顺序继续；可以先讲清卡住的一步。"))
    result = typed_teaching.run(state, after_class=after_class)
    context = json.loads(client.seen[-1][0].content.splitlines()[-1])
    plan = context["teaching_plan"]
    assert plan["action"] == ("ask" if after_class else "respond")
    assert plan["control"] == {"request": "skip", "applied": after_class}
    assert plan["point_changed"] is after_class
    assert context["focus"]["id"] == state["points"][1 if after_class else 0]["id"]
    assert all(r["status"] == "unconfirmed" for r in result["points"][0]["requirements"])


def test_mixed_answer_and_question_updates_evidence_and_selects_explanation(monkeypatch):
    from teaching_behavior_cases import CASES, build_case
    state = build_case(next(c for c in CASES if c["id"] == "09"))
    packet = AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "assessment",
        "args": {"intent": "answer", "observation": {"help_quote": "但为什么a[5]不能访问？"},
            "assessment": {"answer_result": "partial", "evidence": state["student_text"], "updates": [
                {"requirement_id": r["id"], "status": "demonstrated", "evidence": "下标从0开始，所以合法范围是0到4", "gap": ""}
                for r in state["points"][0]["requirements"][:2]], "next_step": "回答疑问"}}}])
    client = scripted(monkeypatch, packet, AIMessage(content="因为a[5]是第6个位置，超出五个元素的范围。"))
    result = typed_teaching.run(state)
    context = json.loads(client.seen[-1][0].content.splitlines()[-1])
    assert context["teaching_plan"]["action"] == "explain"
    assert context["teaching_plan"]["solicitation"] == "none"
    assert [r["status"] for r in result["points"][0]["requirements"]] == ["demonstrated", "demonstrated", "unconfirmed"]


def test_unsuccessful_help_feedback_selects_localization_instead_of_replay(monkeypatch):
    from teaching_behavior_cases import CASES, build_case
    state = build_case(next(c for c in CASES if c["id"] == "08"))
    packet = AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "assessment",
        "args": {"intent": "question", "assessment": None, "observation": {
            "help_quote": state["student_text"], "teacher_feedback": "你刚才这样讲我没懂，换一种方式。"}}}])
    client = scripted(monkeypatch, packet, AIMessage(content="你卡在从0编号，还是编号与第几个的对应？"))
    typed_teaching.run(state)
    context = json.loads(client.seen[-1][0].content.splitlines()[-1])
    assert context["teaching_plan"]["action"] == "clarify"
    assert context["teaching_plan"]["solicitation"] == "one_task"


def test_request_quotes_from_teacher_cannot_be_used_as_current_student_request(monkeypatch):
    from teaching_behavior_cases import CASES, build_case
    state = build_case(next(c for c in CASES if c["id"] == "13"))
    invalid = AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "bad",
        "args": {"intent": "unclear", "assessment": None, "observation": {
            "control": "skip", "control_quote": "老师编出来的跳过请求"}}}])
    valid = AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "good",
        "args": {"intent": "unclear", "assessment": None, "observation": {
            "control": "skip", "control_quote": state["student_text"]}}}])
    original = deepcopy(state)
    client = scripted(monkeypatch, invalid, valid, AIMessage(content="目前仍按顺序学习当前点。"))
    result = typed_teaching.run(state)
    assert result["points"][0]["attempts"] == 1
    assert len(result["points"][0]["assessment_history"]) == 1
    assert len(client.seen) == 3
    assert state == original
    assert result["teaching_plan"]["control"] == {"request": "skip", "applied": False}


def test_punctuation_alone_does_not_invent_a_specific_help_request():
    from teaching_behavior_cases import CASES, build_case
    state = build_case(next(c for c in CASES if c["id"] == "11"))
    result = typed_state.advance(state, "unclear", None, observation={"help_quote": "？？？"})
    assert typed_state.teaching_plan(result)["action"] == "clarify"
    assert state["points"][0]["attempts"] == 0


def test_correct_work_is_recorded_even_when_pause_request_coexists(monkeypatch):
    from teaching_behavior_cases import CASES, build_case
    state = build_case(next(c for c in CASES if c["id"] == "58"))
    packet = AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "assessment",
        "args": {"intent": "answer", "observation": {"control": "pause", "control_quote": "我先暂停。"},
            "assessment": {"answer_result": "correct", "evidence": state["student_text"], "updates": [
                {"requirement_id": r["id"], "status": "demonstrated", "evidence": state["student_text"], "gap": ""}
                for r in state["points"][0]["requirements"]], "next_step": "继续"}}}])
    scripted(monkeypatch, packet, AIMessage(content="这部分回答已记录；你休息好后可以继续。"))
    result = typed_teaching.run(state)
    assert result["points"][0]["status"] == "mastered"
    assert result["teaching_plan"]["point_changed"] is True
    assert result["teaching_plan"]["answer_result"] == "correct"
    assert result["teaching_plan"]["action"] == "respond"
    assert result["teaching_plan"]["solicitation"] == "none"


def test_missing_assessment_is_repaired_within_existing_call_budget(monkeypatch):
    from teaching_behavior_cases import CASES, build_case
    state = build_case(next(c for c in CASES if c["id"] == "13"))
    packet = AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "assessment",
        "args": {"intent": "unclear", "assessment": None}}])
    client = scripted(monkeypatch, AIMessage(content="先直接回复。"), packet, AIMessage(content="我们继续当前知识点。"))
    result = typed_teaching.run(state)
    assert len(client.seen) == 3
    assert result["points"][0]["attempts"] == 1
    original = deepcopy(state)
    client = scripted(monkeypatch, AIMessage(content="仍然不提交工具。"))
    with pytest.raises(TimeoutError, match="调用预算"):
        typed_teaching.run(state)
    assert len(client.seen) == 4
    assert state == original


def test_assessor_rechecks_original_contract_without_inheriting_old_invented_gap(monkeypatch):
    from teaching_behavior_cases import CASES, build_case
    state = build_case(next(c for c in CASES if c["id"] == "18"))
    point = state["points"][0]
    point.update(gaps=["历史老师误加的打印要求"], evidence="必须输出才能掌握", status="partial")
    point["requirements"][0].update(status="needs_help", gap="历史老师误加的打印要求", evidence="老师要求输出")
    packet = AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "assessment",
        "args": {"intent": "answer", "assessment": {"answer_result": "correct", "evidence": state["student_text"], "updates": [
                {"requirement_id": r["id"], "status": "demonstrated", "evidence": state["student_text"], "gap": ""}
                for r in point["requirements"]], "next_step": "继续"}}}])
    client = scripted(monkeypatch, packet, AIMessage(content="求和代码已经正确。"))
    result = typed_teaching.run(state)
    context = json.loads(client.seen[0][0].content.splitlines()[-1])
    assert "gaps" not in context["focus"]
    assert "gap" not in context["focus"]["requirements"][0]
    assert "currentTask" not in context
    assert context["teacherQuestionForInterpretation"] == point["latest_question"]
    assert "历史老师误加的打印要求" not in client.seen[0][0].content
    assert result["points"][0]["status"] == "mastered"


def test_noise_without_actual_request_selects_clarification_even_if_assessor_says_unanswered():
    from teaching_behavior_cases import CASES, build_case
    state = build_case(next(c for c in CASES if c["id"] == "28"))
    result = typed_state.advance(state, "unclear", {
        "answer_result": "unanswered", "evidence": "无可评估作答", "updates": [], "next_step": ""}, observation={})
    assert typed_state.teaching_plan(result)["action"] == "clarify"


def test_partial_progress_does_not_override_explicit_feedback_to_stop_replaying_help():
    from teaching_behavior_cases import CASES, build_case
    state = build_case(next(c for c in CASES if c["id"] == "60"))
    item = state["points"][0]["requirements"][0]
    result = typed_state.advance(state, "answer", {
        "answer_result": "partial", "evidence": "学生说明从0开始", "updates": [{
            "requirement_id": item["id"], "status": "demonstrated", "evidence": "我知道下标从0开始", "gap": ""}],
        "next_step": ""}, observation={"help_quote": "其他还没想清楚", "teacher_feedback": "别再重复这段解释了"})
    assert result["points"][0]["requirements"][0]["status"] == "demonstrated"
    assert typed_state.teaching_plan(result)["action"] == "clarify"


def test_same_request_span_cannot_be_both_confirmation_and_content_help():
    from teaching_behavior_cases import CASES, build_case
    state = build_case(next(c for c in CASES if c["id"] == "06"))
    with pytest.raises(typed_state.InvalidObservation, match="不能重叠"):
        typed_state.advance(state, "unclear", None, observation={
            "help_quote": "然后呢", "continue_quote": "好，然后呢"})
    assert state["points"][0]["attempts"] == 4
    state["student_text"] = "好，请解释a[5]为什么越界。"
    result = typed_state.advance(state, "question", None, observation={
        "help_quote": "请解释a[5]为什么越界。", "continue_quote": "好"})
    assert result["evaluation"]["observation"]["help_quote"]


@pytest.mark.parametrize("content", [MEMORY, CONCEPT, DESIGN])
def test_opening_covers_the_whole_point_without_marking_requirements_assessed(monkeypatch, content):
    state = service.new_dialogue(compile_points(submit_knowledge_points(points=[content])))
    client = scripted(monkeypatch, AIMessage(content="请完成这个知识点的主要任务。"))
    result = typed_teaching.run(state, opening=True)
    context = json.loads(client.seen[0][0].content.splitlines()[-1])
    expected = [r["id"] for r in state["points"][0]["requirements"]]
    assert context["teaching_plan"]["target_ids"] == expected
    assert context["teaching_plan"]["action"] == "ask"
    assert result["points"][0]["attempts"] == 0
    assert all(r["status"] == "unconfirmed" and not r["evidence"] for r in result["points"][0]["requirements"])


def test_followup_covers_only_remaining_requirements_and_does_not_explain_unasked_items(monkeypatch):
    state = service.new_dialogue(compile_points(submit_knowledge_points(points=[MEMORY])))
    scripted(monkeypatch, AIMessage(content="请说明for循环的结构。"))
    state = typed_teaching.run(state, opening=True)
    state["student_text"] = "先初始化，最后更新"
    items = state["points"][0]["requirements"]
    packet = AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "assessment",
        "args": {"intent": "answer", "assessment": {"answer_result": "partial", "evidence": "学生说明初始化和更新",
            "updates": [{"requirement_id": items[i]["id"], "status": "demonstrated", "evidence": "学生自己说明", "gap": ""}
                        for i in [0, 2]], "next_step": "先讲完所有答案，再要求学生重复已会的初始化和更新"}}}])
    client = scripted(monkeypatch, packet, AIMessage(content="中间如何判断是否继续循环？"))
    result = typed_teaching.run(state)
    context = json.loads(client.seen[-1][0].content.splitlines()[-1])
    assert context["teaching_plan"]["target_ids"] == [items[1]["id"]]
    assert context["teaching_plan"]["action"] == "ask"
    assert "next_step" not in context["focus"]
    assert result["points"][0]["requirements"][1]["status"] == "unconfirmed"
    assert result["points"][0]["recall_attempts"] == 1


def test_pure_question_requests_explanation_without_creating_learning_evidence(monkeypatch):
    state = service.new_dialogue(compile_points(submit_knowledge_points(points=[MEMORY])))
    scripted(monkeypatch, AIMessage(content="请说明for循环的结构。"))
    state = typed_teaching.run(state, opening=True)
    state["student_text"] = "条件判断是什么意思？请直接解释。"
    packet = AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "assessment",
        "args": {"intent": "question", "assessment": None}}])
    client = scripted(monkeypatch, packet, AIMessage(content="条件判断决定是否进入下一次循环。"))
    result = typed_teaching.run(state)
    context = json.loads(client.seen[-1][0].content.splitlines()[-1])
    assert context["teaching_plan"]["action"] == "explain"
    assert "next_step" not in context["focus"]
    assert all(r["status"] == "unconfirmed" and not r["evidence"] for r in result["points"][0]["requirements"])


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
    assert context["previousPoint"]["needs_closure"] is False
    assert "details" not in context["previousPoint"]
    assert "last_teacher_reply" not in context["previousPoint"]


@pytest.mark.parametrize("student_text", ["好，然后呢", "不知道，你直接说吧"])
def test_switch_distinguishes_continuation_from_help_without_replaying_teacher(monkeypatch, student_text):
    state = service.new_dialogue(compile_points(submit_knowledge_points(points=[MEMORY, CONCEPT])))
    previous_reply = "定义形式已讲清：存储类型 数据类型 数组名[整型常量表达式]。"
    point = state["points"][0]
    point.update(recall_attempts=4, attempts=4, latest_question=previous_reply,
                 question_history=[{"text": previous_reply}], task_question="说明定义形式")
    state["student_text"] = student_text
    packet = AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "assessment",
        "args": {"intent": "unclear", "assessment": None}}])
    client = scripted(monkeypatch, packet, AIMessage(content="接着看连续存放。"))
    result = typed_teaching.run(state)
    system = client.seen[-1][0].content
    context = json.loads(system.splitlines()[-1])
    assert context["previousPoint"]["needs_closure"] is False
    assert "last_teacher_reply" not in context["previousPoint"]
    assert context["previousPoint"]["learner_evidence"] == [student_text]
    assert context["teaching_plan"]["point_changed"] is True
    assert result["points"][0]["status"] != "mastered"


def test_deferred_point_keeps_material_for_explaining_help_request_before_switch(monkeypatch):
    state = service.new_dialogue(compile_points(submit_knowledge_points(points=[MEMORY, CONCEPT])))
    point = state["points"][0]
    question = "为什么最后入栈的C先出来？"
    point.update(recall_attempts=4, attempts=4, latest_question=question, task_question=question,
                 known_parts=["学生已说明栈顶删除"], gaps=["尚未连接操作位置与顺序"])
    state["student_text"] = "不知道，你直接说吧"
    packet = AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "assessment",
        "args": {"intent": "answer", "assessment": {"answer_result": "unanswered", "evidence": "学生请求讲解",
            "updates": [], "next_step": "说明C在栈顶所以先出来"}}}])
    client = scripted(monkeypatch, packet, AIMessage(content="C最后入栈，在栈顶所以先出来。下面看下一个知识点。"))
    result = typed_teaching.run(state)
    context = json.loads(client.seen[-1][0].content.splitlines()[-1])
    assert context["transition"] == "defer"
    assert context["studentText"] == "不知道，你直接说吧"
    assert context["previousPoint"]["latest_question"] == question
    assert context["previousPoint"]["details"] == point["details"]
    assert context["previousPoint"]["gaps"]
    assert context["focus"]["id"] == result["points"][1]["id"]
    assert context["pointConversation"] == []
    assert result["points"][0]["recall_attempts"] == 5
    assert result["points"][0]["status"] != "mastered"


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
