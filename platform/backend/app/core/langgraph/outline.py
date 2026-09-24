"""Teaching-outline agent (teacher-side): the second LangGraph agent.

Added as an infrastructure stress test for multi-agent support — see
docs/langgraph-migration-plan.md. Relationship to the chat agent
(``graph.py``):

- **No inheritance**: the chat agent's ``get_response`` carries
  memory-search and interrupt-resume logic that is chat-specific (step 4);
  a subclass would override most of it anyway.
- **Shared**: the checkpoint pool factory and thread-row cleanup
  (``checkpoint.py``), tool-call dispatch and history conversion
  (``utils.py``), and the LLM model factory (``services/llm``).
- **Isolated**: its own ``LLMService`` instance with its private tool set
  (inventory gap #5), its own connection pool and compiled graph, and the
  ``outline:`` thread-id namespace — sessions live ONLY in the checkpoint
  tables (no business-table row), so cross-agent isolation is exactly the
  thread-id boundary.

Simplifications vs the chat agent: no memory service, no HITL interrupt
handling — the outline flow is generate → revise → regenerate.
"""

from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
)
from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
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
from app.core.langgraph.tools.outline import outline_tools
from app.core.langgraph.utils import (
    dump_messages,
    execute_tool_calls,
    extract_text_content,
    prepare_messages,
    process_llm_response,
    to_history_messages,
)
from app.core.logging import logger
from app.core.prompts import load_outline_system_prompt
from app.schemas.chat import HistoryMessage, Message
from app.schemas.graph import OutlineState
from app.services.llm import LLMService


class OutlineAgent:
    """Manages the teaching-outline agent and its interactions with the LLM."""

    def __init__(self) -> None:
        """Initialize the outline agent with its own LLM service and tools.

        The private ``LLMService`` instance is the point: binding
        ``outline_tools`` on a shared instance would overwrite another
        agent's bindings (inventory gap #5).
        """
        self.llm_service = LLMService()
        self.llm_service.bind_tools(outline_tools)
        self.tools_by_name = {tool.name: tool for tool in outline_tools}
        self._connection_pool: PostgresConnPool | None = None
        self._graph: CompiledStateGraph[Any, Any, Any, Any] | None = None
        logger.info(
            "outline_agent_initialized",
            model=settings.DEFAULT_LLM_MODEL,
            tools=sorted(self.tools_by_name),
            environment=settings.ENVIRONMENT.value,
        )

    async def _get_connection_pool(self) -> PostgresConnPool:
        """Get this agent's checkpoint pool, creating it on first use.

        Raises:
            Exception: If the pool cannot be created, in every environment.
        """
        if self._connection_pool is None:
            self._connection_pool = await create_checkpoint_pool()
        return self._connection_pool

    async def _outline(
        self, state: OutlineState, config: RunnableConfig
    ) -> Command[Any]:
        """Process the outline state and generate a response.

        Mirrors the chat agent's ``_chat`` node with the outline system
        prompt (teacher name + course context ride config metadata).
        """
        teacher_name = config.get("metadata", {}).get("username")
        course_context = config.get("metadata", {}).get("course_context", "")
        thread_id = config.get("configurable", {}).get("thread_id")
        system_prompt = load_outline_system_prompt(
            teacher_name=teacher_name,
            course_context=course_context,
        )

        messages = prepare_messages(state.messages, system_prompt)

        try:
            response_message = await self.llm_service.call(dump_messages(messages))
            response_message = process_llm_response(response_message)

            logger.info(
                "outline_llm_response_generated",
                session_id=thread_id,
                environment=settings.ENVIRONMENT.value,
            )

            if isinstance(response_message, AIMessage) and response_message.tool_calls:
                goto = "tool_call"
            else:
                goto = END

            return Command(update={"messages": [response_message]}, goto=goto)
        except Exception as e:
            logger.error(
                "outline_llm_call_failed_all_models",
                session_id=thread_id,
                error=str(e),
                environment=settings.ENVIRONMENT.value,
            )
            raise Exception(
                f"failed to get llm response after trying all models: {str(e)}"
            ) from e

    async def _tool_call(self, state: OutlineState) -> Command[Any]:
        """Process tool calls from the last message, then return to outline."""
        tool_calls = state.messages[-1].tool_calls
        outputs = await execute_tool_calls(tool_calls, self.tools_by_name)
        return Command(update={"messages": outputs}, goto="outline")

    async def create_graph(self) -> CompiledStateGraph[Any, Any, Any, Any]:
        """Create and configure the outline workflow.

        Raises:
            Exception: If the graph cannot be built, in every environment.
        """
        if self._graph is None:
            try:
                graph_builder = StateGraph(OutlineState)
                graph_builder.add_node(
                    "outline", self._outline, destinations=("tool_call", END)
                )
                graph_builder.add_node(
                    "tool_call",
                    self._tool_call,
                    destinations=("outline",),
                    retry_policy=RetryPolicy(max_attempts=3),
                )
                graph_builder.set_entry_point("outline")
                graph_builder.set_finish_point("outline")

                # Raises if the pool cannot be created — no checkpointer, no service.
                connection_pool = await self._get_connection_pool()
                checkpointer = AsyncPostgresSaver(connection_pool)
                await checkpointer.setup()

                self._graph = graph_builder.compile(
                    checkpointer=checkpointer,
                    name=(
                        f"{settings.PROJECT_NAME} Outline Agent "
                        f"({settings.ENVIRONMENT.value})"
                    ),
                )

                logger.info(
                    "outline_graph_created",
                    environment=settings.ENVIRONMENT.value,
                )
            except Exception as e:
                logger.exception(
                    "outline_graph_creation_failed",
                    error=str(e),
                    environment=settings.ENVIRONMENT.value,
                )
                raise e

        return self._graph

    async def _get_graph(self) -> CompiledStateGraph[Any, Any, Any, Any]:
        """Return the compiled graph, creating it on first access."""
        if self._graph is None:
            self._graph = await self.create_graph()
        return self._graph

    def _thread_config(
        self,
        thread_id: str,
        username: str | None,
        course_context: str,
    ) -> RunnableConfig:
        """Build the invocation config shared by sync and stream paths."""
        return {
            "configurable": {"thread_id": thread_id},
            "metadata": {
                "username": username,
                "session_id": thread_id,
                "course_context": course_context,
                "environment": settings.ENVIRONMENT.value,
            },
        }

    async def get_response(
        self,
        messages: list[Message],
        thread_id: str,
        username: str | None = None,
        course_context: str = "",
    ) -> list[HistoryMessage]:
        """Generate an outline revision and return the full history."""
        graph = await self._get_graph()
        config = self._thread_config(thread_id, username, course_context)
        response = await graph.ainvoke(
            {"messages": dump_messages(messages)}, config=config
        )
        return to_history_messages(response["messages"])

    async def get_stream_response(
        self,
        messages: list[Message],
        thread_id: str,
        username: str | None = None,
        course_context: str = "",
    ) -> AsyncGenerator[str]:
        """Stream an outline revision token by token.

        Yields:
            str: Tokens of the LLM response.
        """
        graph = await self._get_graph()
        config = self._thread_config(thread_id, username, course_context)

        async for token, _ in graph.astream(
            {"messages": dump_messages(messages)},
            config,
            stream_mode="messages",
        ):
            if not isinstance(token, (AIMessage, AIMessageChunk)):
                continue

            text = extract_text_content(token.content)
            if text:
                yield text

    async def get_chat_history(self, thread_id: str) -> list[HistoryMessage]:
        """Get the outline history for a given thread ID (from checkpoints)."""
        graph = await self._get_graph()

        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        state: StateSnapshot = await graph.aget_state(config=config)
        return to_history_messages(state.values["messages"]) if state.values else []

    async def clear_chat_history(self, thread_id: str) -> None:
        """Clear the outline history for a given thread ID.

        Raises:
            Exception: If there's an error clearing the history.
        """
        try:
            conn_pool = await self._get_connection_pool()
            await clear_thread_rows(conn_pool, thread_id)
        except Exception as e:
            logger.error(
                "outline_clear_history_failed",
                session_id=thread_id,
                error=str(e),
            )
            raise

    async def thread_has_history(self, thread_id: str) -> bool:
        """Whether the thread has any checkpoint row (used by legacy import)."""
        conn_pool = await self._get_connection_pool()
        return await thread_row_count(conn_pool, thread_id) > 0

    async def close(self) -> None:
        """Release the connection pool and forget the compiled graph.

        Called on application shutdown so the next lifespan rebuilds both
        (same rationale as the chat agent).
        """
        if self._connection_pool is not None:
            await self._connection_pool.close()
            self._connection_pool = None
            logger.info("outline_connection_pool_closed")
        self._graph = None


outline_agent = OutlineAgent()
