"""PontifexMCP — a drop-in subclass of the MCP SDK's built-in FastMCP.

Swap `from mcp.server.fastmcp import FastMCP` for
`from pontifex_mcp import PontifexMCP` and existing code keeps working. The
enterprise concerns are additive, all defaulting to zero-infra:

  - `@tool(scope=...)`: declare a `resource:action` (or `namespace:resource:action`)
    scope. Advisory until an auth backend is configured.
  - `auth=`: `ApiKeyAuth()` / `JwtAuth()` enable enforcement (read infra from env).
    Omitted → open mode (anonymous caller; HTTP binds localhost).
  - `audit=`: `None` → stdout; a path/URL → durable; a list → tee.

The floor needs no DB, Redis, or auth:

    mcp = PontifexMCP("payments")

    @mcp.tool(scope="balance:read")
    async def get_balance() -> dict:
        return {"available": 421000, "currency": "usd"}

    mcp.run()
"""

from collections.abc import Callable
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from pontifex_mcp.adapters.manager import DataSourceManager
from pontifex_mcp.audit import AuditSpec, AuditWriter, resolve_audit_writer
from pontifex_mcp.auth.context import set_stdio_caller
from pontifex_mcp.auth.identity import anonymous_identity
from pontifex_mcp.cache.redis_cache import Cache
from pontifex_mcp.config import CoreSettings, require_url
from pontifex_mcp.connectors.register import register_openapi_tools
from pontifex_mcp.server_factory import build_http_app
from pontifex_mcp.tool_runtime import tool_runtime

logger = structlog.get_logger(__name__)


class ApiKeyAuth:
    """Enable API-key auth, reading `DATABASE_URL` (and optional `REDIS_URL`).

    `DATABASE_URL` is the key store: a SQLite file for the zero-infra floor
    (`sqlite+aiosqlite:///pontifex.db`) or Postgres for production. `REDIS_URL`
    is optional — with it, key lookups are cached and per-caller rate limiting
    is enforced; without it, the store is read directly and rate limiting is
    off (logged at startup). A marker: the infra URLs come from the environment
    so laptop → prod is a config change.
    """


class JwtAuth:
    """Enable OAuth 2.1 / JWT auth, reading the `AUTH_*` env vars."""


AuthBackend = ApiKeyAuth | JwtAuth


def _parse_scope(scope: str | None, default_namespace: str) -> tuple[str, str | None, str | None]:
    """Resolve a `@tool(scope=...)` string to `(namespace, resource, action)`.

    `None` → no scope (the action triple is None/None, enforcement skipped).
    `"resource:action"` → the app's own namespace. `"namespace:resource:action"` →
    explicit namespace.
    """
    if not scope:
        return (default_namespace, None, None)
    parts = scope.split(":")
    if len(parts) in (2, 3) and all(p.strip() for p in parts):
        if len(parts) == 2:
            return (default_namespace, parts[0], parts[1])
        return (parts[0], parts[1], parts[2])
    raise ValueError(
        f"Invalid scope {scope!r}: expected 'resource:action' or "
        "'namespace:resource:action' with non-empty parts."
    )


def _resolve_cache(spec: object, settings: CoreSettings, namespace: str) -> Cache | None:
    """Resolve the `cache=` kwarg to a `Cache` (or None).

    - `None` / `False` → no cache
    - a `Cache` → used as-is
    - `True` / `"redis"` → `Cache` from `REDIS_URL` (required)
    - any other str → a Redis URL
    Keys are namespaced by the app's namespace.
    """
    if spec is None or spec is False:
        return None
    if isinstance(spec, Cache):
        return spec
    if spec is True or spec == "redis":
        url = require_url(settings.redis_url, "REDIS_URL", "cache")
        return Cache(url, prefix=namespace)
    if isinstance(spec, str):
        return Cache(spec, prefix=namespace)
    raise TypeError(
        f"Unsupported cache spec {spec!r}: expected None, True, a Redis URL, or a Cache."
    )


class PontifexMCP(FastMCP):
    """FastMCP with opt-in auth, scopes, and audit. See module docstring."""

    def __init__(
        self,
        name: str,
        instructions: str = "",
        *,
        auth: AuthBackend | None = None,
        audit: AuditSpec = None,
        cache: object = None,
        **settings: Any,
    ) -> None:
        # Infra config (port, host, allowed_hosts, AUTH_*) comes from the env via
        # CoreSettings — now optional, so a bare server constructs with nothing set.
        self._settings = CoreSettings()
        hosts = [h.strip() for h in self._settings.allowed_hosts.split(",") if h.strip()]
        settings.setdefault("stateless_http", True)
        settings.setdefault("json_response", True)
        settings.setdefault(
            "transport_security",
            TransportSecuritySettings(
                enable_dns_rebinding_protection=bool(hosts), allowed_hosts=hosts
            ),
        )
        super().__init__(name=name, instructions=instructions, **settings)
        self._namespace = name
        self._auth = auth
        self._audit: AuditWriter = resolve_audit_writer(audit)
        # Public so tools (which close over the app) can use it: `await mcp.cache.get(...)`.
        self.cache: Cache | None = _resolve_cache(cache, self._settings, name)

    def tool(
        self,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: Any = None,
        icons: Any = None,
        meta: dict[str, Any] | None = None,
        structured_output: bool | None = None,
        *,
        scope: str | None = None,
    ) -> Callable[[Any], Any]:
        """Register a tool, folding in scope enforcement + audit.

        Mirrors FastMCP's `.tool()` signature; `scope` is the only addition —
        a `resource:action` (or `namespace:resource:action`) string. Omit it for an
        advisory (unenforced) tool.
        """
        if callable(name):
            raise TypeError(
                "@tool was used without parentheses. Use @mcp.tool() (optionally "
                "with scope=...), not @mcp.tool."
            )
        parent_tool = super().tool
        namespace = self._namespace
        audit = self._audit

        def decorator(fn: Any) -> Any:
            tool_name = name or fn.__name__
            scope_namespace, resource, action = _parse_scope(scope, namespace)
            wrapped = tool_runtime(
                namespace=scope_namespace,
                tool_name=tool_name,
                resource=resource,
                action=action,
                audit=audit,
            )(fn)
            # Same composition GSE does by hand: FastMCP introspects the inner
            # signature through functools.wraps for the input schema.
            parent_tool(
                name=tool_name,
                title=title,
                description=description,
                annotations=annotations,
                icons=icons,
                meta=meta,
                structured_output=structured_output,
            )(wrapped)
            return fn

        return decorator

    def run(
        self,
        transport: str = "stdio",
        mount_path: str | None = None,
        *,
        http: bool = False,
        auth: str | None = None,
    ) -> None:
        """Run the server. `http=True` is shorthand for streamable-http.

        With no auth backend, HTTP binds 127.0.0.1; pass `auth="none"` to bind
        0.0.0.0 unauthenticated (a loud warning is logged).

        Note: stdio is inherently local, so the caller is always anonymous there
        (scopes advisory) — an `auth=` backend only takes effect over HTTP.
        """
        if http:
            transport = "streamable-http"
        if transport == "stdio":
            self._run_stdio()
        elif transport == "streamable-http":
            self._run_http(network_optout=auth)
        elif transport == "sse":
            # Legacy transport; no pontifex auth/audit wiring — delegate to FastMCP.
            super().run(transport="sse", mount_path=mount_path)
        else:
            raise ValueError(f"Unknown transport: {transport!r}")

    def add_openapi(
        self,
        *,
        spec: str | dict[str, Any],
        base_url: str,
        include: list[str],
        allow_mutations: bool = False,
        auth: Any = None,
        names: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> DataSourceManager:
        """Generate one governed tool per allowlisted operation in an OpenAPI spec.

        The tools register on this app with its audit sink and namespace. `include`
        is an explicit allowlist of operations (e.g. ``["GET /orders/{id}"]``);
        mutating verbs additionally require ``allow_mutations=True``. Returns the
        `DataSourceManager` so you can fold it into a health check.
        """
        return register_openapi_tools(
            self,
            spec=spec,
            namespace=self._namespace,
            base_url=base_url,
            audit=self._audit,
            include=include,
            allow_mutations=allow_mutations,
            auth=auth,
            names=names,
            **kwargs,
        )

    async def _readiness(self) -> dict[str, str]:
        return {"status": "ok"}

    def _run_stdio(self) -> None:
        # stdio is inherently local; the caller is anonymous. Tools are already
        # wrapped with the resolved audit sink, so audit (e.g. stdout) works.
        set_stdio_caller(anonymous_identity("stdio"))
        super().run(transport="stdio")

    def _run_http(self, *, network_optout: str | None) -> None:
        import uvicorn

        settings = self._settings
        open_mode = self._auth is None
        if open_mode and (settings.auth_jwks_url or settings.database_url):
            # The environment looks provisioned for auth, but no backend was
            # passed — the server will run open/anonymous and ignore it. Surface
            # that rather than silently failing open.
            logger.warning(
                "pontifex_open_mode_ignores_env_auth",
                msg=(
                    "Running open/anonymous, but AUTH_JWKS_URL / DATABASE_URL are set "
                    "in the environment. Pass auth=ApiKeyAuth() or auth=JwtAuth() to "
                    "enforce them."
                ),
            )
        if not open_mode:
            self._require_auth_env(settings)

        app = build_http_app(
            self._namespace,
            self,
            settings,
            self._readiness,
            allow_anonymous=open_mode,
            enable_api_keys=isinstance(self._auth, ApiKeyAuth),
        )
        host = self._http_host(settings, open_mode=open_mode, network_optout=network_optout)
        uvicorn.run(app, host=host, port=settings.port, log_level=settings.log_level.lower())

    def _require_auth_env(self, settings: CoreSettings) -> None:
        """Fail fast if the configured auth backend's env vars are missing."""
        if isinstance(self._auth, ApiKeyAuth):
            # REDIS_URL is optional: without it the key store is read directly
            # (SQLite or Postgres) and rate limiting is disabled (see AuthMiddleware).
            require_url(settings.database_url, "DATABASE_URL", "ApiKeyAuth")
        elif isinstance(self._auth, JwtAuth):
            require_url(settings.auth_jwks_url, "AUTH_JWKS_URL", "JwtAuth")

    def _http_host(
        self, settings: CoreSettings, *, open_mode: bool, network_optout: str | None
    ) -> str:
        if not open_mode:
            return settings.host or "0.0.0.0"
        if network_optout == "none":
            logger.warning(
                "pontifex_unauthenticated_public_bind",
                msg=(
                    "Serving UNAUTHENTICATED on 0.0.0.0 — anyone who can reach "
                    "this port can call every tool. Configure auth= to lock it down."
                ),
                port=settings.port,
            )
            return "0.0.0.0"
        # Open and not opted out: localhost only.
        return "127.0.0.1"
