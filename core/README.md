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
- **Drop-in connectors** — generate governed tools from an OpenAPI spec (code or config), with optional
  per-user OAuth token exchange (RFC 8693) to the downstream.
- **Built on the MCP SDK** — keep its tools, protocol, and transports; add the controls a production
  server needs.

Asymmetric-only JWT validation, generic auth errors, and no token claim can escalate a caller.

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

## Connect an existing API (no hand-written tools)

If the system already has an OpenAPI spec, generate governed tools from it — each one wrapped in the
same `tool_runtime` (scope check, audit, error envelope). Operations are opt-in via an explicit
`include` allowlist.

```python
from pontifex_mcp import register_openapi_tools, BearerFromEnv

register_openapi_tools(
    mcp,
    spec="https://api.internal/openapi.json",   # URL, path, or dict; JSON or YAML
    domain="orders",
    base_url="https://api.internal",
    audit=audit,
    auth=BearerFromEnv("ORDERS_API_TOKEN"),     # service credential to the backend
    include=["GET /orders", "GET /orders/{id}"],
)
```

Or onboard with **config alone** — point `PONTIFEX_CONNECTORS_CONFIG` at a connectors YAML file and the
server registers the tools at startup, no domain code.

For a backend that enforces its **own per-user permissions**, swap the service credential for OAuth
token exchange ([RFC 8693](https://www.rfc-editor.org/rfc/rfc8693)) — Pontifex exchanges the caller's
token for one scoped to the downstream, on their behalf (the inbound token is never forwarded):

```python
from pontifex_mcp import TokenExchange

auth = TokenExchange(
    token_endpoint="https://idp.example.com/oauth/token",
    audience="https://api.internal",
    client_id_env="PONTIFEX_OAUTH_CLIENT_ID",
    client_secret_env="PONTIFEX_OAUTH_CLIENT_SECRET",
)
```

Exchanged tokens are cached in process memory by default, or in Redis (`PONTIFEX_TOKEN_CACHE=redis`,
encrypted at rest). See the [Connectors guide](https://chris-dare.github.io/pontifex/connectors/) for
the full configuration.

## Who it's for

Reach for `pontifex-mcp` when you're exposing internal or proprietary systems — an orders API, a
customer database, an analytics warehouse — to AI agents (Claude Desktop, your own agents, anything
that speaks MCP), and unauthenticated tool access isn't an option.

If you're shipping a single public tool over non-sensitive data, the MCP SDK on its own is simpler.
Come here when access control and an audit trail start to matter.

## License

MIT © Chris Dare. Part of [Argonauts](https://argonauts.chrisdare.me).
