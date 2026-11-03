"""Record behavior without I/O: identity, provenance, temporal help and model input."""
from copy import deepcopy
import json

import pytest

from backend.evidence import records as records
from backend.content import lesson_content
from backend.infrastructure import model
from backend.teaching import prompts
from backend.teaching import service as teaching


@pytest.fixture
def video():
    quote = "平均数由全部数据的总和除以数据个数得到。"
    point = {"id": "p", "title": "平均数", "content": quote, "sourceIds": ["scene:one"]}
    materials = [{"id": "scene:one", "title": "平均数", "source": "published-classroom-scene", "content": quote}]
    body = lesson_content.build("course", "lesson", "rev", "compiler-a", [point], materials)
    return {"id": "trace-session", "context": {"userId": "student", "courseId": "course",
            "publication": {"id": "pub", "version": 1}}, "lessonId": "lesson", "videoRevision": "rev",
            "phase": "video", "messages": [], "dialogue": teaching.new_dialogue([point]),
            "lessonContent": body, "contentRef": lesson_content.reference(body), "courses": []}


def start(video):
    return records.transition(video, dict(video, phase="discussion", messages=[{
        "role": "assistant", "text": teaching.opening_text(video["dialogue"]), "phase": "recall"}]), command_id="start")


def turn(session, outcome, monkeypatch, *, command_id="answer", text="学生表达"):
    def complete(system, user):
        data = json.loads(user)
        assert all(set(message) <= {"role", "text", "phase"} for message in
                   data.get("recentMessages", [])), "trace metadata leaked into model input"
        if system == prompts.EVALUATION_PROMPT:
            return json.dumps({"intent": "answer", "assessments": [{"id": "p", "result": outcome,
                                                                       "evidence": "模型对该回答的解释"}]})
        return "围绕当前任务给出回复"
    monkeypatch.setattr(model, "complete", complete)
    raw = teaching.classroom_turn(session, text)
    return records.transition(session, dict(session, **raw), command_id=command_id)


def test_question_is_bound_before_answer_and_ids_survive_retry(video, monkeypatch):
    begun = start(video)
    task = begun["learningRecords"]["tasks"][0]
    assert task["questionMessageId"] == begun["messages"][0]["messageId"]
    assert task["question"] == begun["messages"][0]["text"]
    answered = turn(begun, "partial", monkeypatch)
    assert answered["currentTaskId"] == begun["currentTaskId"]
    assert answered["learningRecords"]["tasks"][0]["question"] == task["question"]
    assert records.transition(begun, answered, command_id="answer") == answered
    assert records.normalize(answered) == answered


def test_help_after_an_answer_only_affects_later_evidence(video, monkeypatch):
    first = turn(start(video), "partial", monkeypatch, command_id="one")
    observation = first["learningRecords"]["observations"][0]
    assert observation["studentExcerpt"] == "学生表达"
    assert observation["assistanceRefs"] == []
    assert observation["independence"] == "unknown"
    assert observation["sourceRefs"][0]["quote"] in video["lessonContent"]["sources"][0]["text"]
    help_item = first["learningRecords"]["assistance"][-1]
    assert help_item["kind"] == "hint" and help_item["guidedPolicy"] is True
    assert help_item["substantive"] is None  # The directive is known; semantic effectiveness is not proven.
    second = turn(first, "mastered", monkeypatch, command_id="two", text="提示后的回答")
    later = second["learningRecords"]["observations"][-1]
    assert later["assistanceRefs"] == [help_item["assistanceId"]]
    assert later["independence"] == "assisted"
    assert second["learningRecords"]["observations"][0] == observation
    assert second["dialogue"]["stage"] == "discuss"


def test_student_and_next_tutor_message_can_belong_to_different_tasks(video, monkeypatch):
    begun = start(video)
    answered = turn(begun, "mastered", monkeypatch)
    student, tutor = answered["messages"][-2:]
    assert student["taskId"] == begun["currentTaskId"]
    assert tutor["taskId"] == answered["currentTaskId"] != student["taskId"]
    assert tutor["relatedTaskIds"] == [student["taskId"], tutor["taskId"]]
    assert answered["learningRecords"]["observations"][0]["taskId"] == student["taskId"]


@pytest.mark.parametrize("damage", ["student_quote", "teacher_as_student", "future_help", "independent", "question", "source"])
def test_invalid_or_retroactive_evidence_is_rejected(video, monkeypatch, damage):
    before = start(video)
    result = turn(before, "partial", monkeypatch)
    invalid = deepcopy(result)
    observation = invalid["learningRecords"]["observations"][0]
    if damage == "student_quote":
        observation["studentExcerpt"] = "学生未说过的话"
    elif damage == "teacher_as_student":
        observation["studentMessageIds"] = [result["messages"][-1]["messageId"]]
    elif damage == "future_help":
        observation["assistanceRefs"] = [result["learningRecords"]["assistance"][-1]["assistanceId"]]
    elif damage == "independent":
        observation["independence"] = "independent"
    elif damage == "question":
        invalid["learningRecords"]["tasks"][0]["question"] = "回答后改标准"
    else:
        observation["sourceRefs"] = [{"sourceId": "another-lesson", "quote": "外课内容"}]
    with pytest.raises(records.InvalidRecord):
        records.validate(invalid, before)


def test_legacy_records_gain_ids_without_inventing_message_or_help_links(video):
    old = deepcopy(video)
    old.update(phase="discussion", messages=[{"role": "student", "text": "是的", "phase": "recall"},
        {"role": "assistant", "text": "提供过某种帮助", "phase": "recall"},
        {"role": "student", "text": "是的", "phase": "recall"}])
    old["dialogue"]["points"][0]["assessment_history"] = [{"stage": "recall", "round": 1,
        "result": "mastered", "studentText": "是的", "evidence": "旧评估"}]
    restored = records.normalize(old)
    assert records.normalize(json.loads(json.dumps(restored))) == restored
    assert all(m["createdAt"] is None and m["taskId"] is None for m in restored["messages"])
    observation = restored["learningRecords"]["observations"][0]
    assert observation["recordOrigin"] == "legacy_unknown" and observation["studentMessageIds"] == []
    assert observation["independence"] == "unknown" and not restored["learningRecords"]["assistance"]


def test_other_sessions_and_new_content_generations_do_not_reuse_ids(video):
    old = start(video)
    other = start(dict(video, id="another-session"))
    replaced = start(dict(video, contentGeneration=1))
    assert len({s["currentTaskId"] for s in (old, other, replaced)}) == 3
    assert len({s["messages"][0]["messageId"] for s in (old, other, replaced)}) == 3
    with pytest.raises(records.InvalidRecord):
        records.normalize(dict(old, id="another-session"))


def test_content_fingerprints_sources_and_scope_are_checked(video):
    body = deepcopy(video["lessonContent"])
    body["topics"][0]["sourceRefs"][0]["quote"] = "不在原文的内容"
    body["topics"][0]["sourceRefs"][0]["quoteHash"] = lesson_content.digest("不在原文的内容")
    body["contentId"] = "content:" + lesson_content.digest({k: v for k, v in body.items() if k != "contentId"})
    with pytest.raises(ValueError):
        lesson_content.validate(body)
    with pytest.raises(ValueError):
        lesson_content.bind(dict(video, lessonId="different-lesson"))
    changed = deepcopy(video)
    changed["dialogue"]["points"][0]["content"] = "同编号替换了材料"
    with pytest.raises(ValueError):
        lesson_content.bind(changed)


def test_postclass_discussion_links_to_the_original_classroom_task(video, monkeypatch):
    discussed = turn(start(video), "mastered", monkeypatch)
    original_task = discussed["currentTaskId"]
    ended = records.transition(discussed, dict(discussed, **teaching.finish(discussed)), command_id="finish")
    continued = records.transition(ended, dict(ended, **teaching.start_postclass(ended)), command_id="continue")
    task = next(t for t in continued["learningRecords"]["tasks"] if t["taskId"] == continued["currentTaskId"])
    assert task["type"] == "postclass_discussion"
    assert task["resumesTaskId"] == original_task
    assert task["episodeId"] != discussed["messages"][-1]["episodeId"]


def test_truncated_source_capacity_is_explicit(video):
    text = "可读取文字" * 1200
    body = lesson_content.build("course", "lesson", "rev", "compiler", [], [
        {"id": "scene:long", "content": text, "source": "published-classroom-scene"}])
    assert {"code": "source_text_may_be_truncated", "sourceId": "scene:long"} in body["coverageGaps"]
