"""Pilot behavior through the teaching/session Interface, with a scripted model Adapter."""
from copy import deepcopy
import json
from threading import Lock

import pytest

from backend.teaching import dynamic_teaching as dynamic
from backend.content import lesson_content
from backend.evidence import records as learning_records
from backend.infrastructure import model
from backend.teaching import service as teaching
from backend.session import service as learning_session
from backend.session import command_runtime
from backend.contracts import SessionError
from test_learning_session_flow import classroom


def video():
    points = [{"id": "average", "title": "平均数", "content": "平均数利用全部数据。", "sourceIds": ["s1"]},
              {"id": "median", "title": "中位数", "content": "中位数按排序后位置确定。", "sourceIds": ["s2"]}]
    body = lesson_content.build("course", "lesson", "revision", "test-v1", points,
        [{"id": "s1", "content": points[0]["content"]}, {"id": "s2", "content": points[1]["content"]}])
    return learning_records.normalize({"id": "session", "context": {"courseId": "course", "userId": "student",
        "publication": {"id": "pub", "version": 1}},
        "courses": [], "lessonId": "lesson", "videoRevision": "revision", "phase": "video",
        "stateVersion": 1, "contentGeneration": 0, "messages": [], "preparation": "ready",
        "dialogue": teaching.new_dialogue(points), "flowVersion": dynamic.FLOW,
        "teachingPolicy": deepcopy(dynamic.POLICY), "lessonContent": body, "contentRef": lesson_content.reference(body)})


def apply(session, changed, command="test"):
    return learning_records.transition(session, dict(session, **changed), command_id=command)


def scripted(monkeypatch, actions=None, mutate=None):
    """Select action from actual input; renderer binds the program-created task."""
    actions = list(actions or [])
    calls = []
    def complete(prompt, raw, timeout):
        payload = json.loads(raw)
        calls.append((prompt, payload, timeout))
        if prompt == dynamic.REPLY_PROMPT:
            task = payload["task"]
            return json.dumps({"taskId": task["taskId"], "sourceRefs": task["sourceRefs"],
                "assistanceKind": payload["decision"]["assistanceKind"],
                "text": ("请具体说明你的判断。" if payload["studentText"] else "") + task["question"]}, ensure_ascii=False)
        state, topics = payload["teachingState"], payload["topics"]
        action = actions.pop(0) if actions else "continue_topic" if state["task"] else "switch_topic"
        target = topics[0]["topicId"]
        if action == "return_to_task":
            target = state["returnPoint"]["topicId"]
        elif action == "continue_topic":
            target = state["task"]["topicId"]
        elif state["task"] and action == "switch_topic":
            target = topics[-1]["topicId"]
        topic = next(t for t in topics if t["topicId"] == target)
        result = {"basedOnStateVersion": payload["stateVersion"], "taskId": (state["task"] or {}).get("taskId"),
            "action": action, "targetTopicId": target, "reasonEvidenceIds": [], "reason": "根据当前学生表达继续核对",
            "observation": {"supportedUnderstanding": "学生提到了全部数据" if "全部" in (payload["studentText"] or "") else "",
                            "uncertainties": "还需说明适用条件"},
            "assistanceKind": "hint" if payload["intent"] == "request_help" else "none",
            "task": {"question": f"任务 {state['taskOrdinal'] + 1}：请用本课依据解释你的选择。",
                     "purpose": "核对概念的适用条件", "criteria": "根据本课原文说明依据和条件",
                     "sourceRefs": topic["sourceRefs"]}}
        if mutate:
            mutate(result, payload)
        return json.dumps(result, ensure_ascii=False)
    monkeypatch.setattr(model, "complete_bounded", complete)
    return calls


def opened(monkeypatch, actions=None, mutate=None):
    calls = scripted(monkeypatch, actions, mutate)
    base = video()
    return apply(base, teaching.start_discussion(base), "opening"), calls


def test_default_legacy_allowlist_is_scoped_and_old_sessions_never_upgrade(monkeypatch):
    monkeypatch.delenv("STUDENT_DYNAMIC_PILOT_SCOPES", raising=False)
    assert teaching.select_flow({"courseId": "course"}, "lesson") == {"flowVersion": dynamic.LEGACY}
    monkeypatch.setenv("STUDENT_DYNAMIC_PILOT_SCOPES", '[{"courseId":"course","lessonId":"lesson"}]')
    assert teaching.select_flow({"courseId": "course"}, "lesson")["flowVersion"] == dynamic.FLOW
    assert teaching.select_flow({"courseId": "other"}, "lesson")["flowVersion"] == dynamic.LEGACY
    assert teaching.select_flow(None, "lesson")["flowVersion"] == dynamic.LEGACY
    legacy = video()
    legacy.pop("flowVersion")
    assert not teaching.is_dynamic(legacy)
    for bad in ('invalid', '{}', '[{"courseId":"course"}]'):
        monkeypatch.setenv("STUDENT_DYNAMIC_PILOT_SCOPES", bad)
        assert teaching.select_flow({"courseId": "course"}, "lesson")["flowVersion"] == dynamic.LEGACY


def test_task_question_sources_and_criteria_fixed_before_first_answer(monkeypatch):
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "isolated-view-test-key")
    session, calls = opened(monkeypatch)
    task = session["learningRecords"]["tasks"][0]
    assert task["question"] in session["messages"][0]["text"]
    assert task["questionMessageId"] == session["messages"][0]["messageId"]
    assert task["criteria"] and task["sourceRefs"] and not session["learningRecords"]["observations"]
    view = learning_session.state(session)
    assert "criteria" not in view["currentTaskPublic"] and view["learningProgress"] is None
    assert "context" not in calls[0][1] and "launchToken" not in str(calls)
    assert calls[0][2] <= dynamic.POLICY["modelCallSeconds"]


@pytest.mark.parametrize("field,value", [("action", "skip_everything"), ("basedOnStateVersion", 999),
    ("taskId", "other"), ("targetTopicId", "outside"), ("reasonEvidenceIds", ["invented"]),
    ("assistanceKind", "invented")])
def test_invalid_decision_one_repair_then_no_stage_or_message_change(monkeypatch, field, value):
    base = video()
    calls = scripted(monkeypatch, mutate=lambda result, payload: result.update({field: value}))
    snapshot = deepcopy(base)
    with pytest.raises(SessionError) as failure:
        teaching.start_discussion(base)
    assert failure.value.code == "INVALID_DECISION"
    assert base == snapshot and len(calls) == 2


def test_one_repair_can_recover_without_publishing_invalid_proposal(monkeypatch):
    calls = scripted(monkeypatch, mutate=lambda result, payload: result.update(action="wrong") if "repair" not in payload else None)
    base = video()
    after = apply(base, teaching.start_discussion(base))
    assert len(calls) == 3 and len(after["learningRecords"]["decisions"]) == 1
    assert after["learningRecords"]["decisions"][0]["action"] == "switch_topic"


def test_different_answers_produce_different_observations_and_actions(monkeypatch):
    base, _ = opened(monkeypatch)
    scripted(monkeypatch, ["continue_topic"])
    clarification = apply(base, teaching.classroom_turn(base, "我不确定"))
    scripted(monkeypatch, ["start_independent_attempt"])
    attempt = apply(base, teaching.classroom_turn(base, "我认为利用了全部数据"))
    assert clarification["currentTaskId"] == base["currentTaskId"]
    assert attempt["currentTaskId"] != base["currentTaskId"]
    assert attempt["teachingState"]["stage"] == "independent_attempt"
    assert attempt["messages"][-2]["phase"] == "tutoring"
    assert attempt["messages"][-1]["phase"] == "independent_attempt"
    assert attempt["learningRecords"]["observations"][-1]["supportedUnderstanding"]
    assert not clarification["learningRecords"]["observations"][-1]["supportedUnderstanding"]


def test_independent_answer_is_scoped_and_help_cannot_explain_prior_answer(monkeypatch):
    session, _ = opened(monkeypatch, ["switch_topic", "start_independent_attempt", "continue_topic", "continue_topic", "continue_topic"])
    session = apply(session, teaching.classroom_turn(session, "课堂回答"), "one")
    task = session["currentTaskId"]
    first = apply(session, teaching.classroom_turn(session, "独立解释"), "two")
    obs = first["learningRecords"]["observations"][-1]
    assert obs["taskId"] == task and obs["independence"] == "no_recorded_help_in_task"
    helping = apply(first, teaching.dynamic_command(first, "request_help", {"text": "给个提示"}), "help")
    assert helping["learningRecords"]["observations"][-2] == obs
    answered = apply(helping, teaching.classroom_turn(helping, "提示后回答"), "three")
    last = answered["learningRecords"]["observations"][-1]
    assert last["independence"] == "assisted" and last["assistanceRefs"]
    assert last["studentExcerpt"] == "提示后回答"


def test_summary_requires_attempt_and_burden_limit_stops_without_extra_model_call(monkeypatch):
    session, _ = opened(monkeypatch)
    assert "request_summary" not in dynamic.allowed(session)
    session["teachingState"]["turns"] = dynamic.POLICY["maxTurns"]
    monkeypatch.setattr(model, "complete_bounded", lambda *a: pytest.fail("burden exit must be deterministic"))
    after = apply(session, teaching.classroom_turn(session, "最后一次回答"))
    assert after["teachingState"]["stage"] == "summary" and after["phase"] == "discussion"
    done = apply(after, teaching.finish(after))
    assert done["phase"] == "done" and done["feedback"]["uncovered"]
    assert done["feedback"]["counts"]["mastered"] == 0


def test_pause_preserves_task_and_finish_is_allowed_while_paused(monkeypatch):
    session, calls = opened(monkeypatch)
    paused = apply(session, teaching.dynamic_command(session, "pause", {}))
    assert paused["currentTaskId"] == session["currentTaskId"]
    with pytest.raises(SessionError):
        teaching.classroom_turn(paused, "不能在暂停期间推进")
    resumed = apply(paused, teaching.dynamic_command(paused, "resume_activity", {}))
    assert resumed["currentTaskId"] == session["currentTaskId"]
    done = apply(paused, teaching.finish(paused))
    assert done["phase"] == "done" and len(calls) == 2


def test_postclass_preserves_classroom_feedback_and_has_distinct_episode(monkeypatch):
    session, _ = opened(monkeypatch)
    session = apply(session, teaching.classroom_turn(session, "课堂表达"))
    done = apply(session, teaching.finish(session))
    classroom = deepcopy(done["classroomFeedback"])
    done["lock"] = Lock()
    after = apply(done, teaching.start_postclass(done), "postclass")
    assert after["phase"] == "done" and after["postclassStage"] == "open"
    assert after["currentTaskId"] != session["currentTaskId"]
    after = apply(after, teaching.postclass_turn(after, "课后补充"), "postanswer")
    assert after["classroomFeedback"] == classroom
    assert after["learningRecords"]["observations"][-1]["episodeId"] != session["learningRecords"]["observations"][-1]["episodeId"]
    assert "课后补充" in after["feedback"]["points"][0]["evidence"]


def test_help_question_can_return_to_saved_original_task(monkeypatch):
    session, _ = opened(monkeypatch, ["switch_topic", "switch_topic", "return_to_task"])
    original = session["currentTaskId"]
    asked = apply(session, teaching.dynamic_command(session, "ask_question", {"text": "我想先问另一个主题"}), "ask")
    assert asked["teachingState"]["returnPoint"]["taskId"] == original
    returned = apply(asked, teaching.classroom_turn(asked, "这个疑问清楚了"), "return")
    assert returned["currentTaskId"] == original and returned["teachingState"]["returnPoint"] is None


def test_pinned_flow_and_policy_survive_allowlist_shutdown(monkeypatch):
    session, _ = opened(monkeypatch)
    monkeypatch.setenv("STUDENT_DYNAMIC_PILOT_SCOPES", "[]")
    after = apply(session, teaching.classroom_turn(session, "继续原流程"))
    assert after["flowVersion"] == dynamic.FLOW
    altered = deepcopy(session)
    altered["teachingPolicy"]["maxTurns"] = 999
    with pytest.raises(SessionError):
        teaching.classroom_turn(altered, "不能临场改规则")


def test_new_dynamic_command_requires_current_task_and_paused_input_is_rejected(monkeypatch):
    session, _ = opened(monkeypatch)
    with pytest.raises(SessionError) as failure:
        command_runtime.validate(session, "submit_answer", {"text": "回答", "taskId": "old"})
    assert failure.value.code == "TASK_CHANGED"
    paused = apply(session, teaching.dynamic_command(session, "pause", {}))
    with pytest.raises(SessionError) as failure:
        command_runtime.validate(paused, "submit_answer", {"text": "回答", "taskId": session["currentTaskId"]})
    assert failure.value.code == "INVALID_ACTION"


def test_unbound_rendered_reply_and_missing_source_do_not_publish(monkeypatch):
    base = video()
    scripted(monkeypatch)
    original = model.complete_bounded
    monkeypatch.setattr(model, "complete_bounded", lambda prompt, payload, timeout:
        '{"taskId":"invented","text":"跳过全部阶段"}' if prompt == dynamic.REPLY_PROMPT else original(prompt, payload, timeout))
    with pytest.raises(SessionError) as failure:
        teaching.start_discussion(base)
    assert failure.value.code == "INVALID_DECISION" and base["phase"] == "video"
    base.pop("lessonContent")
    with pytest.raises(SessionError):
        teaching.start_discussion(base)


def test_source_injection_and_reused_independent_question_are_rejected(monkeypatch):
    base, _ = opened(monkeypatch)
    current = base["learningRecords"]["tasks"][0]
    scripted(monkeypatch, ["start_independent_attempt", "start_independent_attempt"],
        mutate=lambda result, payload: result["task"].update(question=current["question"]))
    with pytest.raises(SessionError) as failure:
        teaching.classroom_turn(base, "不能重用原题冒充独立新题")
    assert failure.value.code == "INVALID_DECISION"
    scripted(monkeypatch, ["start_independent_attempt", "start_independent_attempt"],
        mutate=lambda result, payload: result["task"].update(sourceRefs=[{"sourceId": "outside", "quote": "编造材料"}]))
    with pytest.raises(SessionError) as failure:
        teaching.classroom_turn(base, "引用必须属于当前内容")
    assert failure.value.code == "INVALID_DECISION"


def test_fixed_flow_criteria_and_task_limit_cannot_be_changed_mid_session(monkeypatch):
    session, _ = opened(monkeypatch)
    with pytest.raises(learning_records.InvalidRecord):
        apply(session, {"flowVersion": dynamic.LEGACY})
    changed = deepcopy(session)
    changed["teachingState"]["task"]["criteria"] = "看过回答后再改要求"
    with pytest.raises(SessionError):
        teaching.classroom_turn(changed, "实际回答")
    session["teachingState"]["taskTurns"] = dynamic.POLICY["maxTaskTurns"]
    assert "continue_topic" not in dynamic.allowed(session)


def test_expired_model_response_is_not_committed_and_input_state_survives(monkeypatch):
    session, _ = opened(monkeypatch)
    snapshot = deepcopy(session)
    times = iter([0, 0, dynamic.POLICY["turnTimeoutSeconds"] + 1])
    monkeypatch.setattr(dynamic.time, "monotonic", lambda: next(times))
    with pytest.raises(SessionError) as failure:
        teaching.classroom_turn(session, "保留这一原回答")
    assert failure.value.code == "MODEL_UNAVAILABLE" and session == snapshot


def test_video_finish_has_no_invented_assessment_and_summary_follows_independent_answer(monkeypatch):
    base = video()
    command_runtime.validate(base, "finish", {})
    done = apply(base, teaching.finish(base))
    assert done["phase"] == "done" and not done["feedback"]["supported"]
    assert done["feedback"]["uncovered"] == ["average", "median"]
    session, _ = opened(monkeypatch, ["switch_topic", "start_independent_attempt", "continue_topic", "request_summary"])
    session = apply(session, teaching.classroom_turn(session, "原问题回答"), "one")
    session = apply(session, teaching.classroom_turn(session, "新情境的回答"), "two")
    assert "request_summary" in dynamic.allowed(session)
    summarized = apply(session, teaching.classroom_turn(session, "可以收尾"), "three")
    assert summarized["teachingState"]["stage"] == "summary"


def test_model_timeout_and_retry_configuration_is_applied_when_client_is_created(monkeypatch):
    from types import SimpleNamespace
    settings = []
    monkeypatch.setenv("STUDENT_AGENT_API_KEY", "isolated-model-test-key")
    monkeypatch.setattr(model, "ChatOpenAI", lambda **kwargs: settings.append(kwargs) or
                        SimpleNamespace(invoke=lambda messages: SimpleNamespace(content="{}")))
    model.complete_bounded("system", "data", 12.5)
    model.complete("legacy system", "legacy data")
    assert [(s["timeout"], s["max_retries"]) for s in settings] == [(12.5, 0), (45, 1)]


def test_real_lesson_entry_pins_new_flow_without_converting_existing_legacy(classroom, monkeypatch):
    client, old_sid, *_ = classroom
    monkeypatch.setenv("STUDENT_DYNAMIC_PILOT_SCOPES", '[{"courseId":"course","lessonId":"lesson"}]')
    context = learning_session.platform_access.platform_context("ticket", "lesson")
    source = video()["lessonContent"]
    body = lesson_content.build("course", "lesson", learning_session.video_revision(context, "lesson"),
        "test-v1", source["points"], [{"id": s["sourceId"], "content": s["text"]} for s in source["sources"]])
    monkeypatch.setattr(learning_session.published_knowledge, "read", lambda *a: {
        "status": "ready", "points": body["points"], "coverage": {},
        "contentRef": lesson_content.reference(body), "contentModel": body})
    scripted(monkeypatch)
    sid = client.post("/api/session/start", json={"launch_token": "ticket"}).json()["sessionId"]
    begun = client.post(f"/api/session/{sid}/begin/lesson")
    assert begun.status_code == 200, begun.text
    assert begun.json()["flowVersion"] == dynamic.FLOW
    assert client.post(f"/api/session/{sid}/discussion").status_code == 200
    assert learning_session.sessions[sid]["teachingPolicy"] == dynamic.POLICY
    assert learning_session.sessions[old_sid]["flowVersion"] == dynamic.LEGACY


def test_real_model_observation_lists_are_normalized_without_inventing_student_evidence(monkeypatch):
    scripted(monkeypatch, mutate=lambda result, payload: result.update(observation={
        "supportedUnderstanding": [], "uncertainties": ["尚无学生文字", "需要进一步核对"]}))
    base = video()
    after = apply(base, teaching.start_discussion(base))
    decision = after["learningRecords"]["decisions"][0]
    assert decision["observation"] == {"supportedUnderstanding": "", "uncertainties": "尚无学生文字；需要进一步核对"}
    assert not after["learningRecords"]["observations"]


@pytest.mark.parametrize("unsupported", [[{"text": "不能隐式转成学生证据"}], ["a" * 2001]])
def test_observation_normalization_still_rejects_nontext_or_oversized_items(monkeypatch, unsupported):
    scripted(monkeypatch, mutate=lambda result, payload: result.update(observation={
        "supportedUnderstanding": unsupported, "uncertainties": []}))
    with pytest.raises(SessionError) as failure:
        teaching.start_discussion(video())
    assert failure.value.code == "INVALID_DECISION"
