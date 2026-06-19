# Quickstart

A governed MCP server running locally in a couple of minutes — then the same server,
authenticated and audited, for production.

This is a tutorial. Follow it top to bottom. For what comes after — wiring OAuth,
onboarding an existing API, deploying — see the [Guides](../guides/authenticate-callers.md).

!!! info "Prerequisites"

    **Python 3.12+**. That's it for the floor below — no database, no Redis, no auth.
    You add those only when you turn on enforcement (the [last section](#graduate-to-enterprise)).

## Install

=== "uv"

    ```bash
    uv add pontifex-mcp
    ```

=== "pip"

    ```bash
    pip install pontifex-mcp
    ```

## The floor: a server in a few lines

`PontifexMCP` is a drop-in subclass of the MCP SDK's `FastMCP`. If you've used FastMCP,
this is the same API — swap the import, keep your tools.

```python
from pontifex_mcp import PontifexMCP

mcp = PontifexMCP("payments")

@mcp.tool(scope="balance:read")
async def get_balance() -> dict:
    return {"available": 421000, "currency": "usd"}

if __name__ == "__main__":
    mcp.run()
```

```bash
python server.py        # runs over stdio
```

That's a complete, running server — **no database, no Redis, no auth**. The caller is
anonymous, scopes are advisory, and every tool call is audited to stdout:

```json
{"event": "tool_call", "tool": "get_balance", "owner_id": "anonymous", "response_ms": 1}
```

The `scope="balance:read"` you declared is recorded now and **enforced the moment you add
an auth backend** — you don't rewrite the tool to graduate.

## Add a high-stakes tool

The same `scope=` pattern governs mutations. Strip the verb from the tool to get the
resource; the verb is the action. A refund is `refunds:execute`:

```python
@mcp.tool(scope="refunds:execute")
async def issue_refund(charge_id: str, amount: int, idempotency_key: str) -> dict:
    return {"refunded": amount, "charge_id": charge_id, "status": "succeeded"}
```

When enforcement is on, only a caller holding `payments:refunds:execute` (or
`payments:*:execute`, `payments:*:*`) can call it — and the audit row records *who*
refunded *what*, *when*. That record is the whole point of putting an MCP server in front
of money.

## Serve over HTTP

```python
mcp.run(http=True)      # Streamable HTTP at /mcp
```

With no auth backend, HTTP binds **`127.0.0.1`** — open, but not reachable from the
network. Exposing an unauthenticated server publicly is an explicit choice:

```python
mcp.run(http=True, auth="none")   # binds 0.0.0.0 — logs a loud warning
```

## Graduate to enterprise

Turn on enforcement by adding backends — the tools above don't change:

```python
from pontifex_mcp import PontifexMCP, ApiKeyAuth

mcp = PontifexMCP(
    "payments",
    auth=ApiKeyAuth(),     # Bearer required; scopes enforced. Reads DATABASE_URL + REDIS_URL
    audit="audit.db",      # durable audit — SQLite here; a Postgres URL in production
)
```

Now:

- every request needs a valid `sk_…` API key (or an OAuth 2.1 JWT, via `JwtAuth()`);
- `get_balance` and `issue_refund` enforce their scopes — a caller without
  `payments:refunds:execute` is rejected *before* your handler runs;
- audit rows persist to `audit.db` (a SQLite file for local dev) — point `audit=` at a
  `postgresql+asyncpg://…` URL for production, no code change;
- HTTP binds `0.0.0.0` normally, because the server is no longer unauthenticated.

The same switches flip from the environment, so laptop → production is config, not code:
set `DATABASE_URL`, `REDIS_URL`, and the `AUTH_*` group and deploy the identical server.

## Recap

You just:

- stood up a governed MCP server with **no infrastructure**;
- declared `scope=` on read and execute tools, advisory until you opt in;
- served it over stdio and localhost HTTP;
- graduated to enforced auth and durable audit by adding two keyword arguments.

## Next steps

- **Already have an OpenAPI spec?** Skip hand-written tools entirely:
  [connect an API](connect-an-api.md).
- **Let real callers in.** Issue API keys and wire OAuth in
  [Authenticate callers](../guides/authenticate-callers.md).
- **Understand what just happened.** [How a request flows](../concepts/request-path.md).
