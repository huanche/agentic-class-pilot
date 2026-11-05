"""Exercise real create_agent tool validation/repair without contacting a provider."""
from copy import deepcopy
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field, ValidationError

from backend.content import knowledge
from backend.content.knowledge_schema import submit_knowledge_points
from backend.infrastructure import model

MATERIALS = [{"id": "scene:one", "source": "published-classroom-scene",
              "title": "循环", "content": "讲解初始化、条件判断、更新，以及用循环进行累加。"}]
MEMORY = {"title": "for 语法", "type": "memory", "details": {
    "statement": "for 包含初始化、条件判断和更新。", "requiredElements": ["初始化", "条件判断", "更新"]}}
CONCEPT = {"title": "理解循环的执行过程", "type": "concept", "details": {
    "explanation": "先初始化，满足条件时执行循环体，再更新并重新判断。", "understandingPoints": ["初始化只执行一次"]}}
DESIGN = {"title": "编写累加循环", "type": "design", "details": {
    "capability": "根据给定范围独立编写累加程序。", "constraints": [], "successCriteria": ["边界与累加逻辑正确"]}}


def submission(*points):
    return AIMessage(content="", tool_calls=[{"name": "submit_knowledge_points", "id": "submit",
                                              "args": {"points": deepcopy(list(points))}}])


class ScriptedModel(BaseChatModel):
    responses: list[Any]
    seen: list[Any] = Field(default_factory=list)
    settings: list[dict] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "scripted-tool-model"

    def bind_tools(self, tools, **kwargs):
        assert tools, "The real agent must bind its schema as a tool"
        return self.bind(**kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        self.settings.append(kwargs)
        response = self.responses[min(len(self.seen) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return ChatResult(generations=[ChatGeneration(message=response.model_copy(deep=True))])


def run(monkeypatch, *responses):
    client = ScriptedModel(responses=list(responses))
    monkeypatch.setattr(model, "extraction_model", lambda: client)
    return client


def test_three_types_are_preserved_and_paraphrases_need_no_quotes(monkeypatch):
    client = run(monkeypatch, submission(MEMORY, CONCEPT, DESIGN))
    result = knowledge.learning_points(MATERIALS)
    assert [p["type"] for p in result.points] == ["memory", "concept", "design"]
    assert [p["details"] for p in result.points] == [p["details"] for p in (MEMORY, CONCEPT, DESIGN)]
    assert len(client.seen) == result.model_calls == 1
    assert not result.repair_attempted
    assert all("sourceRefs" not in p and p["content"] for p in result.points)
    assert client.settings[0]["timeout"] <= 45


@pytest.mark.parametrize("broken", [
    {"title": "x", "type": "other", "details": {}},
    {"title": "x", "type": "design", "details": {"capability": "编程", "constraints": []}},
    {"title": "x", "type": "memory", "details": DESIGN["details"]},
    {**MEMORY, "title": "   "},
    {**MEMORY, "details": {"statement": "定义", "requiredElements": []}},
    {**MEMORY, "details": {"statement": 123, "requiredElements": ["要点"]}},
    {**MEMORY, "lessonId": "model-cannot-change-the-lesson"},
    {**MEMORY, "sourceRefs": [{"sourceId": "unknown"}]},
])
def test_invalid_first_submission_gets_tool_feedback_and_repairs_in_same_agent(monkeypatch, broken):
    client = run(monkeypatch, submission(broken), submission(MEMORY))
    result = knowledge.learning_points(MATERIALS)
    assert result.model_calls == 2 and result.repair_attempted
    assert result.points[0]["type"] == "memory"
    feedback = [m for m in client.seen[1] if isinstance(m, ToolMessage)]
    assert feedback and "结构校验失败" in feedback[-1].content
    assert "materials" in client.seen[1][1].content
    assert any(isinstance(m, AIMessage) and m.tool_calls for m in client.seen[1])


def test_structural_errors_exhaust_shared_budget_without_partial_result(monkeypatch):
    invalid = {**DESIGN, "details": {**DESIGN["details"], "successCriteria": []}}
    client = run(monkeypatch, submission(MEMORY, invalid))
    with pytest.raises(knowledge.KnowledgePreparationError) as caught:
        knowledge.learning_points(MATERIALS)
    assert caught.value.code == "format" and caught.value.model_calls == 3
    assert len(client.seen) == 3
    assert caught.value.accepted_count == 0 and caught.value.draft
    assert caught.value.issues
    assert any("successCriteria" in issue.reason for issue in caught.value.issues)


def test_plain_text_is_feedback_not_success(monkeypatch):
    client = run(monkeypatch, AIMessage(content="整理完成"), submission(CONCEPT))
    result = knowledge.learning_points(MATERIALS)
    assert result.model_calls == 2
    assert "尚未收到有效的工具提交" in client.seen[1][-1].content


def test_only_plain_text_stops_at_three_calls(monkeypatch):
    client = run(monkeypatch, AIMessage(content="完成"))
    with pytest.raises(knowledge.KnowledgePreparationError, match="结构"):
        knowledge.learning_points(MATERIALS)
    assert len(client.seen) == 3


@pytest.mark.parametrize("bad_message", [
    AIMessage(content="", tool_calls=[{"name": "wrong_tool", "args": {}, "id": "wrong"}]),
    AIMessage(content="", invalid_tool_calls=[{"name": "submit_knowledge_points", "args": "{bad-json", "id": "bad"}]),
    AIMessage(content="", tool_calls=[{"name": "submit_knowledge_points", "id": "first", "args": {"points": [MEMORY]}},
                                      {"name": "submit_knowledge_points", "id": "second", "args": {"points": [CONCEPT]}}]),
])
def test_bad_tool_calls_receive_feedback_before_resubmitting(monkeypatch, bad_message):
    client = run(monkeypatch, bad_message, submission(MEMORY))
    assert knowledge.learning_points(MATERIALS).model_calls == 2
    assert any(isinstance(m, ToolMessage) for m in client.seen[1])


def test_empty_submission_is_no_content_not_format_retry(monkeypatch):
    client = run(monkeypatch, submission())
    with pytest.raises(knowledge.KnowledgePreparationError) as caught:
        knowledge.learning_points(MATERIALS)
    assert caught.value.code == "no_content" and len(client.seen) == 1


def test_no_input_does_not_call_model(monkeypatch):
    monkeypatch.setattr(model, "extraction_model", lambda: pytest.fail("no content"))
    with pytest.raises(knowledge.KnowledgePreparationError) as caught:
        knowledge.learning_points([])
    assert caught.value.code == "no_content"


def test_transport_error_is_not_retried_as_a_structural_error(monkeypatch):
    client = run(monkeypatch, TimeoutError("provider timeout"))
    with pytest.raises(knowledge.KnowledgePreparationError) as caught:
        knowledge.learning_points(MATERIALS)
    assert caught.value.code == "timeout" and len(client.seen) == 1


def test_total_deadline_stops_repair(monkeypatch):
    client = run(monkeypatch, AIMessage(content="还未提交"))
    times = iter([0, 0, 89, 91])
    monkeypatch.setattr(knowledge, "monotonic", lambda: next(times))
    with pytest.raises(knowledge.KnowledgePreparationError) as caught:
        knowledge.learning_points(MATERIALS)
    assert caught.value.code == "timeout" and len(client.seen) == 1


def test_deduplication_is_exact_preserves_type_details_order_and_code(monkeypatch):
    another_type = {**CONCEPT, "title": MEMORY["title"]}
    changed = {**MEMORY, "details": {**MEMORY["details"], "requiredElements": ["不同要点"]}}
    whitespace = {**MEMORY, "title": "  " + MEMORY["title"] + "  "}
    client = run(monkeypatch, submission(MEMORY, whitespace, another_type, changed))
    result = knowledge.learning_points(MATERIALS)
    assert len(result.points) == 3 and result.duplicate_count == 1
    assert len(client.seen) == 1
    assert len({p["id"] for p in result.points}) == 3
    code1 = {**DESIGN, "details": {**DESIGN["details"], "capability": '输出字符串 "a b"'}}
    code2 = {**DESIGN, "details": {**DESIGN["details"], "capability": '输出字符串 "ab"'}}
    assert len(knowledge.compile_points(submit_knowledge_points(points=[code1, code2]))) == 2


def test_schema_forbids_type_specific_field_mismatch():
    with pytest.raises(ValidationError):
        submit_knowledge_points.model_validate({"points": [{**MEMORY, "details": DESIGN["details"]}]})


def test_same_content_in_different_lessons_has_distinct_program_owned_ids(monkeypatch):
    run(monkeypatch, submission(MEMORY))
    first = knowledge.learning_points(MATERIALS, "course", "lesson-1")
    second = knowledge.learning_points(MATERIALS, "course", "lesson-2")
    assert first.points[0]["id"] != second.points[0]["id"]
    assert first.points[0]["details"] == second.points[0]["details"]


def test_incomplete_scope_is_a_program_error_without_model_retry(monkeypatch):
    monkeypatch.setattr(model, "extraction_model", lambda: pytest.fail("invalid program binding"))
    with pytest.raises(knowledge.KnowledgePreparationError) as caught:
        knowledge.learning_points(MATERIALS, "course", "")
    assert caught.value.stage == "binding" and caught.value.model_calls == 0


def test_real_chatopenai_serialization_and_repair_over_mock_http(monkeypatch):
    import httpx
    import json
    from langchain_openai import ChatOpenAI
    requests = []
    def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        candidate = MEMORY if len(requests) > 1 else {**DESIGN, "details": {}}
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 0,
            "model": "test-model", "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{"id": f"call_{len(requests)}",
                "type": "function", "function": {"name": "submit_knowledge_points",
                "arguments": json.dumps({"points": [candidate]}, ensure_ascii=False)}}]}}]})
    with httpx.Client(transport=httpx.MockTransport(handle)) as http_client:
        client = ChatOpenAI(api_key="mock-only", base_url="https://model.example.test/v1",
                            model="test-model", max_retries=0, http_client=http_client)
        monkeypatch.setattr(model, "extraction_model", lambda: client)
        result = knowledge.learning_points(MATERIALS)
    assert result.model_calls == len(requests) == 2
    assert result.points[0]["type"] == "memory"
    assert requests[0]["tools"][0]["function"]["name"] == "submit_knowledge_points"
    assert requests[0]["parallel_tool_calls"] is False
    feedback = [m for m in requests[1]["messages"] if m["role"] == "tool"]
    assert feedback and "结构校验失败" in feedback[0]["content"]


def test_extraction_adapter_disables_sdk_retries(monkeypatch):
    monkeypatch.setenv("STUDENT_AGENT_API_KEY", "mock-only")
    assert model.extraction_model().max_retries == 0


def test_official_deepseek_extraction_disables_thinking_for_forced_tool_selection(monkeypatch):
    monkeypatch.setenv("STUDENT_AGENT_API_KEY", "mock-only")
    monkeypatch.setenv("STUDENT_AGENT_BASE_URL", "https://api.deepseek.com/v1")
    assert model.extraction_model().extra_body["thinking"] == {"type": "disabled"}
    # Ordinary teaching calls retain the existing configuration.
    assert not model._model().extra_body


def test_other_providers_do_not_receive_deepseek_specific_parameters(monkeypatch):
    monkeypatch.setenv("STUDENT_AGENT_API_KEY", "mock-only")
    monkeypatch.setenv("STUDENT_AGENT_BASE_URL", "https://custom.example.test/v1")
    assert not model.extraction_model().extra_body
