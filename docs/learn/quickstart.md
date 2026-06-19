# Quickstart

One server, built up a rung at a time. Start with the bare minimum, then bolt on
each capability — auth, durable audit, caching, generated tools — one keyword at a
time. Every rung is the previous server plus a single line.

!!! info "Prerequisites"

    **Python 3.12+**. That's all you need for Rung 0. Postgres, Redis, and an OIDC
    provider come in only on the rung that uses them.

## Install

=== "uv"

    ```bash
    uv add pontifex-mcp
    ```

=== "pip"

    ```bash
    pip install pontifex-mcp
    ```

## Rung 0 — a server with nothing

No database, no Redis, no auth, no spec. `PontifexMCP` is a drop-in subclass of the
MCP SDK's `FastMCP`: swap the import, keep your tools.

```python
from pontifex_mcp import PontifexMCP

mcp = PontifexMCP("payments")

@mcp.tool(scope="balance:read")
async def get_balance() -> dict:
    return {"available": 421000, "currency": "usd"}

if __name__ == "__main__":
    mcp.run()                       # stdio; mcp.run(http=True) binds 127.0.0.1
```

```bash
python server.py
```

A complete, running server. The caller is anonymous, the `scope=` you declared is
advisory, and every call is audited to stdout:

```json
{"event": "tool_call", "tool": "get_balance", "owner_id": "anonymous", "response_ms": 1}
```

Nothing below changes this tool. Each rung adds **one argument**.

## Rung 1 — bolt on auth

Add an auth backend. Now a Bearer credential is required and the scopes you declared
are enforced.

```python
from pontifex_mcp import PontifexMCP, ApiKeyAuth

mcp = PontifexMCP("payments", auth=ApiKeyAuth())   # ← the only change
```

`ApiKeyAuth()` reads `DATABASE_URL` (the key store) and `REDIS_URL` (the lookup cache)
from the environment, and fails fast if they're missing. Every request now needs a
valid `sk_…` API key; a caller without `payments:balance:read` is rejected *before*
your handler runs. For OAuth 2.1 JWTs from any OIDC provider, use `auth=JwtAuth()`
instead (reads the `AUTH_*` env vars).

```bash
DATABASE_URL=postgresql+asyncpg://… REDIS_URL=redis://… python server.py
```

## Rung 2 — bolt on durable audit

stdout is fine for dev; for a record you can query, point `audit=` at a datastore.

```python
mcp = PontifexMCP("payments", auth=ApiKeyAuth(), audit="audit.db")   # ← added
```

`"audit.db"` is a local SQLite file — zero setup. In production, hand `audit=` a
`postgresql+asyncpg://…` URL; the dialect is detected from the connection string. Each
call now persists a row: who, what, when, data source, latency.

## Rung 3 — bolt on a cache

Give the app a cache and reach it from any tool via `mcp.cache` (keys are namespaced
by the app's domain).

```python
mcp = PontifexMCP("payments", auth=ApiKeyAuth(), audit="audit.db", cache="redis://…")  # ← added

@mcp.tool(scope="balance:read")
async def get_balance() -> dict:
    if mcp.cache and (hit := await mcp.cache.get("balance")):
        return hit
    data = {"available": 421000, "currency": "usd"}
    if mcp.cache:
        await mcp.cache.set("balance", data, ttl_seconds=30)
    return data
```

`cache="redis://…"` (or `cache=True` to read `REDIS_URL`) wires a Redis-backed cache;
omit it and `mcp.cache` is `None`, so the same tool runs uncached in dev.

## Rung 4 — bolt on tools from an OpenAPI spec

Already have an API? Generate governed tools from its spec — each one authenticated,
scope-checked, and audited like a hand-written one. No new handlers.

```python
mcp.add_openapi(
    spec="https://payments.internal/openapi.json",
    base_url="https://payments.internal",
    include=["GET /charges/{id}", "GET /customers/{id}"],   # explicit allowlist
)
```

`include` is a deny-by-default allowlist of operations; mutating verbs additionally
require `allow_mutations=True`. The generated tools carry scopes derived from the
domain and operation, so they slot straight into the same enforcement and audit as
the rest of the server.

## The finished server

```python
from pontifex_mcp import PontifexMCP, ApiKeyAuth

mcp = PontifexMCP(
    "payments",
    auth=ApiKeyAuth(),        # Rung 1 — enforce auth + scopes
    audit="audit.db",         # Rung 2 — durable audit (a Postgres URL in prod)
    cache="redis://…",        # Rung 3 — Redis cache via mcp.cache
)

@mcp.tool(scope="balance:read")
async def get_balance() -> dict: ...

mcp.add_openapi(                # Rung 4 — generated, governed tools
    spec="https://payments.internal/openapi.json",
    base_url="https://payments.internal",
    include=["GET /charges/{id}"],
)

if __name__ == "__main__":
    mcp.run(http=True)
```

Every rung was additive: the tool from Rung 0 never changed, and each capability is one
keyword you can turn on from code or from the environment — so laptop → production is
config, not a rewrite.

## Next steps

- **Let real callers in.** Issue API keys and wire OAuth in
  [Authenticate callers](../guides/authenticate-callers.md).
- **Onboard a whole API.** [Connect an API](connect-an-api.md) goes deeper on the
  OpenAPI path, including per-user OAuth token exchange to the downstream.
- **Understand what just happened.** [How a request flows](../concepts/request-path.md).
