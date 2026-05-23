# MCP Platform

A modular MCP server platform that exposes structured data domains to AI agents. Connect Claude Desktop, Claude API, or any MCP client and query real-time market data, financial instruments, and more — each domain deployed as an independent service.

The first domain is **Ghana Stock Exchange (GSE)**, powered by the [kwayisi API](https://dev.kwayisi.org/apis/gse/).

## Quick Start (Consumer)

1. Get an API key from the platform operator
2. Configure your MCP client:

```json
{
  "mcpServers": {
    "gse": {
      "url": "https://mcp-gse.example.com/mcp",
      "headers": {
        "Authorization": "Bearer sk_live_your_key_here"
      }
    }
  }
}
```

3. Ask your AI agent about GSE data:
   - *"What are the current prices on the Ghana Stock Exchange?"*
   - *"Show me MTN Ghana's stock history for the last 30 days"*
   - *"Give me today's market summary"*

### Available GSE Tools

| Tool | Description | Scope Required |
|------|-------------|----------------|
| `gse_get_live_prices` | Real-time prices for all listed stocks | `gse:live_prices:read` |
| `gse_get_stock_price` | Price and trading data for a specific stock | `gse:stock_price:read` |
| `gse_get_stock_history` | Historical end-of-day prices | `gse:stock_history:read` |
| `gse_get_market_summary` | Composite index, volume, gainers/losers | `gse:market_summary:read` |
| `gse_get_company_info` | Company profile, directors, EPS, DPS, shares | `gse:company_info:read` |

## Quick Start (Developer)

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- Docker (for Redis + Postgres)

### Setup

```bash
git clone <repo-url> && cd mcp-platform

# Start infrastructure
docker compose up -d redis postgres

# Install dependencies
uv sync

# Run migrations
uv run alembic upgrade head

# Start the GSE server
uv run uvicorn gse_mcp.main:app --reload --port 8080
```

### Common Commands

```bash
uv run pytest                    # Run tests
uv run ruff check .              # Lint
uv run ruff format .             # Format
uv run ty check                  # Type check
uv run alembic revision --autogenerate -m "description"  # New migration
fly deploy --app mcp-gse         # Deploy to Fly.io
```

## Architecture

```
core/           Shared library — auth, cache, audit, circuit breaker, observability
domains/gse/    GSE domain module — tools, adapters, models
alembic/        DB migrations (core schema + per-domain schemas)
tests/          Unit, integration, and contract tests
deploy/         Dockerfiles, fly.toml
```

Each domain is a self-contained module that plugs into the shared core. Adding a new domain means adding a folder under `domains/` — core requires zero changes. See the [solution design doc](MCP_PLATFORM_SOLUTION_DESIGN_v2.md) for the full architecture.

### Key Design Decisions

- **Adapter pattern** with circuit breaker and fallback chain for resilient data sourcing
- **Scope-based permissions** using `domain:resource:action` (e.g. `gse:live_prices:read`)
- **Schema isolation** — each domain gets its own Postgres schema
- **API key auth** — the platform enforces scopes but doesn't manage users or billing

## Adding a New Domain

See [Section 20](MCP_PLATFORM_SOLUTION_DESIGN_v2.md#20-adding-a-new-domain-module) of the solution design doc.

## Deployment

Production runs on [Fly.io](https://fly.io). Each domain is a separate Fly app sharing managed Postgres and Redis. See [Section 17](MCP_PLATFORM_SOLUTION_DESIGN_v2.md#17-deployment) for details.

## License

TBD
