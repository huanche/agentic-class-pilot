from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import sentry_sdk
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings
from app.core.langgraph.graph import langgraph_agent
from app.core.langgraph.outline import outline_agent
from app.core.logging import logger
from app.services.agent_registry import validate_registry

FRONTEND_DIR = Path(__file__).parent / "frontend"


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Pre-warm both LangGraph agents: pool + graph + checkpoint tables.

    Failure is deliberately not caught: the checkpointer is the only store
    for conversation history, so an unreachable DB should stop startup
    rather than serve a memory-less agent (vendor template design decision,
    docs/langgraph-migration-plan.md §2.2). Each agent owns its pool —
    steady state is 4+4 connections, budgeted in the migration plan.
    """
    if settings.EMBEDDED_AGENTS_ENABLED:
        await langgraph_agent.create_graph()
        await outline_agent.create_graph()
    # fail fast on a broken registry (duplicate keys, missing scope adapters)
    validate_registry()
    logger.info("graph_pre_warmed", model=settings.DEFAULT_LLM_MODEL)
    yield
    if settings.EMBEDDED_AGENTS_ENABLED:
        await langgraph_agent.close()
        await outline_agent.close()
    logger.info("application_shutdown")


if settings.SENTRY_DSN and settings.FASTAPI_ENV != "development":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_HOST],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)
if FRONTEND_DIR.exists():
    # Normal API routes above keep priority. Serve built assets when present and
    # return the SPA shell for client-side routes such as /login and /teacher.
    @app.get("/{frontend_path:path}", include_in_schema=False, tags=["frontend"])
    async def frontend_spa(frontend_path: str) -> FileResponse:
        if frontend_path == "api" or frontend_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")

        frontend_root = FRONTEND_DIR.resolve()
        requested = (frontend_root / frontend_path).resolve()
        try:
            requested.relative_to(frontend_root)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="Not Found") from error

        if requested.is_file():
            if requested.name == "index.html":
                return FileResponse(requested, headers={"Cache-Control": "no-cache"})
            # Hashed bundles are immutable; cache them long.
            return FileResponse(requested,
                                headers={"Cache-Control": "public, max-age=31536000, immutable"})
        # The SPA shell must never be cached: it references hashed asset
        # bundles, and a stale shell keeps users on a removed route set
        # (e.g. a sidebar entry pointing at a page the new build no longer
        # has).
        return FileResponse(frontend_root / "index.html",
                            headers={"Cache-Control": "no-cache"})
