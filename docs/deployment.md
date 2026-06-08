# Deployment

## Configuration

Infrastructure settings read from **bare, unprefixed** environment variables. Domain-specific settings
on your `CoreSettings` subclass read with your domain's own `env_prefix`.

`DATABASE_URL` *(required)*
:   Async Postgres DSN (`postgresql+asyncpg://…`). Stores API keys and the audit log. The app **fails
    fast** if this is unset.

`REDIS_URL` *(required)*
:   Redis DSN (`redis://…`). Backs rate limiting and the cache. Also required.

`AUTH_JWKS_URL`
:   Your OIDC provider's JWKS endpoint. Set the `AUTH_*` group to enable the OAuth/JWT path.

`AUTH_ISSUER` / `AUTH_AUDIENCE` / `AUTH_SCOPES_CLAIM`
:   The expected token issuer, audience, and the claim that carries scopes (e.g. `permissions` for
    Auth0, `scp` for Entra).

`PUBLIC_BASE_URL`
:   The canonical URL advertised in OAuth discovery metadata. Set this in production so the value is
    stable and not derived from request headers.

## Infrastructure

1.  **Postgres** — provision a Postgres 16 database and run your migrations. The library's API-key and
    audit tables live in a `core` schema.
2.  **Redis** — provision Redis 7 for rate-limit counters and the response cache.
3.  **Run the ASGI app** — serve the app from `create_mcp_http_app` with any ASGI server (`uvicorn`),
    behind your load balancer or platform of choice.

## Wiring an OAuth provider

For interactive clients, point the `AUTH_*` variables at your provider. `pontifex-mcp` exposes
**RFC 9728 protected-resource metadata** and a `WWW-Authenticate` challenge, so spec-compliant MCP
clients discover the authorization server and bootstrap the flow on their own — no out-of-band config.

!!! note

    Map your provider's roles/permissions to `domain:resource:action` scopes, and surface them in the
    configured scopes claim. New users can be auto-granted a read-only role if your provider supports a
    post-login hook.

## Health checks

`/health/live`
:   Liveness — the process is up.

`/health/ready`
:   Readiness — dependencies (database, upstreams) are reachable. Point your platform's health probe here.
