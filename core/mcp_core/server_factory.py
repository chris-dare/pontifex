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

from fastapi import FastAPI, Request
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp_core.audit import AuditWriter, DbAuditWriter, NoopAuditWriter
from mcp_core.auth.context import set_stdio_caller
from mcp_core.auth.discovery import external_base_url
from mcp_core.auth.identity import CallerIdentity
from mcp_core.auth.jwt_validator import JWTValidator
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

    jwt_validator: JWTValidator | None = None
    if settings.auth_jwks_url:
        jwt_validator = JWTValidator(
            jwks_url=settings.auth_jwks_url,
            issuer=settings.auth_issuer,
            audience=settings.auth_audience,
            scopes_claim=settings.auth_scopes_claim,
            default_rate_limit_rpm=settings.jwt_default_rate_limit_rpm,
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with mcp_server.session_manager.run():
            try:
                yield
            finally:
                if jwt_validator is not None:
                    await jwt_validator.aclose()

    app = FastAPI(title=f"{domain_name}-mcp", lifespan=lifespan)

    if settings.logfire_token:
        setup_logfire(app, domain_name, settings.logfire_token)

    app.add_middleware(
        AuthMiddleware,
        redis_url=settings.redis_url,
        database_url=settings.database_url,
        cache_ttl=settings.api_key_cache_ttl_seconds,
        jwt_validator=jwt_validator,
        public_base_url=settings.public_base_url,
        allowed_hosts=settings.allowed_hosts,
    )

    @app.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def readiness() -> dict[str, Any]:
        return await health_check()

    # OAuth 2.0 Protected Resource Metadata (RFC 9728).  MCP clients fetch
    # this to discover the authorization server.  Only meaningful when JWT
    # auth is configured.
    @app.get("/.well-known/oauth-protected-resource")
    async def oauth_protected_resource(request: Request) -> dict[str, Any]:
        if not settings.auth_jwks_url:
            return {"error": "JWT auth not configured."}
        authz_server = settings.auth_authorization_server or settings.auth_issuer
        # RFC 9728: `resource` is the protected resource's *own* canonical URI
        # (the MCP endpoint), NOT the authorization-server API audience.  MCP
        # clients validate this against the URL they connected to.  The host
        # comes from the configured `public_base_url` (or a request fallback
        # pinned to `allowed_hosts`), so a spoofed X-Forwarded-Host can't change
        # the advertised resource identifier.
        base = external_base_url(request, settings.public_base_url, settings.allowed_hosts)
        return {
            "resource": f"{base}/mcp",
            "authorization_servers": [authz_server] if authz_server else [],
            "bearer_methods_supported": ["header"],
        }

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
