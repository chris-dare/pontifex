from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI

from mcp_core.config import CoreSettings
from mcp_core.middleware.audit import AuditMiddleware
from mcp_core.middleware.auth import AuthMiddleware
from mcp_core.observability.logfire_setup import setup_logfire


def create_mcp_app(
    domain_name: str,
    settings: CoreSettings,
    register_tools: Callable[[FastAPI], None],
    health_check: Callable[[], Awaitable[dict[str, Any]]],
) -> FastAPI:
    """Build a fully configured FastAPI + MCP server for one domain."""
    app = FastAPI(title=f"{domain_name}-mcp")

    if settings.logfire_token:
        setup_logfire(app, domain_name, settings.logfire_token)

    # Starlette applies middleware in LIFO order: the last `add_middleware` call
    # wraps the request first. We want Auth to run before Audit (audit needs
    # `request.state.caller`), so add Audit first then Auth.
    app.add_middleware(
        AuditMiddleware,
        domain=domain_name,
        db_url=settings.database_url,
    )
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

    register_tools(app)

    return app
