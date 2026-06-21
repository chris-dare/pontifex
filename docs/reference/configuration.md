# Configuration

Every setting Pontifex reads from the environment.

Two kinds of variable:

- **Infrastructure** settings read from **bare, unprefixed** names. They're the same
  for every server, regardless of namespace: auth, the canonical URL, the shared DB and
  Redis connections.
- **Namespace** settings on your `CoreSettings` subclass read with **your namespace's
  `env_prefix`** (e.g. `ORDERS_…`).

## Required

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | Async Postgres DSN (`postgresql+asyncpg://…`). Stores API keys and the audit log. **Fails fast if unset.** |
| `REDIS_URL` | Redis DSN (`redis://…`). Backs rate limiting and the cache. **Fails fast if unset.** |

## OAuth / JWT

Set the `AUTH_*` group to turn on the OAuth/JWT path. Omit it and only the API-key path
is active.

| Variable | Value |
| --- | --- |
| `AUTH_JWKS_URL` | Your provider's JWKS endpoint. |
| `AUTH_ISSUER` | Expected token issuer (`iss`). |
| `AUTH_AUDIENCE` | The resource-server identifier the token's `aud` must carry. |
| `AUTH_SCOPES_CLAIM` | The claim that carries scopes: `permissions` (Auth0), `scp` or `roles` (Entra). |
| `AUTH_AUTHORIZATION_SERVER` | Advertised in the discovery metadata. |
| `PUBLIC_BASE_URL` | Canonical URL advertised in OAuth discovery. Set it in production so the value is stable, not derived from request headers. |

## Connectors

| Variable | Value |
| --- | --- |
| `PONTIFEX_CONNECTORS_CONFIG` | Path to a [connectors](../learn/connect-an-api.md) YAML file. When set, the server generates governed tools from the listed OpenAPI specs at startup. |

## Token-exchange cache

For the [token-exchange](../guides/downstream-auth.md#the-exchanged-token-cache) path.

| Variable | Value |
| --- | --- |
| `PONTIFEX_TOKEN_CACHE` | `memory` (default, in-process) or `redis` (shared, reuses `REDIS_URL`). |
| `PONTIFEX_TOKEN_CACHE_KEY` | Required when `redis`. A Fernet key (`Fernet.generate_key()`) that encrypts tokens at rest. Held in the environment, never in Redis. |

## Health endpoints

Not configured; always served.

| Endpoint | Reports |
| --- | --- |
| `/health/live` | Liveness. The process is up. |
| `/health/ready` | Readiness. Database, upstreams, and connectors are reachable. |
