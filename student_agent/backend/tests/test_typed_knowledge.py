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
    monkeypatch.setattr(model, "extraction_model", lambda **kwargs: client)
    return client


CORE = {"name": "循环执行过程", "explanation": "先初始化，满足条件时执行循环体，再更新并重新判断。"}


def extract(*args, **kwargs):
    return knowledge.learning_points(*args, course_name="程序设计基础", **kwargs)


def test_core_content_and_course_name_reach_the_real_agent(monkeypatch):
    import json
    client = run(monkeypatch, submission(CORE))
    result = extract(MATERIALS)
    point = result.points[0]
    assert point["name"] == point["title"] == CORE["name"]
    assert point["explanation"] == point["content"] == point["description"] == CORE["explanation"]
    assert "type" not in point and "details" not in point
    assert json.loads(client.seen[0][1].content)["course_name"] == "程序设计基础"
    assert result.model_calls == 1 and not result.repair_attempted
    assert client.settings[0]["timeout"] <= 120


@pytest.mark.parametrize("points", [[], [CORE] * 4, [MEMORY],
    [{**CORE, "type": "concept"}], [{**CORE, "name": " "}],
    [{**CORE, "explanation": ""}], [{**CORE, "explanation": 1}],
    [{**CORE, "masteryPoints": ["额外字段"]}]])
def test_invalid_submission_repairs_in_same_agent(monkeypatch, points):
    client = run(monkeypatch, submission(*points), submission(CORE))
    result = extract(MATERIALS)
    assert result.model_calls == 2 and result.repair_attempted
    assert any(isinstance(m, ToolMessage) and "结构校验失败" in m.content for m in client.seen[1])
    assert client.seen[0][1] in client.seen[1]


def test_budget_exhaustion_is_not_partial_success(monkeypatch):
    client = run(monkeypatch, submission())
    with pytest.raises(knowledge.KnowledgePreparationError) as error:
        extract(MATERIALS)
    assert error.value.code == "format" and error.value.model_calls == 3
    assert len(client.seen) == 3 and error.value.issues


@pytest.mark.parametrize("message", [AIMessage(content="完成"),
    AIMessage(content="", tool_calls=[{"name": "wrong", "args": {}, "id": "bad"}]),
    AIMessage(content="", invalid_tool_calls=[{"name": "submit_knowledge_points", "args": "{bad", "id": "bad"}]),
    AIMessage(content="", tool_calls=[{"name": "submit_knowledge_points", "args": {"points": [CORE]}, "id": "a"},
                                      {"name": "submit_knowledge_points", "args": {"points": [CORE]}, "id": "b"}])])
def test_missing_or_invalid_tool_call_repairs(monkeypatch, message):
    run(monkeypatch, message, submission(CORE))
    assert extract(MATERIALS).model_calls == 2


def test_no_input_or_missing_course_name_never_calls_provider(monkeypatch):
    monkeypatch.setattr(model, "extraction_model", lambda **kw: pytest.fail("must not call model"))
    with pytest.raises(knowledge.KnowledgePreparationError) as error:
        extract([])
    assert error.value.code == "no_content"
    with pytest.raises(knowledge.KnowledgePreparationError) as error:
        knowledge.learning_points(MATERIALS)
    assert error.value.stage == "course_name"


def test_transport_error_is_not_retried(monkeypatch):
    client = run(monkeypatch, TimeoutError("provider timeout"))
    with pytest.raises(knowledge.KnowledgePreparationError) as error:
        extract(MATERIALS)
    assert error.value.code == "timeout" and len(client.seen) == 1


def test_total_deadline_stops_repair(monkeypatch):
    run(monkeypatch, AIMessage(content="未提交"))
    times = iter([0, 0, 179, 181])
    monkeypatch.setattr(knowledge, "monotonic", lambda: next(times))
    with pytest.raises(knowledge.KnowledgePreparationError) as error:
        extract(MATERIALS)
    assert error.value.code == "timeout"


def test_exact_deduplication_and_scope_owned_identity(monkeypatch):
    run(monkeypatch, submission(CORE, {**CORE, "name": "  " + CORE["name"]}))
    first = extract(MATERIALS, "course", "one")
    second = extract(MATERIALS, "course", "two")
    assert len(first.points) == 1 and first.duplicate_count == 1
    assert first.points[0]["id"] != second.points[0]["id"]


def test_invalid_binding(monkeypatch):
    with pytest.raises(knowledge.KnowledgePreparationError) as error:
        extract(MATERIALS, "course", "")
    assert error.value.stage == "binding"


def test_provider_specific_settings(monkeypatch):
    monkeypatch.setenv("STUDENT_AGENT_API_KEY", "mock-only")
    monkeypatch.setenv("STUDENT_AGENT_BASE_URL", "https://api.deepseek.com/v1")
    assert model.extraction_model().max_retries == 0
    assert model.extraction_model().extra_body["thinking"] == {"type": "disabled"}
    assert not model._model().extra_body
    monkeypatch.setenv("STUDENT_AGENT_BASE_URL", "https://custom.example.test/v1")
    assert not model.extraction_model().extra_body
