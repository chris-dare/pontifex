# Quickstart

A governed MCP server — authenticated and audited — running locally in a few minutes.

This is a tutorial. Follow it top to bottom and you'll have a working server. For the
problems you'll solve *after* that — wiring OAuth, onboarding an existing API,
deploying — see the [Guides](../guides/authenticate-callers.md).

!!! info "Prerequisites"

    **Python 3.12+**, a **Postgres** database (API keys + audit log), and **Redis**
    (rate limiting + cache). Locally, `docker compose` is the quickest way to get both.

## Install

=== "uv"

    ```bash
    uv add pontifex-mcp
    ```

=== "pip"

    ```bash
    pip install pontifex-mcp
    ```

## A server is three pieces

- a **settings** class
- your **tools**, each wrapped with `tool_runtime`
- a call to **`create_mcp_http_app`**

That's it. The runtime handles auth, scope checks, audit, and errors. Let's build one.

## Step 1: define your settings

Subclass `CoreSettings`. Add whatever your domain needs.

```python
from pontifex_mcp import CoreSettings

class OrdersSettings(CoreSettings):
    orders_api_base: str = "https://orders.internal.example.com"
```

The infrastructure settings — `DATABASE_URL`, `REDIS_URL`, the `AUTH_*` group — are
inherited. You don't redeclare them.

## Step 2: write a tool

Register the tool on the MCP server. Wrap the handler with `tool_runtime`.

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

The decorator declares the scope this call requires. It writes the audit row. Your
handler just returns plain data.

!!! tip

    No auth code in the handler. No logging code. `tool_runtime` does both, the same
    way, for every tool. That consistency is the point — see
    [How a request flows](../concepts/request-path.md).

## Step 3: create the app

```python
from pontifex_mcp import create_mcp_http_app

async def health() -> dict[str, Any]:
    return {"status": "ok"}

app = create_mcp_http_app("orders", OrdersSettings(), register_tools, health)
```

## Step 4: run it

```bash
DATABASE_URL=postgresql+asyncpg://... REDIS_URL=redis://... \
  uv run uvicorn your_module:app --port 8080
```

The MCP endpoint is at `/mcp`. Health checks are at `/health/live` and `/health/ready`.

## Check it

That's a complete server.

Every call to `orders_get_status` is now authenticated, checked for the
`orders:order:read` scope, and written to the audit log. You wrote none of that.

A caller without the scope is rejected before your handler runs. A caller with it gets
the data — and leaves a row behind saying who they were and what they touched.

## Recap

You just:

- subclassed `CoreSettings` for your domain
- wrote a tool and wrapped it with `tool_runtime`
- built the app with `create_mcp_http_app`
- ran it with any ASGI server

## Next steps

- **Already have an OpenAPI spec?** Skip hand-written tools entirely —
  [connect an API](connect-an-api.md).
- **Let real callers in.** Issue API keys and wire OAuth in
  [Authenticate callers](../guides/authenticate-callers.md).
- **Understand what just happened.** [How a request flows](../concepts/request-path.md).
