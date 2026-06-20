# Set up Postgres & Redis

Pontifex needs two backing services. Bring them up locally, then point at production.

If you want the server running, follow the steps below. To hand the work to a coding
agent instead, use the [copy-paste prompt](#hand-it-to-a-coding-agent) at the end.

## The mental model

Two stores, two jobs:

- **Postgres** holds your **API keys and the audit log**, the durable record.
- **Redis** backs **rate limiting and the cache** (and the optional token-exchange
  cache).

The server reads them from two environment variables, `DATABASE_URL` and `REDIS_URL`,
and **fails fast** if either is missing. Start both, set two variables, run the
migrations.

## Step 1: start both locally

Use Docker Compose. Drop this in `docker-compose.yml`:

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: mcp
      POSTGRES_PASSWORD: mcp
      POSTGRES_DB: mcp_platform
    ports: ["5432:5432"]
  redis:
    image: redis:7
    ports: ["6379:6379"]
```

Bring them up:

```bash
docker compose up -d
```

## Step 2: point the server at them

```bash
export DATABASE_URL=postgresql+asyncpg://mcp:mcp@localhost:5432/mcp_platform
export REDIS_URL=redis://localhost:6379/0
```

!!! note "The driver matters"

    `DATABASE_URL` must use the **`postgresql+asyncpg://`** scheme. Pontifex is async
    all the way down. A plain `postgresql://` URL won't work.

## Step 3: create the tables

Pontifex's API-key and audit tables live in a `pontifex_mcp_core` schema. Create
them with the bundled migrations:

```bash
pontifex-mcp db upgrade
```

## Verify it works

Three checks.

```bash
# Postgres — the core tables exist
docker compose exec postgres psql -U mcp -d mcp_platform -c '\dt core.*'

# Redis — responds
docker compose exec redis redis-cli ping     # -> PONG
```

Once your server is running, its readiness probe confirms both are reachable:

```bash
curl http://localhost:8080/health/ready
```

A down dependency shows up here, not as a surprise at the first tool call.

## Going to production

Same two variables, real services:

1. Provision **managed Postgres 16** and **Redis 7** (any cloud will do).
2. Set `DATABASE_URL` and `REDIS_URL` as secrets in your platform, never in code.
3. Run `pontifex-mcp db upgrade` against the production database once, as part of
   your release.

Nothing about the infrastructure is Pontifex-specific. Full deployment flow:
[Deploy to production](deploy.md).

## Hand it to a coding agent

Paste this to a coding agent working in your project:

```text
Stand up Postgres 16 and Redis 7 for my Pontifex MCP server, locally with Docker
Compose.

1. Create docker-compose.yml with:
   - a postgres:16 service (user mcp, password mcp, db mcp_platform, port 5432)
   - a redis:7 service (port 6379)
2. Bring them up with `docker compose up -d`.
3. Export:
   DATABASE_URL=postgresql+asyncpg://mcp:mcp@localhost:5432/mcp_platform
   REDIS_URL=redis://localhost:6379/0
4. Run the migrations: `pontifex-mcp db upgrade`.
5. Verify: the `pontifex_mcp_core` schema tables exist in Postgres, and `redis-cli ping`
   returns PONG.

Report any failure with the exact command output.
```

## Next

- Let real callers in: [Authenticate callers](authenticate-callers.md).
- Wire interactive login: [Set up OAuth, step by step](oauth-setup.md).
- Ship it: [Deploy to production](deploy.md).
