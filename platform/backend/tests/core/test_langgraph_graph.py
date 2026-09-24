"""Tests for the LangGraph agent graph (routing, tool node, lifecycle).

Node-level tests stub the LLM service — no network, no Postgres. The full
pipeline (checkpointer, multi-turn accumulation) is exercised by
scripts/verify_langgraph_agent.py against the real stack (migration plan,
appendix E).
"""

import asyncio

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from app.core.config import settings
from app.core.langgraph.checkpoint import checkpointer_conninfo
from app.core.langgraph.graph import LangGraphAgent
from app.core.langgraph.tools import tools
from app.schemas.chat import Message
from app.schemas.graph import GraphState


@tool
async def echo(text: str) -> str:
    """Echo the input text back unchanged."""
    return text


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


def test_tools_registry_starts_empty() -> None:
    assert tools == []
    agent = LangGraphAgent()
    assert agent.tools_by_name == {}


def test_agent_init_skips_bind_tools_with_empty_registry(monkeypatch) -> None:
    stub = _StubLLMService()
    monkeypatch.setattr("app.core.langgraph.graph.LLMService", lambda *a, **k: stub)

    agent = LangGraphAgent()

    assert stub.bound_tools is None  # bind_tools never called
    assert agent.tools_by_name == {}
    assert agent.memory_service is None


def test_agent_init_binds_registered_tools(monkeypatch) -> None:
    stub = _StubLLMService()
    monkeypatch.setattr("app.core.langgraph.graph.LLMService", lambda *a, **k: stub)
    monkeypatch.setattr("app.core.langgraph.graph.tools", [echo])

    agent = LangGraphAgent()

    assert stub.bound_tools == [echo]
    assert agent.tools_by_name == {"echo": echo}


def test_chat_routes_plain_reply_to_end() -> None:
    agent = LangGraphAgent()
    agent.llm_service = _StubLLMService(AIMessage(content="你好"))

    result = _run(
        agent._chat,
        GraphState(messages=[Message(role="user", content="hi")]),
        {"configurable": {"thread_id": "t1"}},
    )

    assert result.goto == "__end__"  # the END constant
    assert [m.content for m in result.update["messages"]] == ["你好"]


def test_chat_routes_tool_calls_to_tool_node() -> None:
    reply = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "echo",
                "args": {"text": "ping"},
                "id": "call_1",
                "type": "tool_call",
            }
        ],
    )
    agent = LangGraphAgent()
    agent.llm_service = _StubLLMService(reply)

    result = _run(
        agent._chat,
        GraphState(messages=[Message(role="user", content="hi")]),
        {"configurable": {"thread_id": "t1"}},
    )

    assert result.goto == "tool_call"


def test_chat_prepends_rendered_system_prompt() -> None:
    agent = LangGraphAgent()
    stub = _StubLLMService(AIMessage(content="ok"))
    agent.llm_service = stub

    _run(
        agent._chat,
        GraphState(messages=[Message(role="user", content="什么是牛顿第二定律？")]),
        {
            "configurable": {"thread_id": "t1"},
            "metadata": {"username": "小明", "chapter_context": "第三章：牛顿运动定律"},
        },
    )

    sent = stub.calls[0]
    # system prompt is a SystemMessage, dumping in langchain's {"type": ...}
    # shape (accepted by the LLM client like the history entries)
    assert sent[0]["type"] == "system"
    assert "小明" in sent[0]["content"]
    assert "第三章：牛顿运动定律" in sent[0]["content"]
    # history follows the system prompt; trimmed history dumps in langchain's
    # {"type": "human", ...} shape (both shapes accepted by the LLM client)
    assert len(sent) == 2
    assert sent[1]["content"] == "什么是牛顿第二定律？"
    assert sent[1].get("role", sent[1].get("type")) in ("user", "human")


def test_tool_call_executes_single_tool_and_returns_to_chat() -> None:
    agent = LangGraphAgent()
    agent.tools_by_name = {"echo": echo}
    state = GraphState(
        messages=[
            HumanMessage(content="hi"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "echo",
                        "args": {"text": "ping"},
                        "id": "call_1",
                        "type": "tool_call",
                    }
                ],
            ),
        ]
    )

    result = _run(agent._tool_call, state)

    assert result.goto == "chat"
    (tool_message,) = result.update["messages"]
    assert isinstance(tool_message, ToolMessage)
    assert tool_message.content == "ping"
    assert tool_message.name == "echo"
    assert tool_message.tool_call_id == "call_1"


def test_tool_call_runs_multiple_tools() -> None:
    agent = LangGraphAgent()
    agent.tools_by_name = {"echo": echo}
    state = GraphState(
        messages=[
            HumanMessage(content="hi"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "echo",
                        "args": {"text": "一"},
                        "id": "call_1",
                        "type": "tool_call",
                    },
                    {
                        "name": "echo",
                        "args": {"text": "二"},
                        "id": "call_2",
                        "type": "tool_call",
                    },
                ],
            ),
        ]
    )

    result = _run(agent._tool_call, state)

    assert result.goto == "chat"
    assert [m.tool_call_id for m in result.update["messages"]] == ["call_1", "call_2"]
    assert [m.content for m in result.update["messages"]] == ["一", "二"]


def test_close_releases_pool_and_forgets_graph() -> None:
    agent = LangGraphAgent()

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


def test_checkpointer_conninfo_strips_sqlalchemy_suffix() -> None:
    conninfo = checkpointer_conninfo()
    assert conninfo.startswith("postgresql://")
    assert "+psycopg" not in conninfo
    # same target db as the app DSN (test DB in the test environment)
    assert conninfo.rsplit("/", 1)[-1] == str(settings.DATABASE_URL).rsplit("/", 1)[-1]


def test_checkpoint_settings_defaults() -> None:
    assert settings.CHECKPOINT_TABLES == [
        "checkpoint_blobs",
        "checkpoint_writes",
        "checkpoints",
    ]
    assert settings.CHECKPOINT_POOL_SIZE == 20
