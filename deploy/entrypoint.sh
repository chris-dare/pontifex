#!/usr/bin/env bash
# Container entrypoint: start the MCP server.
# Migrations are run by the CI/CD pipeline before deploy, not at container start.
set -euo pipefail

exec uv run --package gse-mcp python -m gse_mcp.main
