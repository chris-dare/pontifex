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

from pontifex_mcp.adapters.manager import DataSourceManager
from pontifex_mcp.audit import AuditWriter, DbAuditWriter, NoopAuditWriter
from pontifex_mcp.auth.context import set_stdio_caller
from pontifex_mcp.auth.discovery import external_base_url
from pontifex_mcp.auth.identity import CallerIdentity
from pontifex_mcp.auth.jwt_validator import JWTValidator
from pontifex_mcp.config import CoreSettings, require_url
from pontifex_mcp.connectors.config import register_connectors_from_config
from pontifex_mcp.middleware.auth import AuthMiddleware
from pontifex_mcp.observability.logfire_setup import setup_logfire


def create_mcp_http_app(
    domain_name: str,
    settings: CoreSettings,
    register_tools: Callable[[FastMCP, AuditWriter], None],
    health_check: Callable[[], Awaitable[dict[str, Any]]],
    *,
    instructions: str = "",
    audit: AuditWriter | None = None,
) -> FastAPI:
    """Build FastAPI hosting a FastMCP Streamable HTTP server.

    The MCP server is mounted at `/` so its endpoint is `/mcp` (FastMCP's
    default `streamable_http_path`). AuthMiddleware runs first on every
    request; readiness/liveness endpoints sit alongside.

    `audit` is the resolved sink (the facade passes one in). When omitted it
    defaults to a Postgres `DbAuditWriter` from `settings.database_url`, which
    preserves the original direct-factory behavior.
    """
    # This entry point always wires a Postgres audit writer (unless `audit` is
    # given) and a closed AuthMiddleware backed by Redis + Postgres, so both are
    # required. CoreSettings no longer enforces this globally (a bare PontifexMCP
    # server needs neither), so fail fast here with a clear, named error rather
    # than booting with a silently-broken audit/rate-limiter.
    require_url(settings.database_url, "DATABASE_URL", "create_mcp_http_app")
    require_url(settings.redis_url, "REDIS_URL", "create_mcp_http_app")

    if audit is None:
        audit = DbAuditWriter(settings.database_url)
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

    connector_managers: dict[str, DataSourceManager] = {}
    if settings.connectors_config:
        connector_managers = register_connectors_from_config(
            mcp_server, audit, settings.connectors_config
        )

    return build_http_app(
        domain_name,
        mcp_server,
        settings,
        health_check,
        connector_managers=connector_managers,
    )


def build_http_app(
    domain_name: str,
    mcp_server: FastMCP,
    settings: CoreSettings,
    health_check: Callable[[], Awaitable[dict[str, Any]]],
    *,
    allow_anonymous: bool = False,
    enable_api_keys: bool = True,
    connector_managers: dict[str, DataSourceManager] | None = None,
) -> FastAPI:
    """Wrap an already-built FastMCP server in a FastAPI app.

    Shared by `create_mcp_http_app` (which builds the FastMCP from a
    `register_tools` callback) and `PontifexMCP.run()` (which passes itself, with
    tools already registered). `allow_anonymous` selects open mode: the
    AuthMiddleware injects an anonymous caller instead of requiring a token, and
    no JWT/API-key backend is wired.

    `enable_api_keys` gates whether the API-key resolver is wired from
    `DATABASE_URL`. The facade passes `False` for a `JwtAuth()` server so that
    setting `DATABASE_URL` (e.g. for Postgres audit) does not silently turn on
    API-key auth. Defaults to `True` for the legacy `create_mcp_http_app` path,
    which always serves API keys.
    """
    connector_managers = connector_managers or {}

    jwt_validator: JWTValidator | None = None
    if not allow_anonymous and settings.auth_jwks_url:
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
                # Close connector-owned HTTP clients (adapter + its auth).
                for manager in connector_managers.values():
                    for adapter in manager.adapters:
                        closer = getattr(adapter, "close", None)
                        if closer is not None:
                            await closer()

    app = FastAPI(title=f"{domain_name}-mcp", lifespan=lifespan)

    if settings.logfire_token:
        setup_logfire(app, domain_name, settings.logfire_token)

    if allow_anonymous:
        app.add_middleware(
            AuthMiddleware,
            allow_anonymous=True,
            public_base_url=settings.public_base_url,
            allowed_hosts=settings.allowed_hosts,
        )
    else:
        # Only wire the API-key store when API keys are actually enabled. A
        # JwtAuth server with DATABASE_URL set (for audit) must not authenticate
        # sk_ tokens against the key table — that path stays "not configured".
        app.add_middleware(
            AuthMiddleware,
            redis_url=(settings.redis_url or None) if enable_api_keys else None,
            database_url=(settings.database_url or None) if enable_api_keys else None,
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
        result = await health_check()
        for connector_domain, manager in connector_managers.items():
            result[f"connector:{connector_domain}"] = await manager.health_summary()
        return result

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
    audit: AuditWriter | None = None,
    identity: CallerIdentity | None = None,
) -> None:
    """Blocking stdio runner. Loads identity from settings into a ContextVar.

    `audit` is the resolved sink; stdio honors it (e.g. stdout audit). When
    omitted it defaults to `NoopAuditWriter`, preserving prior behavior.

    `identity` overrides the stdio caller; the facade passes an anonymous
    identity when no auth is configured. When omitted it's built from the
    `stdio_*` settings, preserving prior behavior.
    """
    if identity is None:
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
    if audit is None:
        audit = NoopAuditWriter()
    register_tools(mcp_server, audit)
    if settings.connectors_config:
        register_connectors_from_config(mcp_server, audit, settings.connectors_config)
    asyncio.run(mcp_server.run_stdio_async())


# Backwards-compat alias used by callers that don't yet know about the split.
create_mcp_app = create_mcp_http_app
