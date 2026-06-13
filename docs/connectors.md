# Connectors

If the system you're exposing already describes itself with an **OpenAPI 3.x spec**, you don't have to
hand-write a tool per operation. A connector reads the spec and generates the tools — each one wrapped
in the same `tool_runtime` as a hand-written tool, with the same scope check, audit row, and error
envelope. **Auto-generated does not mean ungoverned.**

Onboarding a system becomes *config* instead of *code*:

```yaml
# connectors.yaml
connectors:
  - domain: orders
    spec: https://api.internal/openapi.json   # URL or file path; JSON or YAML
    base_url: https://api.internal
    auth:
      type: bearer_env                        # how Pontifex authenticates downstream
      env_var: ORDERS_API_TOKEN
    include:                                  # the allowlist — nothing else is exposed
      - GET /orders
      - GET /orders/{order_id}
```

Point the server at it and start it — no domain module required:

```bash
export PONTIFEX_CONNECTORS_CONFIG=/app/connectors.yaml
```

Every included operation is now an authenticated, scoped, audited MCP tool. The same generator is
available in code when you want to mix generated and hand-written tools in one domain:

```python
from pontifex_mcp import BearerFromEnv, register_openapi_tools

register_openapi_tools(
    mcp,
    spec="https://api.internal/openapi.json",
    domain="orders",
    base_url="https://api.internal",
    audit=audit,
    auth=BearerFromEnv("ORDERS_API_TOKEN"),
    include=["GET /orders", "GET /orders/{order_id}"],
)
```

## The allowlist

Exposure is **opt-in per operation** and fails closed. A spec describing 200 operations exposes
*zero* of them until you list each one — and when the upstream team adds endpoints to their API, your
MCP server doesn't change until someone deliberately opts in.

Misconfiguration is a refusal to boot, never a silently different exposure:

| You write | What happens at startup |
| --- | --- |
| `- GET /orders` (exists in spec) | tool registered |
| `- GET /orers` (typo) | refuses to start, lists the operations the spec *does* have |
| `- POST /orders` without `allow_mutations: true` | refuses to start — mutating verbs need explicit enablement |
| `- POST /orders` with `allow_mutations: true` | tool registered; callers need the `write` scope |
| *(operation in spec, not in `include`)* | not a tool — agents can't see or call it |

## Derived scopes

Each generated tool requires a `domain:resource:action` scope, derived from the operation — so
spec-generated tools slot into the [scope model](concepts.md#scopes) unchanged, wildcards included:

| Part | Derived from | `GET /orders/{order_id}` |
| --- | --- | --- |
| `domain` | the connector's `domain` | `orders` |
| `resource` | first static path segment | `orders` |
| `action` | the verb: GET→`read`, POST/PUT/PATCH→`write`, DELETE→`delete` | `read` |

A caller needs `orders:orders:read` (or `orders:*:read`, or `orders:*:*`) before the call reaches the
downstream API.

## Tool names

A tool is named `{domain}_{operation_id}` (snake-cased). Specs with machine-generated operationIds
(FastAPI's defaults, for example) produce noisy names — override them per operation:

```yaml
    names:
      GET /orders/{order_id}: get_order   # tool becomes orders_get_order
```

Only the operations you key change; everything else keeps its spec-derived name. A `names` key that
doesn't match an included operation refuses to boot, same as an `include` typo.

## Authenticating downstream

The connector authenticates to the *backend* independently of how MCP callers authenticate to
Pontifex. The first question is **does the backend need to know *which* user is calling?**

- **No — it just needs to trust Pontifex.** Use a *service credential*: one identity for every caller.
  Per-user authorization still happens at Pontifex's scope layer, and the audit log records who made
  each call. This is the right default for most internal APIs.
- **Yes — it enforces its own per-user permissions.** Use *token exchange*: Pontifex swaps the caller's
  token for a downstream one minted for that user.

### Service credential

`bearer_env`
:   Sends `Authorization: Bearer <token>` with the token read from the named environment variable.

`header_env` *(add a `header:` name)*
:   Sends a static header (e.g. `X-API-Key`) with the value read from the named environment variable.

A missing variable fails at startup; the value is re-read on every request, so rotating the secret
doesn't require a restart.

### User identity (OAuth token exchange)

`token_exchange`
:   For a backend that shares your OAuth provider and enforces per-user authorization. Pontifex takes
    the caller's inbound token and exchanges it at the IdP ([RFC 8693](https://www.rfc-editor.org/rfc/rfc8693))
    for a *new* token carrying the backend's audience, on behalf of the user. The downstream then
    applies that user's own permissions.

```yaml
    auth:
      type: token_exchange
      token_endpoint: https://idp.example.com/oauth/token
      audience: https://api.internal              # the downstream's audience
      client_id_env: PONTIFEX_OAUTH_CLIENT_ID     # Pontifex's own IdP client,
      client_secret_env: PONTIFEX_OAUTH_CLIENT_SECRET  # presence checked at boot
```

The caller's token is **never forwarded as-is** (no passthrough — a token minted for Pontifex's
audience wouldn't be accepted downstream, and forwarding it would break the trust chain). Exchanged
tokens are cached, keyed per user and audience, for their lifetime.

#### Token cache backend

Exchanged tokens are cached so a user's repeated calls don't re-hit the IdP. The backend is a
deployment-level setting:

- `PONTIFEX_TOKEN_CACHE=memory` *(default)* — in-process only; tokens never leave the process or hit
  disk. Each worker caches independently.
- `PONTIFEX_TOKEN_CACHE=redis` — shared across workers via Redis (reuses `REDIS_URL`). Tokens are
  **encrypted at rest** with a Fernet key from `PONTIFEX_TOKEN_CACHE_KEY` (generate with
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`), so a
  Redis dump yields only ciphertext — the key lives in the environment, not in Redis. Missing
  `REDIS_URL` or `PONTIFEX_TOKEN_CACHE_KEY` fails at startup.

Using a managed KMS instead of an env-held key is tracked in #52.

The request is plain [RFC 8693](https://www.rfc-editor.org/rfc/rfc8693), so any compliant provider
works — Keycloak, Auth0, Microsoft Entra (on-behalf-of), Okta. Two things differ per provider:

- **What `audience` means.** It's the downstream's identifier as your provider expects it — a client
  ID (Keycloak), an API identifier URL (Auth0), a resource/scope (Entra). Set it to whatever your
  provider puts in the exchanged token's `aud`.
- **Provider-side authorization.** Each provider gates which clients may exchange for which audiences
  in its own model (Keycloak client/audience config, Auth0 client-grant settings, Entra API
  permissions + admin consent). That setup lives in your IdP, not in Pontifex.

Two optional knobs cover provider differences in the protocol itself:

- `client_auth: post` *(default)* sends the client credentials in the form (`client_secret_post`);
  `client_auth: basic` sends them as an HTTP Basic header for providers that require it.
- `default_ttl_seconds` — `expires_in` is optional in RFC 8693. By default a response without it is
  rejected (we can't size the cache TTL); set this to supply a fallback TTL for a provider that omits
  it.

A connector is *either* service-auth *or* user-auth — never both. **API-key callers can't use a
`token_exchange` connector** (they carry no token to exchange) and are rejected with a clear
`invalid_input`. If a backend genuinely needs both modes, define two connector entries with distinct
domains.

!!! note "Token-exchange caveats"

    Audience is verified on inspectable (JWT) exchanged tokens; opaque tokens are trusted. The IdP is
    on the call path — its failures surface as `source_unavailable` and are circuit-broken
    independently of the downstream connector, while a refused exchange surfaces as `invalid_input`.

#### Observability

When Logfire is configured, the token-exchange path emits metrics (audience / outcome / cache-result
labels only — never tokens):

- `pontifex.token_exchange.requests` — exchanges by `outcome` (`ok` / `rejected` / `unavailable` / `error`).
- `pontifex.token_exchange.duration_ms` — IdP exchange latency.
- `pontifex.token_cache.requests` — cache lookups by `result` (`hit` / `miss` / `coalesced`).

## Resilience and errors

Downstream calls go through a generated [`DataAdapter`](concepts.md#data-adapters) under
`DataSourceManager`, so circuit breaking applies like any hand-written adapter, and connector health
appears in `/health/ready` as `connector:<domain>`.

| Downstream result | Caller sees |
| --- | --- |
| 2xx | the response body in the standard success envelope |
| 4xx | `invalid_input` (400) — caller error; the breaker is untouched |
| 5xx or network error | `source_unavailable` (503, retryable) — counted by the circuit breaker |

!!! note "v1 limits"

    Path and query parameters and `application/json` request bodies are supported; header/cookie
    parameters are ignored. `$ref` resolution is local (`#/…`) only. Responses are not cached
    (`cache_hit` is always `false`).
