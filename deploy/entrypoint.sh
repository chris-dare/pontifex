#!/usr/bin/env bash
# Container entrypoint: run alembic migrations (HTTP mode only), then dispatch.
set -euo pipefail

if [ "${GSE_MCP_TRANSPORT:-streamable-http}" = "stdio" ]; then
    # stdio mode does not require Postgres / Redis; skip migrations.
    exec uv run --package gse-mcp python -m gse_mcp.main
fi

echo "[entrypoint] running migrations: alembic upgrade heads"
uv run --package gse-mcp alembic -c alembic/alembic.ini upgrade heads

echo "[entrypoint] starting MCP server (streamable-http)"
exec uv run --package gse-mcp python -m gse_mcp.main
