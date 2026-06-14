# Getting started

!!! info "Prerequisites"

    You'll need **Python 3.12+**, a **Postgres** database (API keys + audit log), and **Redis** (rate
    limiting + cache). For local development, `docker compose` is the quickest way to get both.

## Install

=== "pip"

    ```bash
    pip install pontifex-mcp
    ```

=== "uv"

    ```bash
    uv add pontifex-mcp
    ```

## Build a server

A domain is three things: a **settings class**, your **tools** (wrapped with `tool_runtime`), and a
call to **`create_mcp_http_app`**.

1.  **Define your settings.** Subclass `CoreSettings` and add anything your domain needs.
    Infrastructure settings (`DATABASE_URL`, `REDIS_URL`, the `AUTH_*` vars) are inherited.

    ```python
    from pontifex_mcp import CoreSettings

    class OrdersSettings(CoreSettings):
        orders_api_base: str = "https://orders.internal.example.com"
    ```

2.  **Write a tool.** Register tools on the MCP server and wrap each handler with `tool_runtime` — it
    applies the scope check and the audit row.

    ```python
    from typing import Any
    from mcp.server.fastmcp import Context, FastMCP
    from pontifex_mcp import AuditWriter, tool_runtime

    def register_tools(mcp: FastMCP, audit: AuditWriter) -> None:
        @mcp.tool(name="orders_get_status", description="Look up the status of an order.")
        @tool_runtime(
            domain="orders",
            tool_name="orders_get_status",
            resource="order",   # scope checked: orders:order:read
            action="read",
            audit=audit,
        )
        async def get_order_status(order_id: str, ctx: Context | None = None) -> dict[str, Any]:
            return {"source": "orders-api", "cache_hit": False, "order_id": order_id, "status": "shipped"}
    ```

3.  **Create the app.**

    ```python
    from pontifex_mcp import create_mcp_http_app

    async def health() -> dict[str, Any]:
        return {"status": "ok"}

    app = create_mcp_http_app("orders", OrdersSettings(), register_tools, health)
    ```

4.  **Run it.**

    ```bash
    DATABASE_URL=postgresql+asyncpg://... REDIS_URL=redis://... \
      uv run uvicorn your_module:app --port 8080
    ```

    The MCP endpoint is served at `/mcp`, with health checks at `/health/live` and `/health/ready`.

## Already have an OpenAPI spec?

Skip the hand-written tools. Point a connectors config at the spec and the server generates one
governed tool per allowlisted operation at startup — same scope check and audit as above, no domain
code:

```yaml
# connectors.yaml — then set PONTIFEX_CONNECTORS_CONFIG=connectors.yaml
connectors:
  - domain: orders
    spec: https://api.internal/openapi.json
    base_url: https://api.internal
    auth:
      type: bearer_env        # or token_exchange for per-user downstream auth
      env_var: ORDERS_API_TOKEN
    include:
      - GET /orders
      - GET /orders/{order_id}
```

See the [Connectors guide](connectors.md) for token exchange, the cache, and the full reference.

## Issue an API key

Tools require authentication. For scripts and CI, mint an `sk_…` API key scoped to what the caller may
do — for interactive clients (Claude Desktop, your own agents), wire an OAuth provider instead.

!!! tip

    Scopes use `domain:resource:action` and support wildcards — e.g. `orders:order:read` for one tool,
    or `orders:*:read` for read-only access across the whole domain.
