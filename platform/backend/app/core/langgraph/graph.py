"""LangGraph agent: workflow construction, LLM interaction, and checkpointing.

Ported from the vendor template ``app/core/langgraph/graph.py`` with the
adaptations from docs/langgraph-migration-plan.md §2.2:

- DB settings come from our ``DATABASE_URL`` (``+psycopg`` SQLAlchemy driver
  suffix stripped for the bare libpq URL the checkpointer pool needs); the
  pool stays independent of the sync SQLModel engine, as upstream;
- cross-cutting references are cut until their migration step lands: metrics
  timing is a ``nullcontext`` (step 5), langfuse callbacks an empty list
  (step 6), and the memory service is optional constructor injection
  defaulting to ``None`` (step 4);
- ``bind_tools`` is skipped while the tool registry is empty — binding
  ``[]`` would wrap the runnable for nothing and forward ``tools=[]`` to
  the API on every call;
- ``chapter_context`` rides the config metadata like ``username``, so the
  step-3 chapter Q&A route can feed courseware text into the system prompt
  through the same injection pipeline;
- the pool is assigned only after a successful ``open()`` (upstream assigns
  before opening, leaving a half-initialised pool behind on failure);
- ``close()`` releases the pool and forgets the compiled graph so repeated
  lifespans (one TestClient per test module) rebuild cleanly instead of
  reusing a pool whose connections belong to a closed event loop.

Platform note: psycopg's async mode refuses Windows' ProactorEventLoop, so a
natively-run ``uvicorn app.main:app`` on Windows fails the fail-fast graph
prewarm unless it runs with ``--reload``/workers (uvicorn then uses a
SelectorEventLoop). The supported dev/prod paths run the backend under
Docker (Linux); the test suite sets the selector policy in conftest.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import nullcontext
from typing import (
    Any,
    Protocol,
    cast,
)

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    convert_to_openai_messages,
)
from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import (
    END,
    StateGraph,
)
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import (
    Command,
    RetryPolicy,
    StateSnapshot,
)

from app.core.config import settings
from app.core.langgraph.checkpoint import (
    PostgresConnPool,
    clear_thread_rows,
    create_checkpoint_pool,
    thread_row_count,
)
from app.core.langgraph.tools import tools
from app.core.langgraph.utils import (
    dump_messages,
    execute_tool_calls,
    extract_text_content,
    prepare_messages,
    process_llm_response,
    to_history_messages,
)
from app.core.logging import logger
from app.core.prompts import load_system_prompt
from app.schemas.chat import HistoryMessage, Message
from app.schemas.graph import GraphState
from app.services.llm import LLMService


def _has_pending_interrupt(state: StateSnapshot) -> bool:
    """True only when the graph is genuinely paused on a human interrupt.

    ``state.next`` is also non-empty when a node errored mid-superstep and
    left a pending task — treating that as an interrupt sent every follow-up
    down the ``Command(resume=...)`` path (inventory gap #3). A thread
    poisoned that way self-heals: without real interrupts we fall through to
    normal input, the pending task re-runs and completes.
    """
    return bool(state.next) and any(
        getattr(task, "interrupts", None) for task in state.tasks
    )


class MemoryServiceProtocol(Protocol):
    """Structural interface the step-4 memory service will satisfy.

    Declared here (not imported) because ``app/services/memory.py`` does not
    exist yet; when it lands, its class matches this shape structurally and
    can be injected without touching this file again.
    """

    async def search(self, user_id: str | None, query: str) -> str: ...

    async def add(
        self,
        user_id: str | None,
        messages: list[dict[str, Any]],
        metadata: dict[str, Any] | None,
    ) -> None: ...


class LangGraphAgent:
    """Manages the LangGraph Agent/workflow and interactions with the LLM.

    This class handles the creation and management of the LangGraph workflow,
    including LLM interactions, database connections, and response processing.
    """

    def __init__(
        self,
        memory_service: MemoryServiceProtocol | None = None,
        llm_service: LLMService | None = None,
    ):
        """Initialize the LangGraph Agent with necessary components.

        Args:
            memory_service: Optional long-term-memory service (migration step
                4). ``None`` disables memory search/write instead of failing.
            llm_service: LLM service instance this agent binds its tools to.
                ``None`` creates a fresh one — every agent owns its service
                instance so tool bindings and the model-fallback cursor never
                cross agents (inventory gap #5; ``ask.py`` keeps the module
                singleton).
        """
        # Use the agent's own LLM service instance with tools bound
        self.llm_service = llm_service or LLMService()
        if tools:
            self.llm_service.bind_tools(tools)
        self.tools_by_name = {tool.name: tool for tool in tools}
        self.memory_service = memory_service
        self._connection_pool: PostgresConnPool | None = None
        self._graph: CompiledStateGraph[Any, Any, Any, Any] | None = None
        logger.info(
            "langgraph_agent_initialized",
            model=settings.DEFAULT_LLM_MODEL,
            environment=settings.ENVIRONMENT.value,
        )

    async def _get_connection_pool(self) -> PostgresConnPool:
        """Get this agent's checkpoint pool, creating it on first use.

        Returns:
            AsyncConnectionPool: The open connection pool.

        Raises:
            Exception: If the pool cannot be created, in every environment.
        """
        if self._connection_pool is None:
            self._connection_pool = await create_checkpoint_pool()
        return self._connection_pool

    async def _chat(self, state: GraphState, config: RunnableConfig) -> Command[Any]:
        """Process the chat state and generate a response.

        Args:
            state (GraphState): The current state of the conversation.
            config (RunnableConfig): The runnable configuration for this invocation.

        Returns:
            Command: Command object with updated state and next node to execute.
        """
        # Get the current LLM instance for metrics
        current_llm = self.llm_service.get_llm()
        model_name = (
            current_llm.model_name
            if current_llm and hasattr(current_llm, "model_name")
            else settings.DEFAULT_LLM_MODEL
        )

        username = config.get("metadata", {}).get("username")
        chapter_context = config.get("metadata", {}).get("chapter_context", "")
        thread_id = config.get("configurable", {}).get("thread_id")
        SYSTEM_PROMPT = load_system_prompt(
            username=username,
            long_term_memory=state.long_term_memory,
            chapter_context=chapter_context,
        )

        # Prepare messages with system prompt
        messages = prepare_messages(state.messages, SYSTEM_PROMPT)

        try:
            # Use LLM service with automatic retries and circular fallback
            # (migration step 5 swaps this no-op for the latency histogram)
            with nullcontext():
                response_message = await self.llm_service.call(dump_messages(messages))

            # Process response to handle structured content blocks
            response_message = process_llm_response(response_message)

            logger.info(
                "llm_response_generated",
                session_id=thread_id,
                model=model_name,
                environment=settings.ENVIRONMENT.value,
            )

            # Determine next node based on whether there are tool calls
            if isinstance(response_message, AIMessage) and response_message.tool_calls:
                goto = "tool_call"
            else:
                goto = END

            return Command(update={"messages": [response_message]}, goto=goto)
        except Exception as e:
            logger.error(
                "llm_call_failed_all_models",
                session_id=thread_id,
                error=str(e),
                environment=settings.ENVIRONMENT.value,
            )
            raise Exception(
                f"failed to get llm response after trying all models: {str(e)}"
            ) from e

    # Define our tool node
    async def _tool_call(self, state: GraphState) -> Command[Any]:
        """Process tool calls from the last message.

        Args:
            state: The current agent state containing messages and tool calls.

        Returns:
            Command: Command with updated messages and routing back to chat.
        """
        tool_calls = state.messages[-1].tool_calls
        outputs = await execute_tool_calls(tool_calls, self.tools_by_name)
        return Command(update={"messages": outputs}, goto="chat")

    async def create_graph(self) -> CompiledStateGraph[Any, Any, Any, Any]:
        """Create and configure the LangGraph workflow.

        Returns:
            CompiledStateGraph: The configured LangGraph instance, always with a checkpointer.

        Raises:
            Exception: If the graph cannot be built, in every environment.
        """
        if self._graph is None:
            try:
                graph_builder = StateGraph(GraphState)
                graph_builder.add_node(
                    "chat", self._chat, destinations=("tool_call", END)
                )
                graph_builder.add_node(
                    "tool_call",
                    self._tool_call,
                    destinations=("chat",),
                    retry_policy=RetryPolicy(max_attempts=3),
                )
                graph_builder.set_entry_point("chat")
                graph_builder.set_finish_point("chat")

                # Raises if the pool cannot be created — no checkpointer, no service.
                connection_pool = await self._get_connection_pool()
                checkpointer = AsyncPostgresSaver(connection_pool)
                await checkpointer.setup()

                self._graph = graph_builder.compile(
                    checkpointer=checkpointer,
                    name=f"{settings.PROJECT_NAME} Agent ({settings.ENVIRONMENT.value})",
                )

                logger.info(
                    "graph_created",
                    graph_name=f"{settings.PROJECT_NAME} Agent",
                    environment=settings.ENVIRONMENT.value,
                    has_checkpointer=checkpointer is not None,
                )
            except Exception as e:
                logger.exception(
                    "graph_creation_failed",
                    error=str(e),
                    environment=settings.ENVIRONMENT.value,
                )
                raise e

        return self._graph

    async def _get_graph(self) -> CompiledStateGraph[Any, Any, Any, Any]:
        """Return the compiled graph, creating it on first access.

        Raises:
            Exception: Propagated from ``create_graph()`` when initialisation
                fails. Callers can rely on the return being non-``None``.
        """
        if self._graph is None:
            self._graph = await self.create_graph()
        return self._graph

    async def get_response(
        self,
        messages: list[Message],
        session_id: str,
        user_id: str | None = None,
        username: str | None = None,
        chapter_context: str = "",
    ) -> list[HistoryMessage]:
        """Get a response from the LLM.

        Args:
            messages (list[Message]): The messages to send to the LLM.
            session_id (str): The session ID for the conversation.
            user_id (Optional[str]): The user ID for the conversation.
            username (Optional[str]): The display name of the user.
            chapter_context (str): Courseware text for chapter-scoped Q&A.

        Returns:
            list[Message]: The response from the LLM.
        """
        graph = await self._get_graph()
        # Step 6 (observability) appends the langfuse callback handler here.
        callbacks: list[BaseCallbackHandler] = []
        config: RunnableConfig = {
            "configurable": {"thread_id": session_id},
            "callbacks": callbacks,
            "metadata": {
                "user_id": user_id,
                "username": username,
                "session_id": session_id,
                "chapter_context": chapter_context,
                "environment": settings.ENVIRONMENT.value,
            },
        }

        try:
            # Run state check and memory search concurrently to save 200-500ms
            if self.memory_service is not None:
                state, relevant_memory = await asyncio.gather(
                    graph.aget_state(config),
                    self.memory_service.search(user_id, messages[-1].content),
                )
            else:
                state = await graph.aget_state(config)
                relevant_memory = ""

            if _has_pending_interrupt(state):
                logger.info(
                    "resuming_interrupted_graph",
                    session_id=session_id,
                    next_nodes=state.next,
                )
                response = await graph.ainvoke(
                    Command(resume=messages[-1].content),
                    config=config,
                )
            else:
                relevant_memory = relevant_memory or "（暂无相关记忆）"
                response = await graph.ainvoke(
                    input={
                        "messages": dump_messages(messages),
                        "long_term_memory": relevant_memory,
                    },
                    config=config,
                )

            # Check if the graph was interrupted during this invocation
            state = await graph.aget_state(config)
            if _has_pending_interrupt(state):
                interrupt_value = (
                    state.tasks[0].interrupts[0].value
                    if state.tasks
                    else "Waiting for input."
                )
                logger.info(
                    "graph_interrupted",
                    session_id=session_id,
                    interrupt_value=str(interrupt_value),
                )
                return [HistoryMessage(role="assistant", content=str(interrupt_value))]

            openai_msgs = cast(
                list[dict[str, Any]], convert_to_openai_messages(response["messages"])
            )
            if self.memory_service is not None:
                asyncio.create_task(
                    self.memory_service.add(
                        user_id, openai_msgs, config.get("metadata")
                    )
                )
            return to_history_messages(response["messages"])
        except GraphInterrupt:
            state = await graph.aget_state(config)
            interrupt_value = (
                state.tasks[0].interrupts[0].value
                if state.tasks
                else "Waiting for input."
            )
            logger.info(
                "graph_interrupted",
                session_id=session_id,
                interrupt_value=str(interrupt_value),
            )
            return [HistoryMessage(role="assistant", content=str(interrupt_value))]
        except Exception as e:
            logger.exception("get_response_failed", error=str(e), session_id=session_id)
            raise

    async def get_stream_response(
        self,
        messages: list[Message],
        session_id: str,
        user_id: str | None = None,
        username: str | None = None,
        chapter_context: str = "",
    ) -> AsyncGenerator[str]:
        """Get a stream response from the LLM.

        Args:
            messages (list[Message]): The messages to send to the LLM.
            session_id (str): The session ID for the conversation.
            user_id (Optional[str]): The user ID for the conversation.
            username (Optional[str]): The display name of the user.
            chapter_context (str): Courseware text for chapter-scoped Q&A.

        Yields:
            str: Tokens of the LLM response.
        """
        # Step 6 (observability) appends the langfuse callback handler here.
        callbacks: list[BaseCallbackHandler] = []
        config: RunnableConfig = {
            "configurable": {"thread_id": session_id},
            "callbacks": callbacks,
            "metadata": {
                "user_id": user_id,
                "username": username,
                "session_id": session_id,
                "chapter_context": chapter_context,
                "environment": settings.ENVIRONMENT.value,
            },
        }
        graph = await self._get_graph()

        try:
            # Run state check and memory search concurrently to save 200-500ms
            if self.memory_service is not None:
                state, relevant_memory = await asyncio.gather(
                    graph.aget_state(config),
                    self.memory_service.search(user_id, messages[-1].content),
                )
            else:
                state = await graph.aget_state(config)
                relevant_memory = ""

            if _has_pending_interrupt(state):
                logger.info(
                    "resuming_interrupted_graph_stream",
                    session_id=session_id,
                    next_nodes=state.next,
                )
                graph_input: Any = Command(resume=messages[-1].content)
            else:
                relevant_memory = relevant_memory or "（暂无相关记忆）"
                graph_input = {
                    "messages": dump_messages(messages),
                    "long_term_memory": relevant_memory,
                }

            async for token, _ in graph.astream(
                graph_input,
                config,
                stream_mode="messages",
            ):
                if not isinstance(token, (AIMessage, AIMessageChunk)):
                    continue

                text = extract_text_content(token.content)
                if text:
                    yield text

            # After streaming completes, check for interrupt or update memory
            state = await graph.aget_state(config)
            if _has_pending_interrupt(state):
                interrupt_value = (
                    state.tasks[0].interrupts[0].value
                    if state.tasks
                    else "Waiting for input."
                )
                logger.info(
                    "graph_interrupted_stream",
                    session_id=session_id,
                    interrupt_value=str(interrupt_value),
                )
                yield str(interrupt_value)
            elif (
                state.values
                and "messages" in state.values
                and self.memory_service is not None
            ):
                openai_msgs = cast(
                    list[dict[str, Any]],
                    convert_to_openai_messages(state.values["messages"]),
                )
                asyncio.create_task(
                    self.memory_service.add(
                        user_id, openai_msgs, config.get("metadata")
                    )
                )
        except GraphInterrupt:
            state = await graph.aget_state(config)
            interrupt_value = (
                state.tasks[0].interrupts[0].value
                if state.tasks
                else "Waiting for input."
            )
            logger.info(
                "graph_interrupted_stream",
                session_id=session_id,
                interrupt_value=str(interrupt_value),
            )
            yield str(interrupt_value)
        except Exception as stream_error:
            logger.exception(
                "stream_processing_failed",
                error=str(stream_error),
                session_id=session_id,
            )
            raise stream_error

    async def get_chat_history(self, session_id: str) -> list[HistoryMessage]:
        """Get the chat history for a given thread ID.

        Args:
            session_id (str): The session ID for the conversation.

        Returns:
            list[Message]: The chat history.
        """
        graph = await self._get_graph()

        config: RunnableConfig = {"configurable": {"thread_id": session_id}}
        state: StateSnapshot = await graph.aget_state(config=config)
        return to_history_messages(state.values["messages"]) if state.values else []

    async def clear_chat_history(self, session_id: str) -> None:
        """Clear all chat history for a given thread ID.

        Args:
            session_id: The ID of the session to clear history for.

        Raises:
            Exception: If there's an error clearing the chat history.
        """
        try:
            # Make sure the pool is initialized in the current event loop
            conn_pool = await self._get_connection_pool()
            await clear_thread_rows(conn_pool, session_id)
        except Exception as e:
            logger.error(
                "clear_chat_history_operation_failed",
                session_id=session_id,
                error=str(e),
            )
            raise

    async def thread_has_history(self, thread_id: str) -> bool:
        """Whether the thread has any checkpoint row (used by legacy import)."""
        conn_pool = await self._get_connection_pool()
        return await thread_row_count(conn_pool, thread_id) > 0

    async def close(self) -> None:
        """Release the connection pool and forget the compiled graph.

        Called on application shutdown so the next lifespan (TestClient per
        test module, a worker restart) rebuilds both instead of reusing a
        pool whose connections belong to a closed event loop.
        """
        if self._connection_pool is not None:
            await self._connection_pool.close()
            self._connection_pool = None
            logger.info("connection_pool_closed")
        self._graph = None


langgraph_agent = LangGraphAgent()
