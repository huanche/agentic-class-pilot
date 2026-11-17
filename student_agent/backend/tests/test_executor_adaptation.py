"""Simplified content exercises the real typed Agent/tool/state/persistence chain."""
from copy import deepcopy
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from backend.content import knowledge, lesson_content
from backend.content.knowledge_schema import submit_knowledge_points
from backend.evidence import records
from backend.infrastructure import model, persistence
from backend.teaching import service, typed_state, typed_teaching, progression
from test_typed_knowledge import CORE, MATERIALS, MEMORY, CONCEPT, DESIGN, ScriptedModel
from test_typed_teaching import session as old_session


def seed(count=1):
    points = knowledge.compile_points(submit_knowledge_points(points=[
        {"name": CORE["name"] + str(i), "explanation": CORE["explanation"]} for i in range(count)]), scope=("course", "lesson"))
    content = lesson_content.build("course", "lesson", "revision", "v3", points, MATERIALS)
    return lesson_content.bind({"id": "adapted", "context": {"courseId": "course", "userId": "student",
        "publication": {"id": "pub", "version": 1}}, "lessonId": "lesson", "videoRevision": "revision",
        "courses": [], "phase": "video", "messages": [], "preparation": "ready", "stateVersion": 1,
        "dialogue": service.new_dialogue(points), "lessonContent": content})


def scripted(monkeypatch, *responses):
    client = ScriptedModel(responses=[AIMessage(content=r) if isinstance(r, str) else r for r in responses])
    monkeypatch.setattr(model, "teaching_model", lambda: client)
    return client


def assess(result="partial", *, gaps=None, observation=None, intent="answer", empty=False):
    args = {"intent": intent, "assessment": None if empty else {
        "result": result, "evidence": "学生说明先初始化再判断", "known_parts": ["初始化顺序"],
        "gaps": ([] if result == "mastered" else ["更新后如何判断"]) if gaps is None else gaps,
        "next_step": "继续尚未说明的部分"}}
    if observation:
        args["observation"] = observation
    return AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "assessment", "args": args}])


def apply(base, changed, command="test"):
    return records.transition(base, dict(base, **changed), command_id=command)


def test_core_uses_original_executor_and_assessment_tool_without_type_or_details(monkeypatch):
    base = seed(2)
    before = deepcopy(base)
    client = scripted(monkeypatch, "先说明循环的执行过程。", assess(), "更新完成后下一步是什么？")
    monkeypatch.setattr(service, "_legacy_classroom_turn", lambda *a: pytest.fail("legacy fallback"))
    base = apply(base, service.start_discussion(base), "opening")
    assert service.is_typed(base) and base["dialogue"]["flow_version"] == 4
    assert base["dialogue"]["recall_round_limit"] == 5
    assert base["dialogue"]["reinforce_round_limit"] == 8
    after = apply(base, service.classroom_turn(base, "先初始化再判断。"))
    point = after["dialogue"]["points"][0]
    assert point["status"] == "partial" and point["gaps"] == ["更新后如何判断"]
    assert point["requirements"] == [] and "type" not in point and "details" not in point
    assert point["assessment_history"][-1]["answer_assessment"]["result"] == "partial"
    assert point["assessment_history"][-1]["question"] == "先说明循环的执行过程。"
    assert len(client.seen) == 3  # one opening, one tool assessment, one reply; no compiler
    context = json.loads(client.seen[1][0].content.splitlines()[-1])
    assert context["focus"]["explanation"] == CORE["explanation"]
    assert context["learnerEvidence"] == ["先初始化再判断。"]
    assert after["learningRecords"]["observations"]
    assert after["learningRecords"]["tasks"][0]["criteriaStatus"] == "point_explanation"
    assert before["phase"] == "video" and before["dialogue"]["points"][0]["attempts"] == 0
    lesson_content.bind(after)


def test_mastery_aggregates_and_advances_without_inventing_requirements(monkeypatch):
    base = seed(2)
    scripted(monkeypatch, "先说明循环。", assess("mastered"), "接着说明下一个知识点。")
    base.update(service.start_discussion(base))
    base.update(service.classroom_turn(base, CORE["explanation"]))
    state = base["dialogue"]
    assert state["points"][0]["status"] == "mastered"
    assert state["points"][0]["recall_done"] and state["points"][0]["reinforce_done"]
    assert typed_state.current(state)["id"] == state["points"][1]["id"]
    assert typed_state.feedback(base)["counts"] == {"mastered": 1, "needs_review": 0, "not_assessed": 1}


def test_invalid_mastery_and_false_observation_are_repaired_in_same_tool_exchange(monkeypatch):
    base = seed()
    client = scripted(monkeypatch, "请说明过程。", assess("mastered", gaps=["还有缺口"]),
        assess(observation={"help_quote": "不是学生说的话"}), assess(), "继续剩余一步。")
    base.update(service.start_discussion(base))
    original = deepcopy(base["dialogue"])
    base.update(service.classroom_turn(base, "先初始化。"))
    assert base["dialogue"]["points"][0]["attempts"] == 1
    assert len(base["dialogue"]["points"][0]["assessment_history"]) == 1
    assert original["points"][0]["attempts"] == 0
    assert any(isinstance(m, ToolMessage) and m.status == "error" for call in client.seen for m in call)


def test_recall_reinforcement_and_postclass_keep_limits_and_continue_evidence(monkeypatch):
    base = seed()
    packets = ["请说明过程。"]
    for _ in range(13):
        packets.extend([assess(), "接着尚未说清的部分。"])
    packets.extend(["继续之前尚未说清的更新步骤。", assess("mastered"), "这部分已完成。"])
    scripted(monkeypatch, *packets)
    base = apply(base, service.start_discussion(base), "open")
    for i in range(13):
        base = apply(base, service.classroom_turn(base, "先初始化再判断。"), str(i))
        if i == 4:
            assert base["dialogue"]["stage"] == "reinforce"
            assert base["dialogue"]["transition"] == "enter_reinforce"
    state = base["dialogue"]
    assert state["stage"] == "wrapup" and state["completion_reason"] == "rounds_exhausted"
    assert state["points"][0]["recall_attempts"] == 5
    assert state["points"][0]["reinforce_attempts"] == 8
    base = apply(base, service.finish(base), "finish")
    base = apply(base, service.start_postclass(base), "postclass")
    assert base["postclassStage"] == "remediation"
    base = apply(base, service.postclass_turn(base, CORE["explanation"]), "post-answer")
    assert base["postclassStage"] == "completed"
    assert base["dialogue"]["points"][0]["mastered_in"] == "postclass"
    assert base["dialogue"]["points"][0]["postclass_rounds"] == 1
    assert len(base["dialogue"]["points"][0]["assessment_history"]) == 14
    assert base["classroomFeedback"]["counts"]["needs_review"] == 1
    assert base["feedback"]["counts"]["mastered"] == 1


def test_null_assessment_preserves_progress_and_help_survives_json_restore(monkeypatch):
    base = seed()
    scripted(monkeypatch, "说明更新后的执行过程。", assess(), "提示：回到循环条件。",
        assess(empty=True, intent="question", observation={"help_quote": "还是不会"}), "直接讲清更新后重新判断条件。")
    base.update(service.start_discussion(base))
    base.update(service.classroom_turn(base, "先初始化。"))
    assert base["dialogue"]["teaching_plan"]["action"] == "concept_hint"
    base = json.loads(json.dumps(base, ensure_ascii=False))
    base.update(service.classroom_turn(base, "还是不会"))
    assert base["dialogue"]["teaching_plan"]["action"] == "concept_explain"
    assert base["dialogue"]["teaching_plan"]["solicitation"] == "none"
    assert base["dialogue"]["points"][0]["attempts"] == 1
    assert base["dialogue"]["points"][0]["status"] == "partial"


@pytest.mark.parametrize("bad", [[{"id":"x", "name":"n"}], [{"id":"x", **CORE, "type":"concept"}],
    [{"id":"x", **CORE}, {"id":"y", "title":"legacy"}]])
def test_malformed_core_never_falls_back(bad):
    with pytest.raises(ValueError):
        service.new_dialogue(bad)


def test_navigation_and_new_lesson_route_do_not_change_existing_versions(monkeypatch):
    from backend.teaching import dynamic_teaching
    monkeypatch.setenv("STUDENT_DYNAMIC_PILOT_SCOPES", '[{"courseId":"course","lessonId":"lesson"}]')
    assert service.select_flow({"courseId":"course"}, "lesson") == {"flowVersion": dynamic_teaching.LEGACY}
    base = seed(2)
    scripted(monkeypatch, "第一点。", "第二点。")
    base.update(service.start_discussion(base))
    base.update(service.navigate_point_turn(base, "next"))
    assert base["dialogue"]["selected_point_id"] == base["dialogue"]["points"][1]["id"]
    assert base["dialogue"]["points"][0]["recall_done"] is True
    base.update(service.navigate_point_turn(base, "previous"))
    assert base["dialogue"]["review_point_id"] == base["dialogue"]["points"][0]["id"]


@pytest.mark.parametrize("kind", ["core", "typed", "scoped", "legacy", "dynamic", "legacy_core"])
def test_persisted_protocol_restores_without_reinitialization(pg, monkeypatch, kind):
    base = seed()
    if kind in {"typed", "scoped"}:
        base = old_session(MEMORY, CONCEPT, DESIGN)
        if kind == "scoped":
            base["dialogue"]["mastery_version"] = 1
        base["context"] = {"courseId": "course", "userId": "student", "publication": {"id":"pub", "version":1}}
    elif kind == "dynamic":
        from test_dynamic_teaching import video
        base = video()
    elif kind == "legacy":
        base = {**base, "dialogue": service.new_dialogue([{"id":"old", "title":"旧点", "content":"旧内容"}])}
        base.pop("lessonContent", None)
        base.pop("contentRef", None)
    elif kind == "legacy_core":
        points = lesson_content.point_payload(base["dialogue"]["points"][0])
        base["dialogue"] = progression.normalize({"stage":"recall", "points":[points], "messages":[],
            "evaluation":{}, "reply":"", "strategy":"ask", "student_text":""})
    base["id"] = "restore-" + kind
    first = base["dialogue"]["points"][0]
    first.update(status="partial", attempts=1, recall_attempts=1, evidence="历史学生原话",
        known_parts=["历史已会内容"], gaps=["历史缺口"],
        assessment_history=[{"stage":"recall", "round":1, "result":"partial",
                             "studentText":"历史学生原话", "evidence":"历史学生原话"}])
    base["stateVersion"] = 0
    expected = deepcopy(base["dialogue"])
    persistence.save(base, 0)
    monkeypatch.setattr(service, "new_dialogue", lambda *a: pytest.fail("must not reinitialize"))
    restored = persistence.restore(base["id"])
    assert restored["dialogue"] == expected
    assert service.is_typed(restored) is (kind in {"core", "typed", "scoped"})
    assert service.is_dynamic(restored) is (kind == "dynamic")


def test_published_ready_core_enters_typed_through_session_sync(monkeypatch):
    from backend.session import service as sessions
    base = seed()
    body = base["lessonContent"]
    base["dialogue"] = None
    base.pop("contentRef")
    base.pop("lessonContent")
    monkeypatch.setattr(sessions.published_knowledge, "read", lambda *a: {
        "status":"ready", "points":body["points"], "contentModel":body, "coverage":{}})
    sessions.sync_published_preparation(base, persist=False)
    assert base["preparation"] == "ready" and service.is_typed(base)
    assert base["dialogue"]["assessment_basis"] == "explanation"
    lesson_content.bind(base)


def test_failed_model_does_not_mutate_original_state_or_fallback(monkeypatch):
    base = seed()
    before = deepcopy(base)
    scripted(monkeypatch, RuntimeError("offline"))
    from backend.contracts import SessionError
    with pytest.raises(SessionError) as error:
        service.start_discussion(base)
    assert error.value.code == "MODEL_UNAVAILABLE"
    assert base == before


def open_core_card(monkeypatch, question_count=2):
    from backend.teaching import question_cards
    base = seed()
    monkeypatch.setattr(question_cards.random, "shuffle", lambda values: None)
    monkeypatch.setattr(model, "complete", lambda *a: json.dumps({"questions": [
        {"prompt": "第%d题：是否先初始化？" % i, "options":["是", "否"], "answer":0,
         "explanation":"先初始化再判断。"} for i in range(question_count)]}))
    scripted(monkeypatch, json.dumps({"text":"用题卡检查执行过程。", "question_card":True}))
    base = apply(base, service.start_discussion(base), "card-open")
    assert len(base["dialogue"]["question_groups"]) == 1
    assert base["messages"][-1]["cardId"] == base["dialogue"]["question_groups"][0]["id"]
    assert "answer" not in service.describe_session(base)["questionGroups"][0]["questions"][0]
    return base


def test_core_cards_partial_grading_restore_and_coverage_use_original_assessor(pg, monkeypatch):
    base = open_core_card(monkeypatch)
    group_id = base["dialogue"]["question_groups"][0]["id"]
    # First, reject treating one locally correct child as complete lesson mastery.
    client = scripted(monkeypatch, assess("mastered"), assess())
    base = apply(base, service.card_turn(base, group_id, {"q1":0}), "first-card")
    assert base["dialogue"]["points"][0]["status"] == "partial"
    assert base["dialogue"]["points"][0]["attempts"] == 0
    assert len(client.seen) == 2  # tool repair only; no unseen teacher reply
    assert len(base["dialogue"]["points"][0]["question_history"]) == 1
    assert len(base["messages"]) == 1
    base["stateVersion"] = 0
    persistence.save(base, 0)
    base = persistence.restore(base["id"])
    assert base["dialogue"]["question_groups"][0]["results"]["q1"]["correct"]
    scripted(monkeypatch, assess())  # all choices right can still leave explanation unconfirmed
    base = apply(base, service.card_turn(base, group_id, {"q2":0}), "second-card")
    assert base["dialogue"]["points"][0]["status"] == "partial"
    assert base["dialogue"]["points"][0]["attempts"] == 1
    assert base["dialogue"]["review_point_id"] == base["dialogue"]["points"][0]["id"]
    assert len(base["dialogue"]["question_groups"]) == 1
    assert len(base["messages"]) == 1


@pytest.mark.parametrize("assisted,choice", [(False,1),(True,0)])
def test_core_card_wrong_or_assisted_is_not_independent_mastery(monkeypatch, assisted, choice):
    base = open_core_card(monkeypatch, question_count=1)
    group = base["dialogue"]["question_groups"][0]
    group["assisted"] = assisted
    scripted(monkeypatch, assess("mastered"), assess())
    result = service.card_turn(base, group["id"], {"q1":choice})["dialogue"]
    assert result["points"][0]["status"] == "partial"
    assert result["question_groups"][0]["results"]["q1"]["correct"] is (choice == 0)
    assert base["dialogue"]["question_groups"][0]["results"] == {}


def test_core_card_provider_failure_keeps_unsubmitted_answers(monkeypatch):
    from backend.contracts import SessionError
    base = open_core_card(monkeypatch)
    before = deepcopy(base)
    scripted(monkeypatch, RuntimeError("offline"))
    with pytest.raises(SessionError) as error:
        service.card_turn(base, base["dialogue"]["question_groups"][0]["id"], {"q1":0})
    assert error.value.code == "MODEL_UNAVAILABLE" and base == before


def test_http_commands_commit_core_tool_evidence_and_restore(pg, monkeypatch):
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from backend import main
    monkeypatch.setenv("PLATFORM_TO_STUDENT_KEY", "core-command-test")
    base = seed()
    base["stateVersion"] = 0
    persistence.save(base, 0)
    scripted(monkeypatch, "请说明循环执行过程。", assess("mastered"), "本点已完成。")
    client = TestClient(main.app, headers={"X-Platform-Learning-Key":"core-command-test",
        "X-Platform-Protocol":"platform-cookie-v1", "X-Platform-User-Id":"student", "X-Platform-Course-Id":"course"})

    def command(kind, payload):
        view = client.get('/api/session/adapted').json()
        response = client.post('/api/session/adapted/commands', json={"commandId":uuid4().hex,
            "type":kind, "payload":payload, "expectedStateVersion":view["stateVersion"],
            "contentGeneration":view["contentGeneration"]})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "completed", response.json()
        return response.json()["sessionView"]

    opened = command("start_discussion", {})
    assert opened["typedTeaching"]
    answered = command("submit_answer", {"text":CORE["explanation"], "taskId":opened["currentTaskPublic"]["taskId"]})
    assert answered["agentStage"] == "wrapup" and answered["typedTeaching"]
    restored = persistence.restore('adapted')
    assert restored["dialogue"]["assessment_basis"] == "explanation"
    assert restored["dialogue"]["points"][0]["status"] == "mastered"
    assert restored["learningRecords"]["observations"][-1]["assessmentResult"] == "mastered"
    assert restored["learningRecords"]["observations"][-1]["studentExcerpt"] == CORE["explanation"]
