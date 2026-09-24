"""Tests for the outline agent (second graph: routing, tools, isolation).

Node-level tests stub the LLM service — no network, no Postgres. The full
pipeline (checkpoint persistence, cross-agent thread isolation) is
exercised by scripts/verify_outline_agent.py against the real stack.
"""

import asyncio

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.core.langgraph.graph import langgraph_agent
from app.core.langgraph.outline import OutlineAgent, outline_agent
from app.core.langgraph.tools.outline import outline_tools, suggest_weekly_plan
from app.schemas.graph import OutlineState


class _StubLLMService:
    """Minimal stand-in for LLMService covering what the graph nodes call."""

    def __init__(self, response: BaseMessage | None = None) -> None:
        self.response = response
        self.calls: list[list[dict]] = []
        self.bound_tools: list | None = None

    def get_llm(self) -> None:
        return None

    async def call(self, messages: list[dict]) -> BaseMessage:
        self.calls.append(messages)
        assert self.response is not None
        return self.response

    def bind_tools(self, tool_list: list) -> None:
        self.bound_tools = list(tool_list)


def _run(node, *args):
    return asyncio.run(node(*args))


# ----- Agent isolation (the point of the second agent) -----


def test_outline_agent_binds_private_tool_set(monkeypatch) -> None:
    stub = _StubLLMService()
    monkeypatch.setattr("app.core.langgraph.outline.LLMService", lambda *a, **k: stub)

    agent = OutlineAgent()

    assert stub.bound_tools == outline_tools
    assert agent.tools_by_name == {"suggest_weekly_plan": suggest_weekly_plan}


def test_tool_sets_do_not_cross_agents() -> None:
    """The chat agent's registry stays empty while outline has its own tools."""
    assert set(outline_agent.tools_by_name) == {"suggest_weekly_plan"}
    assert langgraph_agent.tools_by_name == {}  # chat singleton unpolluted


def test_outline_agent_gets_its_own_llm_service() -> None:
    """Two agents never share one LLMService instance (inventory gap #5)."""
    assert outline_agent.llm_service is not langgraph_agent.llm_service


# ----- Node routing (mirrors the chat agent tests) -----


def test_outline_routes_plain_reply_to_end() -> None:
    agent = OutlineAgent()
    agent.llm_service = _StubLLMService(AIMessage(content="大纲 v1"))

    result = _run(
        agent._outline,
        OutlineState(messages=[HumanMessage(content="帮我生成大纲")]),
        {"configurable": {"thread_id": "t1"}},
    )

    assert result.goto == "__end__"  # the END constant
    assert [m.content for m in result.update["messages"]] == ["大纲 v1"]


def test_outline_routes_tool_calls_to_tool_node() -> None:
    reply = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "suggest_weekly_plan",
                "args": {"total_hours": 64, "weeks": 16},
                "id": "call_1",
                "type": "tool_call",
            }
        ],
    )
    agent = OutlineAgent()
    agent.llm_service = _StubLLMService(reply)

    result = _run(
        agent._outline,
        OutlineState(messages=[HumanMessage(content="64 学时 16 周")]),
        {"configurable": {"thread_id": "t1"}},
    )

    assert result.goto == "tool_call"


def test_outline_prepends_rendered_system_prompt() -> None:
    agent = OutlineAgent()
    stub = _StubLLMService(AIMessage(content="ok"))
    agent.llm_service = stub

    _run(
        agent._outline,
        OutlineState(messages=[HumanMessage(content="生成《线性代数》大纲")]),
        {
            "configurable": {"thread_id": "t1"},
            "metadata": {
                "username": "王老师",
                "course_context": "课程：线性代数\n章节：行列式、矩阵、向量组",
            },
        },
    )

    sent = stub.calls[0]
    assert sent[0]["type"] == "system"
    assert "王老师" in sent[0]["content"]
    assert "行列式" in sent[0]["content"]
    assert "教学设计" in sent[0]["content"]  # outline persona, not the chat one
    assert sent[1]["content"] == "生成《线性代数》大纲"


# ----- Tool node (real execution — the tool is a pure function) -----


def test_tool_call_executes_weekly_plan_and_returns_to_outline() -> None:
    agent = OutlineAgent()
    state = OutlineState(
        messages=[
            HumanMessage(content="帮我排课时"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "suggest_weekly_plan",
                        "args": {"total_hours": 64, "weeks": 16},
                        "id": "call_1",
                        "type": "tool_call",
                    }
                ],
            ),
        ]
    )

    result = _run(agent._tool_call, state)

    assert result.goto == "outline"
    (tool_message,) = result.update["messages"]
    assert isinstance(tool_message, ToolMessage)
    assert tool_message.name == "suggest_weekly_plan"
    assert tool_message.tool_call_id == "call_1"
    assert "64" in tool_message.content  # real computation, not a stub


def test_tool_call_returns_error_text_for_bad_args() -> None:
    agent = OutlineAgent()
    state = OutlineState(
        messages=[
            HumanMessage(content="帮我排课时"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "suggest_weekly_plan",
                        "args": {"total_hours": 0, "weeks": 16},
                        "id": "call_1",
                        "type": "tool_call",
                    }
                ],
            ),
        ]
    )

    result = _run(agent._tool_call, state)

    (tool_message,) = result.update["messages"]
    assert "错误" in tool_message.content


# ----- Lifecycle -----


def test_close_releases_pool_and_forgets_graph() -> None:
    agent = OutlineAgent()

    class _FakePool:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    fake_pool = _FakePool()
    agent._connection_pool = fake_pool  # type: ignore[assignment]
    agent._graph = object()  # type: ignore[assignment]

    asyncio.run(agent.close())

    assert fake_pool.closed
    assert agent._connection_pool is None
    assert agent._graph is None
