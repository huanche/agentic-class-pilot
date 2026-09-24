"""Tests for the LangGraph state schema: defaults and the add_messages reducer."""

from langchain_core.messages import HumanMessage
from langgraph.graph.message import add_messages

from app.schemas.graph import GraphState


def test_graph_state_defaults() -> None:
    state = GraphState()
    assert state.messages == []
    assert state.long_term_memory == ""


def test_add_messages_appends_instead_of_replacing() -> None:
    # The reducer wired into GraphState.messages: new messages must merge on
    # top of existing history, not replace it — that is what makes multi-turn
    # conversation accumulate across nodes.
    merged = add_messages(
        [HumanMessage(content="第一轮")],
        [{"role": "user", "content": "第二轮"}],
    )
    assert len(merged) == 2
    assert merged[0].content == "第一轮"
    assert merged[1].content == "第二轮"


def test_add_messages_merges_by_id() -> None:
    # Same id = edit of an existing entry, not a duplicate append.
    first = HumanMessage(content="原文", id="m1")
    edited = HumanMessage(content="改后", id="m1")
    merged = add_messages([first], [edited])
    assert len(merged) == 1
    assert merged[0].content == "改后"
