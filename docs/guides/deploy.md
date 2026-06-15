# Deploy to production

Pontifex is a library you run. This guide is what it needs around it: two backing
services, a handful of environment variables, and a provider for interactive auth.

## Stand up the infrastructure

1.  **Postgres.** Provision Postgres 16 and run your migrations. The API-key and audit
    tables live in a `core` schema.
2.  **Redis.** Provision Redis 7 for rate-limit counters and the response cache.
3.  **The app.** Serve the app from `create_mcp_http_app` with any ASGI server
    (`uvicorn`), behind your load balancer or platform of choice.

## Set the environment

The two infrastructure variables are required. The app **fails fast** if either is
missing.

```bash
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db   # API keys + audit log
REDIS_URL=redis://host:6379/0                              # rate limiting + cache
```

Add the `AUTH_*` group to turn on OAuth, and `PUBLIC_BASE_URL` so discovery metadata is
stable in production. The full list — every variable, what it does, what's required —
is in [Configuration](../reference/configuration.md).

## Wire an OAuth provider

For interactive clients, point the `AUTH_*` variables at your provider (see
[Authenticate callers](authenticate-callers.md#oauth-21-interactive-clients)).

Pontifex exposes **RFC 9728 protected-resource metadata** and a `WWW-Authenticate`
challenge. Spec-compliant MCP clients discover the authorization server and bootstrap
the flow on their own. No out-of-band config.

!!! tip

    Keep the IdP/auth config and the DB/Redis URLs in bare, unprefixed variables —
    they're the same for every server regardless of its domain. Only your
    domain-specific settings carry your `env_prefix`.

## Probe health

Point your platform's health checks at these:

`/health/live`
:   Liveness. The process is up.

`/health/ready`
:   Readiness. Dependencies — database, upstreams, connectors — are reachable. A
    down data source shows up here (see [Resilient adapters](resilient-adapters.md)).

## A note on secrets

Database, Redis, and provider credentials all come from the environment — nothing is
hardcoded. Store them in your platform's secret manager (Pontifex's own pre-prod uses
Doppler) and rotate them there. Service-credential and token-cache values are re-read
per request, so rotation doesn't require a restart.
