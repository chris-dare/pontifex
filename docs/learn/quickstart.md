# Quickstart

In this tutorial you'll build an MCP server for a payments API. By the end, an AI
agent can call your tools over HTTP, with every request authenticated against a
credential and written to a permanent audit trail.

You'll add one capability at a time. Each step is the previous file plus one
parameter. Nothing from a previous step breaks:

1. A **live server** any MCP client can connect to
2. **Audit**: A persistent audit log of every tool call
3. **Autogenerate Tools**: Tools generated from an existing REST API, no handler code required
4. **Auth**: Token-gated access with per-tool scope enforcement
5. **Cache**: A Redis cache to protect your upstream from agent traffic

**New to MCP?** Read the [overview](../overview.md) for context on what MCP is and
why Pontifex exists on top of it. To see how a request travels through the stack
end-to-end, see [Request path](../concepts/request-path.md).

---

!!! info "Prerequisites"

```
**Python 3.12+**. Postgres, Redis, and an OIDC provider come in only at the step
that uses them.
```

## Install

=== "uv"

```
```bash
uv add pontifex-mcp
```

```

=== "pip"

```

```bash
pip install pontifex-mcp
```

```

---

## 1. A working server

```python title="main.py"
from pontifex_mcp import PontifexMCP

mcp = PontifexMCP("payments")

@mcp.tool(scope="balance:read")
async def get_balance() -> dict:
    return {"available": 421000, "currency": "usd"}

if __name__ == "__main__":
    mcp.run(http=True)
```

```bash
python main.py
```

You'll see:

```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8080 (Press CTRL+C to quit)
```

Port 8080 is open. Any MCP-compatible client can connect.

Point [MCP Inspector](https://github.com/modelcontextprotocol/inspector) at it and
`get_balance` appears under Tools. Call it and you get the dict back:

```bash
npx @modelcontextprotocol/inspector http://localhost:8080/mcp
```

To wire it into Claude Desktop, Cursor, Zed, or any other MCP client:

```json
{
  "mcpServers": {
    "payments": { "url": "http://localhost:8080/mcp" }
  }
}
```

Audit logging is already active. Every call writes a structured line to stdout:

```
2026-06-20 13:32:14 [info] tool_call  domain=payments tool=get_balance owner_id=anonymous response_ms=0 ip_address=127.0.0.1
```

`owner_id=anonymous` because no auth backend is active yet. `scope="balance:read"`
declares what permission a caller needs — it's advisory here, enforced at step 4.

Scopes use `resource:action`. Pontifex prepends the server name as the domain, so
`"balance:read"` on a server named `"payments"` becomes `payments:balance:read`. When
you issue API keys, use that full three-part form.

---

## 2. Persist the audit trail

stdout is fine for development. Pass a path and Pontifex writes every call to durable
storage:

```python title="main.py"
mcp = PontifexMCP("payments", audit="audit.db")  # ← added
```

`"audit.db"` creates a local SQLite file. No migrations, no setup. Start the server,
call `get_balance`, then query the file to verify the record landed:

```bash
sqlite3 audit.db "SELECT timestamp, tool_name, owner_id, response_ms FROM audit_log"
```

```
2026-06-20 13:41:03.760035|get_balance|anonymous|0
```

Each row records the caller identity, tool name, inputs, response time, and source IP.

In production, swap the string for a Postgres URL:

```python
mcp = PontifexMCP("payments", audit="postgresql+asyncpg://user:pass@host/db")
```

Pontifex detects the dialect and creates the schema.

---

## 3. Expose your existing API

If you already have a REST API, don't rewrite it. Point Pontifex at its OpenAPI spec
and it wraps the listed operations as governed tools.

To follow along, save this and start it:

```python title="upstream.py"
from fastapi import FastAPI

app = FastAPI(title="Payments API")

@app.get("/charges/{charge_id}")
async def get_charge(charge_id: str) -> dict:
    return {"id": charge_id, "amount": 500, "currency": "usd", "status": "succeeded"}
```

```bash
uvicorn upstream:app --port 9000
```

Now point your MCP server at its spec:

```python title="main.py"
from pontifex_mcp import PontifexMCP

mcp = PontifexMCP("payments", audit="audit.db")

mcp.add_openapi(  # ← added
    spec="http://localhost:9000/openapi.json",
    base_url="http://localhost:9000",
    include=["GET /charges/{charge_id}"],
    names={"GET /charges/{charge_id}": "get_charge"},
)

if __name__ == "__main__":
    mcp.run(http=True)
```

```bash
python main.py
```

The startup output includes the spec fetch before the server comes up:

```
INFO:     HTTP Request: GET http://localhost:9000/openapi.json "HTTP/1.1 200 OK"
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8080 (Press CTRL+C to quit)
```

Open MCP Inspector and you'll see `payments_get_charge` under Tools. Call it and the
response wraps the upstream JSON in a governed envelope:

```json
{
  "source": "openapi:payments",
  "cache_hit": false,
  "status_code": 200,
  "data": {
    "id": "ch_123",
    "amount": 500,
    "currency": "usd",
    "status": "succeeded"
  }
}
```

Tools are named `{domain}_{name}` — the `names` key sets the suffix, and the domain
prefix is always added.

`include` is a strict allowlist. List the operations you want to expose; everything
else stays hidden. If your API has fifty endpoints and you list two, clients see two.

!!! info "Mutating verbs"
    `POST`, `PUT`, `PATCH`, and `DELETE` are blocked by default even if listed in
    `include`. Pass `allow_mutations=True` to the `add_openapi()` call to permit them.

---

## 4. Gate access

Add `auth=` and the server goes from open to credentialed. The `scope=` you declared
on each tool, advisory until now, is enforced.

```python title="main.py"
from pontifex_mcp import PontifexMCP, ApiKeyAuth  # ← added

mcp = PontifexMCP("payments", auth=ApiKeyAuth(), audit="audit.db")  # auth= added

@mcp.tool(scope="balance:read")
async def get_balance() -> dict:
    return {"available": 421000, "currency": "usd"}

if __name__ == "__main__":
    mcp.run(http=True)
```

`ApiKeyAuth()` reads `DATABASE_URL` (key store) and `REDIS_URL` (lookup cache) from
the environment.

!!! tip "Quickest way to get Postgres and Redis running"

```
=== "Docker / Podman"

    ```bash
    docker run -d --name pg -e POSTGRES_PASSWORD=dev -p 5432:5432 postgres:16
    docker run -d --name redis -p 6379:6379 redis:7
    ```

    ```bash
    export DATABASE_URL=postgresql+asyncpg://postgres:dev@localhost:5432/postgres
    export REDIS_URL=redis://localhost:6379
    ```

    Create the schema and a test API key (run this once):

    ```python title="setup_dev_key.py"
    import asyncio, hashlib
    from pontifex_mcp.models.db import Base, ApiKeyModel
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy import text
    import os

    DB = os.environ["DATABASE_URL"]
    KEY = "sk_dev_test"

    async def setup():
        engine = create_async_engine(DB)
        async with engine.begin() as conn:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine) as session:
            session.add(ApiKeyModel(
                key_id="key_dev",
                key_hash=hashlib.sha256(KEY.encode()).hexdigest(),
                owner_id="user_kwame",
                owner_label="Kwame Mensah",
                scopes=["payments:balance:read"],
                rate_limit_rpm=60,
                is_active=True,
            ))
            await session.commit()
        print(f"Key created: {KEY}")
        await engine.dispose()

    asyncio.run(setup())
    ```

    ```bash
    python setup_dev_key.py
    ```

=== "Managed cloud"

    - **Postgres** — [Neon](https://neon.tech) has a free tier. Copy the
      `postgresql://…` connection string and replace `postgresql://` with
      `postgresql+asyncpg://`.
    - **Redis** — [Upstash](https://upstash.com) or [Redis Cloud](https://redis.com/try-free/)
      both have free tiers. Use the `redis://` or `rediss://` URL directly.

    Run `setup_dev_key.py` from the Docker tab above, substituting your managed URLs.
```

```bash
DATABASE_URL=postgresql+asyncpg://… REDIS_URL=redis://… python main.py
```

One difference from step 1: with an auth backend active, the server binds to
`0.0.0.0` instead of `127.0.0.1` — it's ready to accept connections from outside
localhost:

```
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

Every request now needs `Authorization: Bearer sk_dev_test`. A call without a token returns:

```json
{"error_code": "auth_failed", "message": "Missing 'Authorization: Bearer <token>' header.", "status": 401}
```

The auth middleware checks the key and its scopes **before your handler runs**. A caller
without `payments:balance:read` gets `401` and never reaches `get_balance`. That's the
full scope for `scope="balance:read"` on a server named `"payments"` — the domain is
always prepended.

Once you have a valid API key, query the audit log to confirm the real caller identity:

```bash
sqlite3 audit.db "SELECT timestamp, tool_name, owner_id, response_ms FROM audit_log"
```

```
2026-06-20 13:50:36.796704|get_balance|user_kwame|0
```

`owner_id` now shows the key holder instead of `anonymous`.

!!! tip "JWTs / OAuth 2.1"
    Swap `ApiKeyAuth()` for `JwtAuth()` and set the `AUTH_*` env vars to accept signed
    tokens from Auth0, Entra ID, Keycloak, or any OIDC provider. See
    [Authenticate callers](../guides/authenticate-callers.md).

---

## 5. Cache upstream calls

Give the server a Redis cache and reach it from any handler via `mcp.cache`. Keys are
namespaced by server name. Two servers sharing a Redis instance can't collide.

```python title="main.py"
from pontifex_mcp import PontifexMCP, ApiKeyAuth

mcp = PontifexMCP(
    "payments",
    auth=ApiKeyAuth(),
    audit="audit.db",
    cache="redis://localhost:6379",  # ← added
)

@mcp.tool(scope="balance:read")
async def get_balance() -> dict:
    if mcp.cache and (hit := await mcp.cache.get("balance")):
        return hit

    data = {"available": 421000, "currency": "usd"}

    if mcp.cache:
        await mcp.cache.set("balance", data, ttl_seconds=30)

    return data

if __name__ == "__main__":
    mcp.run(http=True)
```

The `if mcp.cache` guards mean the same handler works whether or not Redis is configured.
No code changes between dev and prod.

Call `get_balance` once, then verify the value landed in Redis:

```bash
docker exec redis redis-cli GET payments:balance
```

```
{"available": 421000, "currency": "usd"}
```

Check the TTL to confirm expiry is set:

```bash
docker exec redis redis-cli TTL payments:balance
```

```
(integer) 29
```

A second call within 30 seconds returns the cached value without touching your upstream.

`cache=True` reads `REDIS_URL` from the environment. Omit it entirely and `mcp.cache`
is `None`.

---

## Where to go next

- **Issue API keys, set up OAuth** — [Authenticate callers](../guides/authenticate-callers.md)
- **Expose a full API** — [Connect an existing API](connect-an-api.md)
- **See how a request flows** — [Request path](../concepts/request-path.md)

