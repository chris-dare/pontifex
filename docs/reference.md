# API reference

Everything below is importable directly from `pontifex_mcp` and is the **supported public surface**.
Anything reached through a deeper path (`pontifex_mcp.middleware`, `pontifex_mcp.auth`, …) is internal
and may change without a major-version bump.

```python
from pontifex_mcp import create_mcp_http_app, tool_runtime, CoreSettings, DataAdapter  # etc.
```

## Server

`create_mcp_http_app(domain_name, settings, register_tools, health_check, *, instructions='')` → `FastAPI`
:   Builds the ASGI application: wires auth + rate-limit middleware, the audit writer, OAuth discovery
    endpoints, and your registered tools. Returns a FastAPI app to serve with any ASGI server.

`run_mcp_stdio(domain_name, settings, register_tools, *, instructions='')` → `None`
:   Blocking runner for the stdio transport (local MCP clients that launch the server as a subprocess).
    It returns `None`, not a coroutine — call it directly, don't `await` it.

## Configuration

`CoreSettings`
:   The settings base class (pydantic-settings). Subclass it to add domain-specific fields;
    infrastructure settings (`DATABASE_URL`, `REDIS_URL`, the `AUTH_*` group, `PUBLIC_BASE_URL`) are
    inherited.

## Tools

`tool_runtime(*, domain, tool_name, resource, action, audit, source_unavailable_exception=None)`
:   Decorator that wraps a tool handler: enforces the `domain:resource:action` scope and writes the
    audit row. A successful handler's return value passes through unchanged; a raised error is
    normalized into a structured `ToolError`. `source_unavailable_exception` maps a domain's own "all
    sources down" exception to a clean unavailable response.

`InvalidInput`
:   Raise inside a handler to reject bad arguments with a clean, structured error (rather than a 500).

## Identity & scopes

`CallerIdentity`
:   The resolved caller: `key_id`, `owner_id`, `owner_label`, `scopes`, `rate_limit_rpm`, and
    `transport`. Produced by both the API-key and JWT paths.

`scopes_match(scopes, domain, resource, action)` → `bool`
:   Returns whether the caller's `scopes` satisfy a required `domain` / `resource` / `action`, honoring
    wildcard forms like `domain:*:read`, `domain:resource:*`, and `domain:*:*`.

## Data adapters

`DataAdapter`
:   The protocol every external data source implements. Keeps I/O out of tool handlers and makes sources
    swappable and testable.

`DataSourceManager`
:   Orders adapters by health and records each one's success/failure (`get_available_adapters`,
    `record_success`, `record_failure`, `health_summary`). Gives your tool the ordering and bookkeeping
    to iterate sources and fail over — the domain code performs the actual calls.

## Reliability

`Cache`
:   A namespaced, Redis-backed cache for adapter responses.

`CircuitBreaker`
:   Trips after repeated failures to a source and recovers automatically, shielding callers from a down
    upstream.

`async_retry(...)`
:   Decorator that retries a coroutine with backoff and jitter, for transient upstream errors.

## Audit

`AuditWriter`
:   The audit sink protocol. Implementations receive an `AuditRecord` per tool call.

`DbAuditWriter`
:   Persists audit records to Postgres — the production default.

`NoopAuditWriter`
:   Discards records — useful in tests and local development.

## Models

`AuditRecord`
:   One audited call: caller, tool, timing, data source, cache hit.

`ToolResponse`
:   The success envelope returned to the client.

`ToolError`
:   The structured error envelope — a stable `error_code` and message, never a stack trace.
