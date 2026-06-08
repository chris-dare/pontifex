# pontifex-mcp

Enterprise-grade capabilities for MCP servers, built on the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).

`pontifex-mcp` lets you build [MCP](https://modelcontextprotocol.io) servers that connect AI agents to
real systems without giving up control over who can call what. You write the tools; it handles
authentication, per-caller scopes, rate limits, and a full audit trail.

## Key features

- **Secure by default** — OAuth 2.1 JWTs *and* `sk_…` API keys; every tool call is authenticated.
  Any OIDC provider (Auth0, Entra, Clerk, Keycloak).
- **Least-privilege scopes** — `domain:resource:action`, checked before every call. Callers can't
  widen their own access.
- **Auditable** — every call recorded: who, what, when, data source, cache hit, latency.
- **Standards-based** — RFC 9728 discovery + `WWW-Authenticate`; MCP clients bootstrap auth on their own.
- **Resilient** — per-caller rate limiting, adapter failover, circuit breaking.
- **Observable** — Logfire / OpenTelemetry tracing and metrics wired in.
- **Built on the MCP SDK** — keep its tools, protocol, and transports; add the controls a production
  server needs.

*Security is deliberate: asymmetric-only JWT validation, generic auth errors, and no token claim can
escalate a caller — all verifiable in the source.*

> **Status:** `0.x`, building in public. The security model is solid; the public API (everything
> exported from `pontifex_mcp`) is still settling — expect occasional breaking changes before `1.0`.

## Install

```bash
pip install pontifex-mcp     # or: uv add pontifex-mcp
```

Requires Python 3.12+, Postgres, and Redis.

## Build your own domain

A domain is: a settings class, one or more data adapters, and tools wrapped with `tool_runtime`.
Everything below comes from the top-level package.

```python
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from pontifex_mcp import (
    AuditWriter,
    CoreSettings,
    create_mcp_http_app,
    tool_runtime,
)


class OrdersSettings(CoreSettings):
    orders_api_base: str = "https://orders.internal.example.com"


def register_tools(mcp: FastMCP, audit: AuditWriter) -> None:
    @mcp.tool(name="orders_get_status", description="Look up the status of an order.")
    @tool_runtime(
        domain="orders",
        tool_name="orders_get_status",
        resource="order",        # scope checked: orders:order:read
        action="read",
        audit=audit,
    )
    async def get_order_status(order_id: str, ctx: Context | None = None) -> dict[str, Any]:
        # ... fetch from your internal system (ideally through a DataAdapter) ...
        return {"source": "orders-api", "cache_hit": False, "order_id": order_id, "status": "shipped"}


async def health() -> dict[str, Any]:
    return {"status": "ok"}


settings = OrdersSettings()
app = create_mcp_http_app("orders", settings, register_tools, health)
# `uv run uvicorn your_module:app` → MCP endpoint at /mcp, health at /health/ready
```

Auth, scope checks, rate limiting, the audit row, and the structured error envelope are all applied by
`tool_runtime` and the server's middleware — your handler just returns data.

### Configuration

Infrastructure settings read from bare, unprefixed env vars:

```
DATABASE_URL, REDIS_URL          # required (the app fails fast if unset)
AUTH_JWKS_URL, AUTH_ISSUER, AUTH_AUDIENCE, AUTH_SCOPES_CLAIM   # enable the OAuth/JWT path
PUBLIC_BASE_URL                  # canonical URL advertised in OAuth discovery
```

Domain-specific settings on your subclass read with your domain's `env_prefix`.

## Who it's for

Reach for `pontifex-mcp` when you're exposing internal or proprietary systems — an orders API, a
customer database, an analytics warehouse — to AI agents (Claude Desktop, your own agents, anything
that speaks MCP), and unauthenticated tool access isn't an option.

If you're shipping a single public tool over non-sensitive data, the MCP SDK on its own is simpler.
Come here when access control and an audit trail start to matter.

## License

MIT © Chris Dare. Part of [Argonauts](https://argonauts.chrisdare.me).
