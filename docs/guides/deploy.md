# Deploy to production

Pontifex is a library you run. It needs three things around it: two backing
services, a handful of environment variables, and a provider for interactive auth.

## Stand up the infrastructure

1.  **Postgres.** Provision Postgres 16 and run your migrations. The API-key and audit
    tables live in a `pontifex_mcp_core` schema.
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
stable in production. [Configuration](../reference/configuration.md) lists every
variable, what it does, and what's required.

## Wire an OAuth provider

For interactive clients, point the `AUTH_*` variables at your provider (see
[Authenticate callers](authenticate-callers.md#oauth-21-interactive-clients)).

Pontifex exposes **RFC 9728 protected-resource metadata** and a `WWW-Authenticate`
challenge. Spec-compliant MCP clients discover the authorization server and bootstrap
the flow on their own. No out-of-band config.

!!! tip

    Keep the IdP/auth config and the DB/Redis URLs in bare, unprefixed variables.
    They're the same for every server regardless of its namespace. Only your
    namespace-specific settings carry your `env_prefix`.

## Probe health

Point your platform's health checks at these:

`/health/live`
:   Liveness. The process is up.

`/health/ready`
:   Readiness. Dependencies (database, upstreams, connectors) are reachable. A
    down data source shows up here (see [Resilient adapters](resilient-adapters.md)).

## A note on secrets

Database, Redis, and provider credentials all come from the environment; nothing is
hardcoded. Store them in your platform's secret manager (Pontifex's own pre-prod uses
Doppler) and rotate them there. Service-credential and token-cache values are re-read
per request, so rotation doesn't require a restart.

## Hand it to a coding agent

Paste this to a coding agent, naming your target platform:

```text
Deploy my Pontifex MCP server to <my platform: Fly.io / Render / a container on
ECS / …>.

1. Build and run the ASGI app from create_mcp_http_app with uvicorn.
2. Provision managed Postgres 16 and Redis 7, and wire DATABASE_URL
   (postgresql+asyncpg://…) and REDIS_URL as secrets — never in the image.
3. Run `pontifex-mcp db upgrade` against the production database as a
   release step.
4. If interactive OAuth is in use, set the AUTH_* group and PUBLIC_BASE_URL to the
   deployment's real public URL.
5. Point the platform's health check at /health/ready, and confirm it returns OK
   after deploy.

Fail the deploy if /health/ready isn't green. Don't print secret values.
```

The prompt names the result you want and the rules to hold; the agent picks the
platform-specific commands.
