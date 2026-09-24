"""Tool registry for the LangGraph agent.

The registry *is* the integration mechanism: the graph binds whatever is in
``tools`` at agent construction and dispatches calls by name, so adding a
tool means appending it here — no graph code changes.

The vendor template's two demo tools (DuckDuckGo web search, ``ask_human``
HITL) were deliberately not ported: public web search is not a teaching
scenario, and ``ask_human`` waits until we have a real irreversible action
to confirm. Teaching-scenario tools (e.g. "search this course's outline",
"fetch this chapter's courseware text") drop in here later. See
docs/langgraph-migration-plan.md §2.1.
"""

from langchain_core.tools.base import BaseTool

# Empty on purpose: the agent runs tool-free until the first real tool lands.
tools: list[BaseTool] = []
