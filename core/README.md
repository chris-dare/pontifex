# pontifex-mcp

**Connect your systems to AI agents — safely.**

The [MCP](https://modelcontextprotocol.io) SDK gives you a server. It doesn't give you the
things that keep that server from becoming a liability the moment it touches real data:
authentication, per-caller access control, rate limits, and a record of who called what.
`pontifex-mcp` is that layer — the **security, access-control, and governance layer for MCP
servers** — and there's already a live server running on it.

> **Live example:** the GSE market-data server — authenticated, scoped, rate-limited —
> runs on `pontifex-mcp`, serving real Ghana Stock Exchange data. See [`domains/gse`](../domains/gse).

> **Status:** `0.x`, building in public. The security model is solid; the public API
> (everything exported from `pontifex_mcp`) is still settling — expect occasional breaking
> changes before `1.0`.

## Who it's for

Reach for `pontifex-mcp` when you're exposing **internal or proprietary systems** — an orders
API, a customer database, an analytics warehouse — to AI agents (Claude Desktop, your own
agents, anything that speaks MCP), and unauthenticated tool access isn't an option.

If you're shipping a single public tool over non-sensitive data, the bare MCP SDK is simpler.
Come here when access control and an audit trail start to matter.

## What you get

Grouped into four areas. The list grows with the roadmap and what teams ask for — new
capabilities slot into these buckets.

**Identity & access**
- Two auth paths, one identity: `sk_…` API keys (scripts/CI) **and** OAuth 2.1 JWTs (Auth0,
  Entra, Clerk, Keycloak — any OIDC provider) for interactive clients. Both resolve to a single
  `CallerIdentity`.
- Per-caller scope enforcement — `domain:resource:action`, checked before every tool call.
  Least-privilege by default; a caller cannot widen their own scope.

**Governance & audit**
- Every call recorded: who, what, when, which data source, cache hit, latency — the trail you
  need for compliance and incident response.
- Standards-based discovery (RFC 9728 protected-resource metadata + `WWW-Authenticate`), so MCP
  clients bootstrap OAuth on their own — no out-of-band config.

**Reliability**
- Per-caller, Redis-backed rate limiting.
- Resilient data access: a `DataAdapter` protocol with failover and circuit breaking across sources.

**Operability**
- Logfire / OpenTelemetry tracing and metrics wired in.

> **Security is deliberate, not incidental.** Asymmetric-only JWT validation; generic auth errors
> (no validation oracle); no token claim can raise a caller's own rate limit or scope; secrets only
> via env vars. The properties are verifiable in the source, not just asserted here.

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

Auth, scope checks, rate limiting, the audit row, and the structured error envelope are all
applied by `tool_runtime` and the server's middleware — your handler just returns data.

### Configuration

Infrastructure settings read from bare, unprefixed env vars:

```
DATABASE_URL, REDIS_URL          # required (the app fails fast if unset)
AUTH_JWKS_URL, AUTH_ISSUER, AUTH_AUDIENCE, AUTH_SCOPES_CLAIM   # enable the OAuth/JWT path
PUBLIC_BASE_URL                  # canonical URL advertised in OAuth discovery
```

Domain-specific settings on your subclass read with your domain's `env_prefix`.

## Example

The [GSE reference server](../domains/gse) is a complete, deployed example — multiple tools,
multiple data adapters with failover, OAuth + API-key auth, on Fly.io.

## License

MIT © Chris Dare. Part of [Argonauts](https://argonauts.chrisdare.me).
