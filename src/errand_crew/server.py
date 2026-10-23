"""MCP server (Streamable HTTP). Tools are asynchronous so a voice assistant never waits."""

from __future__ import annotations

import logging
import os
from typing import Annotated, Any

import uvicorn
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route

from .browser import KernelFetcher
from .config import Settings
from .judge import Judge
from .llm import ClaudeLLM
from .orchestrator import Busy, Orchestrator, RateLimited
from .planner import Planner
from .registry import Registry
from .schemas import Errand
from .security import ERRAND_ID_RE, BearerTokenVerifier
from .workers import Worker

log = logging.getLogger("errand_crew")

INSTRUCTIONS = (
    "Errand Crew compares product prices across Romanian electronics shops. "
    "Call start_errand with the user's request, then poll get_status every few seconds "
    "and read spoken_summary from get_result when it is ready. Read-only: it never "
    "logs in, buys or submits anything."
)

READ_ONLY = {"readOnlyHint": True, "openWorldHint": True, "destructiveHint": False}


def _find(orch: Orchestrator, errand_id: str) -> Errand:
    if not ERRAND_ID_RE.match(errand_id):
        raise ToolError("Unknown errand.")
    errand = orch.get(errand_id)
    if errand is None:
        raise ToolError("Unknown errand.")
    return errand


def build_server(orch: Orchestrator, auth=None) -> FastMCP:
    mcp = FastMCP("Errand Crew", instructions=INSTRUCTIONS, auth=auth)

    @mcp.tool(annotations=READ_ONLY)
    async def start_errand(
        request: Annotated[
            str,
            Field(
                min_length=3,
                max_length=300,
                description="What to find, e.g. 'cheapest 27 inch gaming monitor'.",
            ),
        ],
    ) -> dict[str, Any]:
        """Start comparing prices for a product across the supported shops.

        Returns immediately with an errand_id. The work takes up to a minute, so poll
        get_status and then call get_result.
        """
        try:
            errand = orch.start(request.strip())
        except Busy:
            raise ToolError("I'm busy with other errands. Please try again shortly.")
        except RateLimited:
            raise ToolError("The errand limit has been reached. Please try again later.")
        token = get_access_token()
        client = token.client_id if token else "unauthenticated"
        log.info("errand %s started by client %s", errand.id, client)
        return {
            "errand_id": errand.id,
            "status": errand.state,
            "message": "Started. Check get_status in a few seconds.",
        }

    @mcp.tool(annotations=READ_ONLY)
    async def get_status(
        errand_id: Annotated[str, Field(description="The id from start_errand.")],
    ) -> dict[str, Any]:
        """Progress of an errand: its state and what each shop's agent is doing."""
        errand = _find(orch, errand_id)
        plan = errand.plan
        return {
            "errand_id": errand.id,
            "status": errand.state,
            "category": plan.category if plan else None,
            "progress": errand.progress,
        }

    @mcp.tool(annotations=READ_ONLY)
    async def get_result(
        errand_id: Annotated[str, Field(description="The id from start_errand.")],
    ) -> dict[str, Any]:
        """The finished comparison. Read spoken_summary aloud to the user."""
        errand = _find(orch, errand_id)
        if errand.state == "failed":
            return {
                "ready": True,
                "status": "failed",
                "spoken_summary": "Sorry, I couldn't finish that errand.",
                "error": errand.error,
            }
        if errand.state != "done" or errand.result is None:
            return {"ready": False, "status": errand.state}
        return {"ready": True, "status": "done", **errand.result.model_dump(mode="json")}

    return mcp


def build_orchestrator(settings: Settings) -> Orchestrator:
    registry = Registry.load()
    llm = ClaudeLLM(settings.anthropic_api_key)
    fetcher = KernelFetcher(
        settings.kernel_api_key, registry, settings.max_page_chars, settings.kernel_headless
    )
    return Orchestrator(
        settings,
        registry,
        Planner(llm, registry, settings.planner_model, settings.max_sites_per_errand),
        Worker(fetcher, llm, registry, settings.worker_model),
        Judge(llm, settings.judge_model),
    )


def build_app(settings: Settings) -> Starlette:
    mcp = build_server(
        build_orchestrator(settings), auth=BearerTokenVerifier(settings.client_tokens)
    )
    mcp_app = mcp.http_app(
        path="/mcp",
        host_origin_protection=True if settings.allowed_hosts else "auto",
        allowed_hosts=list(settings.allowed_hosts) or None,
        allowed_origins=list(settings.allowed_origins) or None,
    )

    async def health(_: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    # /health sits outside the MCP app so platform health checks need no token or Host match.
    return Starlette(
        routes=[Route("/health", health), Mount("/", app=mcp_app)],
        lifespan=mcp_app.lifespan,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    uvicorn.run(
        build_app(settings),
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
