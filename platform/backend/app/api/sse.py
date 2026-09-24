"""Shared SSE frame generator for streaming agent replies.

Extracted from the chat route's inline generator so every streaming agent
endpoint emits the same frame protocol: one ``data: {"content", "done"}``
JSON event per chunk, and the stream ALWAYS ends with a ``done=true`` frame
— empty content on success, a readable error message on failure — so the
frontend never hangs waiting for a token that will not come. Error details
go to the server log only, never into the frames.
"""

import json
from collections.abc import AsyncGenerator
from typing import Any

from app.core.logging import logger
from app.schemas.chat import StreamResponse


async def sse_frames(
    chunk_gen: AsyncGenerator[str],
    *,
    error_text: str,
    log_event: str,
    **log_ctx: Any,
) -> AsyncGenerator[str]:
    """Wrap an async token generator into SSE ``data:`` frames.

    Args:
        chunk_gen: Yields reply text chunks (e.g. an agent's
            ``get_stream_response``).
        error_text: User-facing message for the final frame on failure.
        log_event: Structured-log event name when the stream fails.
        **log_ctx: Extra structured-log context (session ids, user id…).
    """
    try:
        async for chunk in chunk_gen:
            frame = StreamResponse(content=chunk, done=False)
            yield f"data: {json.dumps(frame.model_dump(mode='json'))}\n\n"
        final = StreamResponse(content="", done=True)
        yield f"data: {json.dumps(final.model_dump(mode='json'))}\n\n"
    except Exception as e:
        logger.exception(log_event, error=str(e), **log_ctx)
        error = StreamResponse(content=error_text, done=True)
        yield f"data: {json.dumps(error.model_dump(mode='json'))}\n\n"
