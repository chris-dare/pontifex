#!/usr/bin/env bash
# Container entrypoint.
# When called with arguments (e.g. docker-compose command override), run those.
# Otherwise start the MCP server directly.
# In production, migrations run via Fly's release_command — not here.
set -euo pipefail

if [ $# -gt 0 ]; then
    exec "$@"
fi

exec uv run --package gse-mcp python -m gse_mcp.main
