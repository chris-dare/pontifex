---
name: pontifex-mcp
description: "Use when building or modifying an MCP server with the pontifex-mcp Python library - the PontifexMCP facade, governed @tool scopes, API-key or JWT auth, audit logging, Redis caching, generating tools from an OpenAPI spec, and the `pontifex-mcp` CLI for migrations and API keys. Triggers on: pontifex-mcp, PontifexMCP, ApiKeyAuth, JwtAuth, mcp.tool(scope=...), pontifex-mcp keys, pontifex-mcp db upgrade."
license: Apache-2.0
metadata:
  author: Chris Dare
  version: '0.5.0'
  openclaw:
    emoji: "\U0001F510"
    homepage: https://github.com/chris-dare/pontifex
---

# pontifex-mcp

Build enterprise-grade MCP servers in Python: authentication, `namespace:resource:action`
scopes, audit logging, caching, and resilient adapters, layered on the official MCP SDK.

`PontifexMCP` is a drop-in subclass of the SDK's `FastMCP`. The enterprise features are
**opt-in and default to zero extra infrastructure** — a bare server needs no database,
Redis, or auth. You add capabilities one keyword argument at a time, and the same code
runs from a laptop (SQLite) to production (Postgres + Redis) with only configuration
changes.

## When to use

- Standing up a new MCP server that needs auth, scopes, or an audit trail
- Adding governed tools, or wrapping an existing REST API as MCP tools
- Wiring API-key or OAuth 2.1 / JWT authentication and per-tool scope enforcement
- Provisioning API keys or running schema migrations via the `pontifex-mcp` CLI

## Install

```bash
uv add pontifex-mcp     # or: pip install pontifex-mcp
```

Requires Python 3.12+. Pydantic v2, async throughout.

## Mental model

- `PontifexMCP("payments")` — the constructor name **is the namespace**. Scopes and cache
  keys are namespaced by it.
- `auth=` enables enforcement, `audit=` sets where calls are logged, `cache=` wires Redis.
  Omit them and you get an open, stdout-audited, uncached server.
- Infra (DB, Redis, JWKS, port, host) comes from `CoreSettings`, which reads
  environment variables by default, so laptop → prod is usually a config change,
  not a code change.

## Build a server

```python title="main.py"
from pontifex_mcp import PontifexMCP

mcp = PontifexMCP("payments")

@mcp.tool(scope="balance:read")
async def get_balance() -> dict:
    return {"available": 421000, "currency": "usd"}

if __name__ == "__main__":
    mcp.run(http=True)   # streamable-http on :8080 (PORT env to change)
```

## Tools and scopes

- **Always call the decorator with parentheses**: `@mcp.tool()` or `@mcp.tool(scope=...)`.
  Bare `@mcp.tool` raises a `TypeError`.
- Tool handlers are typically `async def` and return JSON-serializable data (dicts, Pydantic models).
- `scope="resource:action"` — the server's namespace is prepended, so
  `"balance:read"` on a `"payments"` server enforces `payments:balance:read`. Pass the full
  `"namespace:resource:action"` to target another namespace.
- A tool with **no** `scope=` is unenforced (advisory).
- For the `PontifexMCP.run()` facade, scopes are advisory over **stdio** (the local caller
  is anonymous). Enforcement happens over HTTP once an `auth=` backend is set.

## Running

- `mcp.run()` → stdio (local; anonymous caller).
- `mcp.run(http=True)` → streamable-http.
- **No auth backend** → HTTP binds `127.0.0.1` (localhost only). Pass `mcp.run(http=True,
  auth="none")` to bind `0.0.0.0` unauthenticated (logs a loud warning).
- **With an auth backend** → binds `0.0.0.0`, every request needs `Authorization: Bearer`.

## Authentication

```python
from pontifex_mcp import PontifexMCP, ApiKeyAuth

mcp = PontifexMCP("payments", auth=ApiKeyAuth())
```

- `ApiKeyAuth()` reads `DATABASE_URL` (the key store) and optional `REDIS_URL`. With Redis,
  key lookups are cached and per-caller rate limiting is enforced; without it, the store is
  read directly and rate limiting is off (logged at startup). It fails fast if
  `DATABASE_URL` is unset.
- `JwtAuth()` validates OAuth 2.1 / JWT access tokens from any OIDC provider (Auth0, Entra,
  Keycloak, …), reading `AUTH_*` env vars (including `AUTH_JWKS_URL`). See the
  "Authenticate callers" guide for the full variable set.
- Both resolve authenticated callers to the same `CallerIdentity` type and flow
  through the same scope check.

**SQLite floor → Postgres is a config change, not a code change.** Start local:

```bash
export DATABASE_URL=sqlite+aiosqlite:///pontifex.db
```

Move to production by pointing the same variable at Postgres
(`postgresql+asyncpg://user:pass@host/db`) and re-running `db upgrade`. `main.py` is
untouched.

## The `pontifex-mcp` CLI

```bash
# Create or update the schema. SQLite → create_all; Postgres → bundled Alembic migrations.
pontifex-mcp db upgrade

# Mint a key. Scopes MUST be the full 3-part namespace:resource:action form.
pontifex-mcp keys create --owner user_kwame --scopes "payments:balance:read" --rate-limit-rpm 120
# → prints sk_live_… once (only the SHA-256 hash is stored)

pontifex-mcp keys list                 # never prints the secret; --all includes revoked
pontifex-mcp keys revoke key_user_kwame  # soft-delete + clears the Redis cache immediately
```

`keys create` flags: `--owner` (required), `--scopes` (required), `--label`, `--key-id`,
`--rate-limit-rpm` (default 60), `--expires-in-days`, `--key-plaintext` (pin an exact key
for CI/tests), `--json`. A 2-part scope is rejected — it could never match a tool.

Keys can also be provisioned by an upstream platform writing directly to
`pontifex_mcp_core.api_keys`; the CLI is the first-party path.

## Audit

The `audit=` argument controls where every tool call is logged:

```python
PontifexMCP("payments")                                  # → stdout (default)
PontifexMCP("payments", audit="audit.db")                # → durable SQLite file
PontifexMCP("payments", audit="postgresql+asyncpg://…")  # → Postgres (dialect auto-detected)
PontifexMCP("payments", audit=["audit.db", writer])      # → tee to several sinks
```

Each record captures caller identity, tool name, inputs, response time, cache hit, and
source IP. No migrations needed for the SQLite path.

## Cache

```python
mcp = PontifexMCP("payments", cache="redis://localhost:6379")

@mcp.tool(scope="balance:read")
async def get_balance() -> dict:
    if mcp.cache and (hit := await mcp.cache.get("balance")):
        return hit
    data = {"available": 421000, "currency": "usd"}
    if mcp.cache:
        await mcp.cache.set("balance", data, ttl_seconds=30)
    return data
```

- `cache=` accepts a Redis URL, `True`/`"redis"` (reads `REDIS_URL`), a `Cache` instance,
  or `None`/`False` (off).
- Reach it from any handler via `mcp.cache`. Guard with `if mcp.cache:` so the same handler
  works with or without Redis.
- Keys are prefixed with the namespace (`payments:balance`), so servers sharing a Redis can't collide.

## Generate tools from an existing API

Point at an OpenAPI spec and pontifex-mcp wraps allowlisted operations as governed tools —
no handler code:

```python
mcp.add_openapi(
    spec="http://localhost:9000/openapi.json",
    base_url="http://localhost:9000",
    include=["GET /charges/{charge_id}"],          # strict allowlist
    names={"GET /charges/{charge_id}": "get_charge"},
)
```

- `include` is an explicit allowlist — unlisted operations stay hidden.
- Mutating verbs (`POST`/`PUT`/`PATCH`/`DELETE`) are blocked even if listed; pass
  `allow_mutations=True` to permit them.
- Generated tools are named `{namespace}_{name}` (e.g. `payments_get_charge`).
- For upstream credentials, use the `auth=` connectors (`BearerFromEnv`, `HeaderFromEnv`,
  `TokenExchange`).

## Conventions and gotchas

- **Decorator needs parentheses** — `@mcp.tool()`, never `@mcp.tool`.
- **Scope form differs by layer**: `@tool(scope=)` takes `resource:action` (namespace implied);
  `keys create --scopes` takes the full `namespace:resource:action`.
- **Public API only**: import from `pontifex_mcp` (`PontifexMCP`, `ApiKeyAuth`, `JwtAuth`,
  `Cache`, `CallerIdentity`, `DataAdapter`, connectors). Deeper paths are internal.
- **Async everywhere** — handlers, adapters, and DB access are `async`.
- **Pydantic v2** — `model_dump()`, not `.dict()`.
- Run migrations with `pontifex-mcp db upgrade`; don't hand-write the schema.

## Upgrading to 0.5 (the namespace rename)

On pontifex-mcp < 0.5, the **domain** concept is now **namespace**. Your scope *values*,
API keys, tools, and auth config stay the same; only terminology and a few identifiers
move. Three fixes:

- Run `pontifex-mcp db upgrade` (migration `core_0005` renames `audit_log.domain` →
  `namespace` and `domain_registry` → `namespace_registry`; existing rows preserved).
- In any connector YAML, rename each `domain:` key to `namespace:`.
- If imported: `pontifex_mcp.models.DomainRegistryModel` → `NamespaceRegistryModel`.

`PontifexMCP(...)`, `@mcp.tool(scope=...)`, `ApiKeyAuth`/`JwtAuth`, and the CLI are
unchanged. Full steps: the "Upgrading" page in the docs.
