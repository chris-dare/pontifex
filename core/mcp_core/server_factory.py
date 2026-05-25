"""Transport wiring for an MCP domain server.

Two entry points:
  - `create_mcp_http_app(...)` → FastAPI hosting a FastMCP server mounted at
    `/`. AuthMiddleware runs per HTTP request; tools read the resolved
    CallerIdentity via `ctx.request_context.request.state.caller`.
  - `run_mcp_stdio(...)` → blocking stdio runner with no FastAPI / DB / Redis;
    identity is loaded once from settings into a ContextVar.
"""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp_core.audit import AuditWriter, DbAuditWriter, NoopAuditWriter
from mcp_core.auth.context import set_stdio_caller
from mcp_core.auth.identity import CallerIdentity
from mcp_core.config import CoreSettings
from mcp_core.middleware.auth import AuthMiddleware
from mcp_core.observability.logfire_setup import setup_logfire


def create_mcp_http_app(
    domain_name: str,
    settings: CoreSettings,
    register_tools: Callable[[FastMCP, AuditWriter], None],
    health_check: Callable[[], Awaitable[dict[str, Any]]],
    *,
    instructions: str = "",
) -> FastAPI:
    """Build FastAPI hosting a FastMCP Streamable HTTP server.

    The MCP server is mounted at `/` so its endpoint is `/mcp` (FastMCP's
    default `streamable_http_path`). AuthMiddleware runs first on every
    request; readiness/liveness endpoints sit alongside.
    """
    audit: AuditWriter = DbAuditWriter(settings.database_url)
    hosts = [h.strip() for h in settings.allowed_hosts.split(",") if h.strip()]
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(hosts),
        allowed_hosts=hosts,
    )
    mcp_server = FastMCP(
        name=f"{domain_name}-mcp",
        instructions=instructions,
        stateless_http=True,
        json_response=True,
        transport_security=transport_security,
    )
    register_tools(mcp_server, audit)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with mcp_server.session_manager.run():
            yield

    app = FastAPI(title=f"{domain_name}-mcp", lifespan=lifespan)

    if settings.logfire_token:
        setup_logfire(app, domain_name, settings.logfire_token)

    app.add_middleware(
        AuthMiddleware,
        redis_url=settings.redis_url,
        database_url=settings.database_url,
        cache_ttl=settings.api_key_cache_ttl_seconds,
    )

    @app.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def readiness() -> dict[str, Any]:
        return await health_check()

    # Mount FastMCP's Streamable HTTP ASGI app. Endpoint becomes /mcp.
    app.mount("/", mcp_server.streamable_http_app())

    return app


def run_mcp_stdio(
    domain_name: str,
    settings: CoreSettings,
    register_tools: Callable[[FastMCP, AuditWriter], None],
    *,
    instructions: str = "",
) -> None:
    """Blocking stdio runner. Loads identity from settings into a ContextVar."""
    identity = CallerIdentity(
        key_id=settings.stdio_key_id,
        owner_id=settings.stdio_owner_id,
        owner_label=settings.stdio_owner_label,
        scopes=[s.strip() for s in settings.stdio_scopes.split(",") if s.strip()],
        rate_limit_rpm=9999,
        transport="stdio",
    )
    set_stdio_caller(identity)

    mcp_server = FastMCP(name=f"{domain_name}-mcp", instructions=instructions)
    register_tools(mcp_server, NoopAuditWriter())
    asyncio.run(mcp_server.run_stdio_async())


# Backwards-compat alias used by callers that don't yet know about the split.
create_mcp_app = create_mcp_http_app
