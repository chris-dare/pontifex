# Quickstart

Start with a plain MCP server. Add audit logging, generated tools, auth, and cache as
you go. Each step adds one parameter.

!!! info "Prerequisites"

    Python 3.12+.

## Install

=== "uv"

    ```bash
    uv add pontifex-mcp
    ```

=== "pip"

    ```bash
    pip install pontifex-mcp
    ```

## 1. A plain server

`PontifexMCP` is a subclass of the MCP SDK's `FastMCP`. Everything FastMCP can do,
Pontifex can do — auth, audit, and cache are opt-in on top.

```python title="main.py"
from pontifex_mcp import PontifexMCP

mcp = PontifexMCP("payments")

@mcp.tool()
async def get_balance() -> dict:
    return {"available": 421000, "currency": "usd"}

if __name__ == "__main__":
    mcp.run()
```

```bash
python main.py
```

This runs over stdio. Audit is already on; every call logs to stdout:

```
{"event": "tool_call", "tool": "get_balance", "owner_id": "anonymous", "response_ms": 1}
```

### Connect a client

Most MCP clients (Claude Desktop, Cursor, Zed, VS Code with Copilot) read a JSON
config of this shape:

```json
{
  "mcpServers": {
    "payments": {
      "command": "python",
      "args": ["/path/to/main.py"]
    }
  }
}
```

To inspect tools interactively during development, use
[MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```bash
npx @modelcontextprotocol/inspector python main.py
```

---

## 2. Persist audit logs

The default sink is stdout. Pass a path or URL to write every call to durable storage.

```python title="main.py"
from pontifex_mcp import PontifexMCP

mcp = PontifexMCP("payments", audit="audit.db")

@mcp.tool()
async def get_balance() -> dict:
    return {"available": 421000, "currency": "usd"}

if __name__ == "__main__":
    mcp.run()
```

`"audit.db"` creates a local SQLite file with no extra setup. In production, pass a
`postgresql+asyncpg://…` URL. Each row records the caller, tool name, inputs, response
time, and source IP.

---

## 3. Generate tools from an OpenAPI spec

If you already have an API, Pontifex can turn its operations into governed MCP tools
without writing handlers by hand.

To try this locally, save the file below and start it:

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

Now point Pontifex at its spec:

```python title="main.py"
from pontifex_mcp import PontifexMCP

mcp = PontifexMCP("payments", audit="audit.db")

mcp.add_openapi(
    spec="http://localhost:9000/openapi.json",
    base_url="http://localhost:9000",
    include=["GET /charges/{charge_id}"],
    names={"GET /charges/{charge_id}": "get_charge"},
)

if __name__ == "__main__":
    mcp.run()
```

```bash
python main.py
```

`include` is an allowlist — nothing else is exposed. `names` sets the tool name the
client sees. Mutating verbs are blocked by default; pass `allow_mutations=True` to
permit them.

---

## 4. Add auth

Auth applies when you serve HTTP. The stdio runner stays local and anonymous.

```python title="main.py"
from pontifex_mcp import PontifexMCP, ApiKeyAuth

mcp = PontifexMCP("payments", auth=ApiKeyAuth(), audit="audit.db")

@mcp.tool(scope="balance:read")
async def get_balance() -> dict:
    return {"available": 421000, "currency": "usd"}

if __name__ == "__main__":
    mcp.run(http=True)
```

```bash
DATABASE_URL=postgresql+asyncpg://… REDIS_URL=redis://… python main.py
```

`ApiKeyAuth()` reads both env vars. A caller needs a valid `sk_…` token, and its scopes
must cover `balance:read` before the handler runs.

For OAuth 2.1 JWTs, use `auth=JwtAuth()` and set the `AUTH_*` variables for your
provider. See [Authenticate callers](../guides/authenticate-callers.md) for key
issuance and OAuth setup.

### Connect an HTTP client

**Claude Desktop** — replace `command`/`args` with `url`:

```json
{
  "mcpServers": {
    "payments": {
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

**MCP Python SDK:**

```python
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession
import asyncio

async def main():
    async with streamablehttp_client("http://localhost:8080/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_balance", {})
            print(result)

asyncio.run(main())
```

---

## 5. Add a cache

Give the server a cache and access it from handlers via `mcp.cache`. Keys are
namespaced by the app name automatically.

```python title="main.py"
from pontifex_mcp import PontifexMCP, ApiKeyAuth

mcp = PontifexMCP(
    "payments",
    auth=ApiKeyAuth(),
    audit="audit.db",
    cache="redis://localhost:6379",
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

`cache=True` reads `REDIS_URL` from the environment. Leave it out and `mcp.cache` is
`None`.

---

## Where to go next

- **Issue API keys, set up OAuth** — [Authenticate callers](../guides/authenticate-callers.md)
- **Expose a full API** — [Connect an existing API](connect-an-api.md)
- **See how a request flows** — [Request path](../concepts/request-path.md)
