"""Exercise final model requests through the real teaching agent, without a provider."""
import json

import pytest
from langchain_core.messages import HumanMessage

from backend.teaching import service, typed_teaching
from test_executor_adaptation import seed, scripted, assess


@pytest.mark.parametrize("action,text,packet,solicitation", [
    ("explain", "直接讲一下更新后的判断", assess(empty=True, intent="question",
        observation={"help_quote": "直接讲一下更新后的判断"}), "none"),
    ("respond", "暂停", assess(empty=True, intent="unclear",
        observation={"control": "pause", "control_quote": "暂停"}), "none"),
    ("concept_hint", "先初始化再判断", assess(), "one_task"),
])
def test_final_request_has_one_action_and_no_conflicting_human_override(monkeypatch, action, text, packet, solicitation):
    base = seed()
    client = scripted(monkeypatch, "请说明循环过程。", packet, "本轮回复。")
    base.update(service.start_discussion(base))
    base.update(service.classroom_turn(base, text))
    if action == "respond":
        assert len(client.seen) == 2  # Opening + assessment, no model confirmation.
        assert base["dialogue"]["teaching_plan"]["action"] == "respond"
        assert base["dialogue"]["teaching_plan"]["solicitation"] == "none"
        assert "未执行暂停" in base["messages"][-1]["text"]
        return
    system, human = client.seen[-1]
    context = json.loads(system.content.splitlines()[-1])
    assert context["teaching_plan"]["action"] == action
    assert context["teaching_plan"]["solicitation"] == solicitation
    instructions = system.content.split("程序提供的最新教学数据：")[0]
    assert instructions.count("本轮生成动作约束：") == 1
    assert typed_teaching.ACTION_PROMPTS[action] in instructions
    assert typed_teaching.SOLICITATION_PROMPTS[solicitation] in instructions
    assert "只输出给学生看的自然中文，不输出JSON" not in instructions  # core allows card JSON
    assert "学生只说不会、卡点尚不清楚时，问一个具体定位问题" not in instructions
    assert "补充该卡点后就请学生补充" not in instructions
    assert isinstance(human, HumanMessage)
    assert human.content == typed_teaching.GENERATION_INSTRUCTION
    assert "requirements" not in context["focus"] or context["focus"]["requirements"] == []
    assert client.settings[-1]["tool_choice"] == "none"


def test_failed_hint_explains_once_then_resume_locates_remaining_difficulty(monkeypatch):
    base = seed()
    client = scripted(monkeypatch, "请说明过程。", assess(), "先看更新完成后会检查什么。",
                      assess(empty=True, intent="question", observation={"help_quote": "还是不会"}), "更新后重新判断条件。",
                      "更新后会重新判断条件。")
    base.update(service.start_discussion(base))
    base.update(service.classroom_turn(base, "先初始化再判断"))
    base.update(service.classroom_turn(base, "还是不会"))
    restored = json.loads(json.dumps(base["dialogue"], ensure_ascii=False))
    typed_teaching.run(restored, opening=True, after_class=True)
    for messages, action in zip(client.seen[-2:], ["concept_explain", "clarify"]):
        system, human = messages
        context = json.loads(system.content.splitlines()[-1])
        assert context["teaching_plan"]["action"] == action
        instructions = system.content.split("程序提供的最新教学数据：")[0]
        assert typed_teaching.ACTION_PROMPTS[action] in instructions
        assert typed_teaching.SOLICITATION_PROMPTS["none" if action == "concept_explain" else "one_task"] in instructions
        assert "再提出focus的新任务" not in human.content
    assert "不重考" in client.seen[-1][-1].content
    assert client.seen[-1][-1].content.endswith(typed_teaching.GENERATION_INSTRUCTION)


def test_core_opening_keeps_card_protocol_without_legacy_json_rules(monkeypatch):
    base = seed()
    client = scripted(monkeypatch, "请说明循环过程。")
    service.start_discussion(base)
    system, human = client.seen[0]
    assert '"question_card":true' in system.content
    assert "action=ask" in system.content
    assert "当前类型策略" not in system.content
    assert "只输出给学生看的自然中文，不输出JSON" not in system.content
    assert "不在开场提交学生评估" in human.content
    assert human.content.count(typed_teaching.GENERATION_INSTRUCTION) == 1
    assert "把核心答案留给学生" in human.content


@pytest.mark.parametrize("legacy", [False, True])
def test_card_repair_keeps_source_and_protocol_without_tutoring_instructions(legacy):
    from backend.teaching import question_cards
    point = {"id": "p", "explanation": "条件为假时执行else分支。", "requirements": []}
    item = {"prompt": "条件为假时执行什么？", "options": ["else分支", "if分支"],
            "answer": 0, "explanation": "条件为假时执行else分支。"}
    if legacy:
        point = {"id": "p", "type": "memory", "content": point["explanation"],
                 "requirements": [{"id": "r", "text": "假时执行else", "status": "unconfirmed"}]}
        item["target_ids"] = ["r"]
    calls = []

    def complete(system, user):
        calls.append((system, user))
        payload = dict(item)
        if len(calls) == 1:
            payload["options"] = ["重复", "重复"]
        return json.dumps({"questions": [payload]}, ensure_ascii=False)

    group = question_cards.generate(point, complete)
    assert len(calls) == 2
    assert calls[0][0] == calls[1][0]
    assert calls[1][1].startswith(calls[0][1] + "\n")
    assert "选项须为二至四个不同的非空文本" in calls[1][1]
    assert "同一输入返回完整题组JSON" in calls[1][1]
    assert "本轮生成动作约束" not in calls[1][0]
    assert group["questions"][0]["target_ids"] == (["r"] if legacy else [])
