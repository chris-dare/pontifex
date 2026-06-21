# Quickstart

In this tutorial you'll build an MCP server for a payments API. By the end, an AI
agent can call your tools over HTTP, with every request authenticated against a
credential and written to a permanent audit trail.

You'll add one capability at a time, each a small change to the same server. Every
step keeps working as the next one builds on it:

1. A **live server** any MCP client can connect to
2. **Audit**: a persistent log of every tool call
3. **Generated tools**: tools from an existing REST API, no handler code required
4. **Auth**: token-gated access with per-tool scope enforcement
5. **Cache**: a Redis cache to protect your upstream from agent traffic
6. **Postgres**: swap the SQLite floor for production Postgres, no code change

**New to MCP?** Read the [overview](../overview.md) for context on what MCP is and
why Pontifex exists on top of it. To see how a request travels through the stack
end-to-end, see [Request path](../concepts/request-path.md).

---

!!! info "Prerequisites"

    **Python 3.12+**. Postgres, Redis, and an OIDC provider come in only at the step
    that uses them.

## Install

=== "uv"

    ```bash
    uv add pontifex-mcp
    ```

=== "pip"

    ```bash
    pip install pontifex-mcp
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
2026-06-20 13:32:14 [info     ] tool_call    cache_hit=False data_source=unknown delegated_audience=None domain=payments error=None ip_address=127.0.0.1 key_id=anonymous owner_id=anonymous owner_label=Anonymous params={} response_ms=0 tool=get_balance transport=http
```

`owner_id=anonymous` because no auth backend is active yet. `scope="balance:read"`
declares what permission a caller needs. It's advisory here, enforced at step 4.

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
  "timestamp": "2026-06-20T13:45:02.118402+00:00",
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

Tools are named `{domain}_{name}`. The `names` key sets the suffix; the domain prefix
is always added.

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

`ApiKeyAuth()` reads `DATABASE_URL` (the key store) from the environment. The fastest
path is a single SQLite file: no Postgres, no Redis, no Docker. [Step 6](#6-move-to-postgres)
swaps it for Postgres without touching your code.

```bash
export DATABASE_URL=sqlite+aiosqlite:///pontifex.db
```

Create the schema, then mint a key:

```bash
pontifex-mcp db upgrade
pontifex-mcp keys create --owner user_kwame --scopes payments:balance:read --key-plaintext sk_dev_test
```

`--key-plaintext` pins a predictable key for this tutorial. In practice, omit it and
Pontifex generates one (`sk_live_…`), printed once.

Start the server:

```bash
python main.py
```

One difference from step 1: with an auth backend active, the server binds to
`0.0.0.0` instead of `127.0.0.1`. It's ready to accept connections from outside
localhost:

```
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

Every request now needs an `Authorization: Bearer` header. A call without one returns:

```json
{"error_code": "auth_failed", "message": "Missing 'Authorization: Bearer <token>' header.", "status": 401, "retry": false}
```

Pass the key from your MCP client config:

```json
{
  "mcpServers": {
    "payments": {
      "url": "http://localhost:8080/mcp",
      "headers": { "Authorization": "Bearer sk_dev_test" }
    }
  }
}
```

The auth middleware checks the key and its scopes **before your handler runs**. A caller
without `payments:balance:read` gets a `403` (`scope_denied`) and never reaches
`get_balance`. That's the full scope for `scope="balance:read"` on a server named
`"payments"`; the domain is always prepended.

Once a request goes through, query the audit log to confirm the real caller identity:

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

Start Redis (the only new infrastructure so far):

```bash
docker run -d --name redis -p 6379:6379 redis:7
```

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
30
```

A second call within 30 seconds returns the cached value without touching your upstream.

`cache=True` reads `REDIS_URL` from the environment. Omit it entirely and `mcp.cache`
is `None`.

---

## 6. Move to Postgres

The SQLite file got you this far with zero setup. Production wants Postgres: concurrent
writers, real indexes, one key store shared across every replica. The switch is one env
var and the same `db upgrade` command. Your `main.py` doesn't change.

Start Postgres and point `DATABASE_URL` at it:

```bash
docker run -d --name pg -e POSTGRES_PASSWORD=dev -p 5432:5432 postgres:16
export DATABASE_URL=postgresql+asyncpg://postgres:dev@localhost:5432/postgres
```

Run the same command you ran on SQLite. On Postgres it applies the bundled Alembic
migrations instead of creating the tables directly:

```bash
pontifex-mcp db upgrade
```

```
INFO  [alembic.runtime.migration] Running upgrade  -> core_0001, create api_keys
INFO  [alembic.runtime.migration] Running upgrade core_0001 -> core_0002, create audit_log
INFO  [alembic.runtime.migration] Running upgrade core_0002 -> core_0003, create domain_registry
INFO  [alembic.runtime.migration] Running upgrade core_0003 -> core_0004, add delegated_audience to audit_log
Schema is up to date.
```

Re-mint your key against the new store. Set `REDIS_URL` too, so `ApiKeyAuth()` caches
lookups and enforces per-caller rate limits (on the SQLite floor it logged that rate
limiting was off). You already have Redis running from step 5:

```bash
pontifex-mcp keys create --owner user_kwame --scopes payments:balance:read --key-plaintext sk_dev_test
export REDIS_URL=redis://localhost:6379
```

Start the server. Same `main.py`, no code change:

```bash
python main.py
```

Auth, scopes, and the cache behave exactly as they did on SQLite. Only the backend
changed. To move the audit trail onto Postgres too, point `audit=` at the same URL
(step 2).

Managed cloud is the same two URLs: [Neon](https://neon.tech) for Postgres,
[Upstash](https://upstash.com) for Redis. Swap the URLs, keep the commands.

---

## Where to go next

- **Issue API keys, set up OAuth**: [Authenticate callers](../guides/authenticate-callers.md)
- **Expose a full API**: [Connect an existing API](connect-an-api.md)
- **See how a request flows**: [Request path](../concepts/request-path.md)
