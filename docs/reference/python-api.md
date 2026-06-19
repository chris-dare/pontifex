# Python API

Everything below imports from `pontifex_mcp`. This is the **supported public
surface.**

```python
from pontifex_mcp import PontifexMCP, ApiKeyAuth, JwtAuth  # the facade — start here
```

Anything reached through a deeper path (`pontifex_mcp.middleware`, `pontifex_mcp.auth`,
…) is internal. It may change without a major-version bump.

## Server — the facade (start here)

`PontifexMCP(name, instructions='', *, auth=None, audit=None, cache=None, **settings)`
:   A drop-in subclass of the MCP SDK's `FastMCP`. Defaults to zero infrastructure
    (anonymous caller, audit → stdout). `auth` enables enforcement (`ApiKeyAuth()` /
    `JwtAuth()`); `audit` selects the sink (`None` → stdout, a path/URL → durable, a list
    → tee); `cache` wires a Redis cache exposed as `mcp.cache`. See the
    [Quickstart](../learn/quickstart.md) for the rung-by-rung build-up.

`@mcp.tool(name=None, *, scope=None, **fastmcp_kwargs)`
:   FastMCP's `.tool()` plus a `scope`. `scope="resource:action"` (or
    `"domain:resource:action"`) is enforced when an auth backend is configured, advisory
    otherwise; omit it for an unscoped tool. Folds scope-check + audit in for you.

`mcp.run(transport='stdio', mount_path=None, *, http=False, auth=None)`
:   Runs the server. `http=True` is shorthand for streamable-http. With no auth backend,
    HTTP binds `127.0.0.1`; pass `auth="none"` to bind `0.0.0.0` (logs a warning).

`mcp.add_openapi(*, spec, base_url, include, allow_mutations=False, auth=None, names=None)` → `DataSourceManager`
:   Generate one governed tool per allowlisted operation in an OpenAPI spec, registered
    on the app with its audit sink. See [Connect an API](../learn/connect-an-api.md).

`ApiKeyAuth()` / `JwtAuth()`
:   Auth backends passed to `PontifexMCP(auth=...)`. `ApiKeyAuth` reads `DATABASE_URL` +
    `REDIS_URL` (and activates JWT too if `AUTH_JWKS_URL` is set); `JwtAuth` reads the
    `AUTH_*` group. Both fail fast if their env vars are missing.

## Server — lower-level factory

For full control (or to wire pieces the facade doesn't expose), build the app directly:

`create_mcp_http_app(domain_name, settings, register_tools, health_check, *, instructions='', audit=None)` → `FastAPI`
:   Builds the ASGI app. Wires auth + rate-limit middleware, the audit writer, OAuth
    discovery endpoints, and your registered tools. Requires `DATABASE_URL` + `REDIS_URL`.

`run_mcp_stdio(domain_name, settings, register_tools, *, instructions='', audit=None, identity=None)` → `None`
:   Blocking runner for the stdio transport: local MCP clients that launch the server
    as a subprocess. It returns `None`, not a coroutine. Call it, don't
    `await` it.

## Configuration

`CoreSettings`
:   The settings base class (pydantic-settings). Subclass it to add domain fields. You
    inherit the infrastructure settings: `DATABASE_URL`, `REDIS_URL`, the `AUTH_*` group,
    and `PUBLIC_BASE_URL`. Every variable: [Configuration](configuration.md).

## Tools

`tool_runtime(*, domain, tool_name, resource, action, audit, source_unavailable_exception=None)`
:   The decorator that wraps a tool handler. Enforces the `domain:resource:action`
    scope and writes the audit row. A successful return value passes through unchanged;
    it converts a raised error into a structured `ToolError`. `source_unavailable_exception`
    maps a domain's own "all sources down" exception to a clean unavailable response.

`InvalidInput`
:   Raise inside a handler to reject bad arguments with a clean, structured error
    instead of a 500. See [Errors & scopes](errors-and-scopes.md).

## Connectors

`register_openapi_tools(mcp, *, spec, domain, base_url, audit, include, auth=None, allow_mutations=False, names=None, ...)` → `DataSourceManager`
:   Generates one governed tool per allowlisted operation in an OpenAPI 3.x spec. It
    wraps each in `tool_runtime` with a scope derived from the operation, and returns the
    manager wrapping the generated adapter, so you can fold it into your health checks.
    Guide: [Connect an API](../learn/connect-an-api.md).

`BearerFromEnv(env_var)` / `HeaderFromEnv(header, env_var)`
:   Service-credential auth for the generated adapter: a bearer token or static header,
    read from the environment per request (presence checked at startup). One identity
    for all callers.

`TokenExchange(*, token_endpoint, audience, client_id_env, client_secret_env, client_auth='post', default_ttl_seconds=None, ...)`
:   Per-user downstream auth via OAuth token exchange
    ([RFC 8693](https://www.rfc-editor.org/rfc/rfc8693)). Exchanges the caller's token
    for one scoped to `audience`, on their behalf, with no passthrough. It rejects
    API-key callers, which have no token to exchange. Guide:
    [Authenticate to your backend](../guides/downstream-auth.md).

Exchanged tokens are cached behind the `TokenCache` seam, chosen by
`PONTIFEX_TOKEN_CACHE` (`memory`, default; or `redis`, encrypted at rest with
`PONTIFEX_TOKEN_CACHE_KEY`).

## Identity & scopes

`CallerIdentity`
:   The resolved caller: `key_id`, `owner_id`, `owner_label`, `scopes`,
    `rate_limit_rpm`, `transport`. Produced by both the API-key and JWT paths.

`scopes_match(scopes, domain, resource, action)` → `bool`
:   Whether the caller's `scopes` satisfy a required `domain` / `resource` / `action`.
    Honors wildcard forms: `domain:*:read`, `domain:resource:*`, `domain:*:*`. See
    [Errors & scopes](errors-and-scopes.md#scopes).

## Data adapters

`DataAdapter`
:   The protocol every external data source implements. Keeps I/O out of tool handlers
    and makes sources swappable and testable.

`DataSourceManager`
:   Orders adapters by health and records each one's success and failure
    (`get_available_adapters`, `record_success`, `record_failure`, `health_summary`).
    Gives your tool the ordering and bookkeeping to iterate sources and fail over. The
    domain code makes the actual calls. Guide:
    [Resilient adapters](../guides/resilient-adapters.md).

## Reliability

`Cache`
:   A namespaced, Redis-backed cache for adapter responses. You set the TTL per write.

`CircuitBreaker`
:   Trips after repeated failures to a source, then recovers automatically. Shields
    callers from a down upstream.

`async_retry(...)`
:   Decorator that retries a coroutine with backoff and jitter, for transient upstream
    errors.

## Audit

`AuditWriter`
:   The audit sink protocol. Implementations receive an `AuditRecord` per tool call.
    `resolve_audit_writer(spec)` maps the facade's `audit=` value to one of the below.

`StdoutAuditWriter`
:   Structured one-line-per-call via structlog. The facade default — audit stays visible
    with no infrastructure.

`DbAuditWriter`
:   Persists audit records to SQLite (a path/`sqlite://` URL) or Postgres
    (`postgresql+asyncpg://…`); the dialect is detected from the connection string.

`TeeAuditWriter`
:   Fans each record out to several writers (e.g. `audit=["stdout", "audit.db"]`).

`NoopAuditWriter`
:   Discards records — the explicit "off" sink.

## Models

`AuditRecord`
:   One audited call: caller, tool, timing, data source, cache hit.

`ToolResponse`
:   The success envelope returned to the client.

`ToolError`
:   The structured error envelope: a stable `error_code` and message, never a stack
    trace. Fields and codes: [Errors & scopes](errors-and-scopes.md).
